"""
Phase B & C: Multi-agent Grader x Auditor (x Retriever/Parser) combinations.

Each "combo" assigns a model to the Grader role, a model to the Auditor role,
and optionally a model to the Retriever/Parser role (None = skip that agent
call and feed the raw rubric straight to the Grader). The confidence engine,
prompts, and score clamping are ported verbatim from the main branch's
run_experiment_2_audit.py / llm_service.py / confidence.py so results are
directly comparable to the reference Model Comparison PDFs.

Combos to run are defined in COMBOS below; edit that list between phases
(Phase B: vary grader/auditor with parser=None; Phase C: vary parser with the
winning grader/auditor fixed).

Usage:
    python run_multiagent_evaluation.py [combo_name ...]
    (defaults to all combos in COMBOS if no args given)
"""

import os
import sys
import json
import time
import pandas as pd
from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
load_dotenv(dotenv_path=os.path.join(SCRIPT_DIR, ".env"))

from model_config import MODELS
from data_loader import load_dataset, is_blank_answer
from agents import call_parser_agent, call_grader_agent, call_auditor_agent, evaluate_confidence_and_status, clamp_score
from metrics import compute_grading_metrics, compute_flagging_metrics
from budget import check_budget

RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Phase B: Grader x Auditor combos (parser=None). Per user request: Claude as
# Grader, tested against all 3 models as Auditor (self-audit + 2 cross-checks).
# ---------------------------------------------------------------------------
COMBOS = [
    {"name": "G-claude_A-claude", "grader": "claude", "auditor": "claude", "parser": None},
    {"name": "G-claude_A-nemotron", "grader": "claude", "auditor": "nemotron", "parser": None},
    {"name": "G-claude_A-gemini", "grader": "claude", "auditor": "gemini", "parser": None},
]


def extract_feedback_text(fb) -> str:
    if isinstance(fb, dict):
        return fb.get("summary", "")
    return fb or ""


