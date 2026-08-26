"""
Phase A: Single-model Grader-only baselines.

Runs the Grader Agent alone (no Retriever/Auditor) for each of the three
candidate models against the same 25-responses-per-question sample, so
results are directly comparable to each other and to the existing
Gemini 3.1 Flash Lite / Nemotron 3 Super benchmark numbers.

Usage:
    python run_baseline_evaluation.py [model_key ...]
    e.g. python run_baseline_evaluation.py gemini claude nemotron
    (defaults to all three if no args given)
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
from agents import call_grader_agent, clamp_score
from metrics import compute_grading_metrics
from budget import check_budget

RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def run_baseline_for_model(model_key: str, model_id: str, records):
    raw_csv_path = os.path.join(RESULTS_DIR, f"baseline_{model_key}_raw.csv")
    raw_json_path = os.path.join(RESULTS_DIR, f"baseline_{model_key}_raw.json")

    done_rows = []
    done_keys = set()
    if os.path.exists(raw_csv_path):
        existing = pd.read_csv(raw_csv_path)
        done_rows = existing.to_dict("records")
        done_keys = set(zip(existing["response_id"].tolist(), existing["question_no"].tolist()))
        print(f"[{model_key}] Resuming: {len(done_keys)} responses already graded.")

    json_log = []
    if os.path.exists(raw_json_path):
        with open(raw_json_path, "r", encoding="utf-8") as f:
            json_log = json.load(f)

    # NOTE: response_id is the STUDENT's ID, reused across their Q6/Q8/Q9/Q22
    # responses -- it is NOT a unique key by itself. Dedup must use the
    # (response_id, question_no) pair, otherwise a student's later questions
    # get silently skipped as "already graded" once their first question is done.
    total = len(records)
    for i, rec in enumerate(records, 1):
        if (rec["response_id"], rec["question_no"]) in done_keys:
            continue

        try:
            spend = check_budget(f"baseline/{model_key}")
        except RuntimeError as e:
            print(str(e))
            print(f"[{model_key}] Stopping early with {len(done_rows)} responses saved.")
            break

        print(f"[{model_key}] ({i}/{total}, spend so far ${spend:.2f}) grading response {rec['response_id']} ({rec['question_no']})...")

        if is_blank_answer(rec["student_answer"]):
            score = 0.0
            meta = {"latency_s": 0.0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "raw_text": "", "error": None}
            parsed = {
                "overall_score": 0.0,
                "confidence_score": 1.0,
                "status": "graded",
                "reasoning": "Blank answer provided. 0 marks awarded.",
                "feedback": {"summary": "No response provided.", "breakdown": []},
                "highlights": [],
            }
        else:
            parsed, meta = call_grader_agent(
                question_no=rec["question_no"],
                rubric=rec["rubric"],
                max_score=rec["max_score"],
                student_answer=rec["student_answer"],
                model=model_id,
            )
            if parsed is None:
                print(f"  [Warning] Failed after retries: {meta.get('error')}")
                score = 0.0
                parsed = {"overall_score": 0.0, "reasoning": f"FAILED: {meta.get('error')}"}
            else:
                score = clamp_score(parsed.get("overall_score", 0.0), rec["max_score"])

        feedback_obj = (parsed or {}).get("feedback", {})
        feedback_summary = feedback_obj.get("summary", "") if isinstance(feedback_obj, dict) else str(feedback_obj)

        row = {
            "response_id": rec["response_id"],
            "question_no": rec["question_no"],
            "max_score": rec["max_score"],
            "human_score": rec["human_score"],
            "ai_score": score,
            "ai_feedback": feedback_summary,
            "latency_s": meta["latency_s"],
            "input_tokens": meta["input_tokens"],
            "output_tokens": meta["output_tokens"],
            "cost_usd": meta["cost_usd"],
            "error": meta["error"],
        }
        done_rows.append(row)
        done_keys.add((rec["response_id"], rec["question_no"]))

        json_log.append(
            {
                "response_id": rec["response_id"],
                "question_no": rec["question_no"],
                "human_score": rec["human_score"],
                "ai_evaluation": parsed,
            }
        )

        # Save incrementally so a crash / rate-limit never loses progress.
        pd.DataFrame(done_rows).to_csv(raw_csv_path, index=False)
        with open(raw_json_path, "w", encoding="utf-8") as f:
            json.dump(json_log, f, indent=2)

    return pd.DataFrame(done_rows)


def summarize(model_key: str, df: pd.DataFrame):
    overall = compute_grading_metrics(df, score_col="ai_score")
    overall["model_key"] = model_key
    overall["model_id"] = MODELS[model_key]

    total_cost = round(float(df["cost_usd"].sum()), 4)
    avg_latency = round(float(df["latency_s"].mean()), 2)
    overall["total_cost_usd"] = total_cost
    overall["avg_latency_s"] = avg_latency

    per_question = []
    for q, sub in df.groupby("question_no"):
        m = compute_grading_metrics(sub, score_col="ai_score")
        m["question_no"] = q
        m["model_key"] = model_key
        per_question.append(m)

    return overall, per_question


def main():
    args = sys.argv[1:]
    model_keys = args if args else ["gemini", "claude", "nemotron"]

    print("Loading dataset (25 responses/question)...")
    records = load_dataset()
    print(f"Loaded {len(records)} responses across {len(set(r['question_no'] for r in records))} questions.")

    all_overall = []
    all_per_question = []

    for model_key in model_keys:
        if model_key not in MODELS:
            print(f"Unknown model key '{model_key}', skipping. Valid keys: {list(MODELS.keys())}")
            continue
        model_id = MODELS[model_key]
        print(f"\n=== Running baseline for {model_key} ({model_id}) ===")
        t0 = time.time()
        df = run_baseline_for_model(model_key, model_id, records)
        elapsed = time.time() - t0
        print(f"[{model_key}] Completed in {elapsed/60:.1f} min.")

        overall, per_question = summarize(model_key, df)
        all_overall.append(overall)
        all_per_question.extend(per_question)
        print(f"[{model_key}] Overall ICC={overall.get('icc_a1')} MAE={overall.get('mae')} Cost=${overall.get('total_cost_usd')}")

    if all_overall:
        summary_path = os.path.join(RESULTS_DIR, "baseline_summary.csv")
        new_overall = pd.DataFrame(all_overall)
        if os.path.exists(summary_path):
            prev = pd.read_csv(summary_path)
            prev = prev[~prev["model_key"].isin(new_overall["model_key"])]
            new_overall = pd.concat([prev, new_overall], ignore_index=True)
        new_overall.to_csv(summary_path, index=False)

        per_q_path = os.path.join(RESULTS_DIR, "baseline_per_question.csv")
        new_per_q = pd.DataFrame(all_per_question)
        if os.path.exists(per_q_path):
            prev_pq = pd.read_csv(per_q_path)
            prev_pq = prev_pq[~prev_pq["model_key"].isin(new_per_q["model_key"])]
            new_per_q = pd.concat([prev_pq, new_per_q], ignore_index=True)
        new_per_q.to_csv(per_q_path, index=False)
        print(f"\nSaved summary to {summary_path}")


if __name__ == "__main__":
    if not os.getenv("OPENROUTER_API_KEY"):
        print("Please set OPENROUTER_API_KEY in evaluation/.env before running.")
        sys.exit(1)
    main()