def run_combo(combo, records):
    name = combo["name"]
    grader_id = MODELS[combo["grader"]]
    auditor_id = MODELS[combo["auditor"]]
    parser_key = combo.get("parser")
    parser_id = MODELS[parser_key] if parser_key else None

    raw_csv_path = os.path.join(RESULTS_DIR, f"multiagent_{name}_raw.csv")
    raw_json_path = os.path.join(RESULTS_DIR, f"multiagent_{name}_raw.json")

    done_rows = []
    done_keys = set()
    if os.path.exists(raw_csv_path):
        existing = pd.read_csv(raw_csv_path)
        done_rows = existing.to_dict("records")
        done_keys = set(zip(existing["response_id"].tolist(), existing["question_no"].tolist()))
        print(f"[{name}] Resuming: {len(done_keys)} responses already done.")

    json_log = []
    if os.path.exists(raw_json_path):
        with open(raw_json_path, "r", encoding="utf-8") as f:
            json_log = json.load(f)

    # NOTE: response_id is the STUDENT's ID, reused across their Q6/Q8/Q9/Q22
    # responses -- dedup must use the (response_id, question_no) pair.
    total = len(records)
    for i, rec in enumerate(records, 1):
        if (rec["response_id"], rec["question_no"]) in done_keys:
            continue

        try:
            spend = check_budget(f"multiagent/{name}")
        except RuntimeError as e:
            print(str(e))
            print(f"[{name}] Stopping early with {len(done_rows)} responses saved.")
            break

        print(f"[{name}] ({i}/{total}, spend so far ${spend:.2f}) {rec['response_id']} ({rec['question_no']})...")

        total_cost = 0.0
        parser_latency_s = 0.0
        grader_latency_s = 0.0
        auditor_latency_s = 0.0
        errors = []
        max_score = rec["max_score"]

        if is_blank_answer(rec["student_answer"]):
            grader_score = 0.0
            auditor_score = 0.0
            audit_passed = True
            grader_result = {
                "overall_score": 0.0,
                "confidence_score": 1.0,
                "status": "graded",
                "reasoning": "Blank answer provided. 0 marks awarded.",
                "feedback": {"summary": "No response provided.", "breakdown": []},
                "highlights": [],
            }
            auditor_result = {"auditor_score": 0.0, "audit_passed": True, "conflicting_questions": [], "discrepancy_note": ""}
        else:
            structured_rubric = None
            if parser_id:
                structured_rubric, p_meta = call_parser_agent(
                    rec["question_no"], rec["rubric"], max_score, parser_id
                )
                total_cost += p_meta["cost_usd"]
                parser_latency_s += p_meta["latency_s"]
                if p_meta["error"]:
                    errors.append(f"parser:{p_meta['error']}")

            grader_result, g_meta = call_grader_agent(
                rec["question_no"], rec["rubric"], max_score, rec["student_answer"],
                grader_id, structured_rubric=structured_rubric,
            )
            total_cost += g_meta["cost_usd"]
            grader_latency_s += g_meta["latency_s"]
            if g_meta["error"] or grader_result is None:
                errors.append(f"grader:{g_meta['error']}")
                grader_result = grader_result or {"overall_score": 0.0}
            grader_score = clamp_score(grader_result.get("overall_score", 0.0), max_score)

            auditor_result, a_meta = call_auditor_agent(
                rec["question_no"], rec["rubric"], max_score, rec["student_answer"],
                grader_result, auditor_id,
            )
            total_cost += a_meta["cost_usd"]
            auditor_latency_s += a_meta["latency_s"]
            if a_meta["error"] or auditor_result is None:
                errors.append(f"auditor:{a_meta['error']}")
                auditor_result = auditor_result or {"auditor_score": grader_score, "audit_passed": True, "conflicting_questions": [], "discrepancy_note": ""}
            auditor_score = clamp_score(auditor_result.get("auditor_score", grader_score), max_score)
            audit_passed = bool(auditor_result.get("audit_passed", True))

        # Attach audit result to the grader's evaluation and run the ported
        # deterministic confidence engine exactly as main's run_manual_audit_experiment does.
        score_discrepancy = round(abs(grader_score - auditor_score), 2)
        max_denom = max_score if max_score > 0 else 10.0
        agreement_ratio = max(0.0, 1.0 - (score_discrepancy / max_denom))
        grader_result["multi_agent_audit"] = {
            "auditor_passed": audit_passed,
            "auditor_score": auditor_score,
            "auditor_breakdown": auditor_result.get("auditor_breakdown", []) if isinstance(auditor_result, dict) else [],
            "score_discrepancy": score_discrepancy,
            "agreement_ratio": round(agreement_ratio, 2),
            "conflicting_questions": auditor_result.get("conflicting_questions", []) if isinstance(auditor_result, dict) else [],
            "audit_note": auditor_result.get("discrepancy_note", "") if isinstance(auditor_result, dict) else "",
            "model_used": auditor_id,
        }

        conf = evaluate_confidence_and_status(grader_result, str(rec["student_answer"]), max_score)
        total_latency_s = parser_latency_s + grader_latency_s + auditor_latency_s

        # Column set/order matches main branch's run_experiment_2_audit.py
        # (response_id..audit_note), with our own additions appended after.
        row = {
            "response_id": rec["response_id"],
            "question_no": rec["question_no"],
            "human_score": rec["human_score"],
            "max_score": max_score,
            "grader_score": grader_score,
            "auditor_score": auditor_score,
            "score_discrepancy": score_discrepancy,
            "audit_passed": audit_passed,
            "confidence_score": conf["confidence_score"],
            "status": conf["status"],
            "flag_reasons": "; ".join(conf.get("flag_reasons", [])),
            "actual_error_ge_1mark": abs(grader_score - rec["human_score"]) >= 1.0,
            "grader_absolute_error": round(abs(grader_score - rec["human_score"]), 2),
            "grader_latency_ms": round(grader_latency_s * 1000),
            "auditor_latency_ms": round(auditor_latency_s * 1000),
            "total_latency_ms": round(total_latency_s * 1000),
            "total_cost_usd": round(total_cost, 6),
            "student_answer": str(rec["student_answer"]),
            "grader_reasoning": str(grader_result.get("reasoning", "")),
            "audit_note": grader_result["multi_agent_audit"]["audit_note"],
            "grader_feedback": extract_feedback_text(grader_result.get("feedback", "")),
            "errors": "; ".join(errors) if errors else None,
        }
        done_rows.append(row)
        done_keys.add((rec["response_id"], rec["question_no"]))

        json_log.append(
            {
                "response_id": rec["response_id"],
                "question_no": rec["question_no"],
                "human_score": rec["human_score"],
                "grader_result": grader_result,
                "auditor_result": auditor_result,
            }
        )

        pd.DataFrame(done_rows).to_csv(raw_csv_path, index=False)
        with open(raw_json_path, "w", encoding="utf-8") as f:
            json.dump(json_log, f, indent=2)

    return pd.DataFrame(done_rows)


def summarize_combo(combo, df: pd.DataFrame):
    # status here uses 'graded'/'flagged' (ported engine), while metrics.py's
    # compute_flagging_metrics expects 'Auto-Approved'/'Action Required' --
    # remap for that helper without changing what's stored in the CSV.
    df = df.copy()
    df["_status_norm"] = df["status"].map({"graded": "Auto-Approved", "flagged": "Action Required"})

    grading = compute_grading_metrics(df, score_col="grader_score")
    flagging = compute_flagging_metrics(df, score_col="grader_score", status_col="_status_norm")
    summary = {
        "combo_name": combo["name"],
        "parser_model": combo.get("parser") or "(none)",
        "grader_model": combo["grader"],
        "auditor_model": combo["auditor"],
        **grading,
        **flagging,
        "total_cost_usd": round(float(df["total_cost_usd"].sum()), 4),
        "avg_latency_s": round(float(df["total_latency_ms"].mean()) / 1000.0, 2),
    }
    return summary


def main():
    if not COMBOS:
        print("COMBOS is empty. Edit run_multiagent_evaluation.py to define combos for this phase.")
        sys.exit(1)

    # Optional: restrict this invocation to specific combo name(s), so combos
    # can be launched as separate parallel processes (each writes to its own
    # multiagent_<name>_raw.csv/json, so there's no cross-process file race).
    requested = sys.argv[1:]
    combos_to_run = COMBOS
    if requested:
        combos_to_run = [c for c in COMBOS if c["name"] in requested]
        unknown = set(requested) - {c["name"] for c in COMBOS}
        if unknown:
            print(f"Unknown combo name(s): {unknown}. Valid: {[c['name'] for c in COMBOS]}")
        if not combos_to_run:
            sys.exit(1)

    print("Loading dataset (25 responses/question, seed=42)...")
    records = load_dataset()
    print(f"Loaded {len(records)} responses.")

    all_summaries = []
    for combo in combos_to_run:
        print(f"\n=== Running combo: {combo['name']} (parser={combo.get('parser')}, grader={combo['grader']}, auditor={combo['auditor']}) ===")
        t0 = time.time()
        df = run_combo(combo, records)
        elapsed = time.time() - t0
        print(f"[{combo['name']}] Completed in {elapsed/60:.1f} min.")
        summary = summarize_combo(combo, df)
        all_summaries.append(summary)
        print(f"[{combo['name']}] ICC={summary.get('icc_a1')} MAE={summary.get('mae')} FlagRecall={summary.get('flagging_recall_pct')} Cost=${summary.get('total_cost_usd')}")

    existing_summary_path = os.path.join(RESULTS_DIR, "multiagent_summary.csv")
    if os.path.exists(existing_summary_path):
        prev = pd.read_csv(existing_summary_path)
        prev = prev[~prev["combo_name"].isin([s["combo_name"] for s in all_summaries])]
        combined = pd.concat([prev, pd.DataFrame(all_summaries)], ignore_index=True)
    else:
        combined = pd.DataFrame(all_summaries)
    combined.to_csv(existing_summary_path, index=False)
    print(f"\nSaved multi-agent summary to {existing_summary_path}")


if __name__ == "__main__":
    if not os.getenv("OPENROUTER_API_KEY"):
        print("Please set OPENROUTER_API_KEY in evaluation/.env before running.")
        sys.exit(1)
    main()
