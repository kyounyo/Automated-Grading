import os
import re
import sys
import glob
import json
import time
import argparse
import pandas as pd
import pingouin as pg
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Path setup
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(script_dir, "../backend"))
sys.path.append(backend_dir)

# Load environment variables
load_dotenv(dotenv_path=os.path.join(script_dir, ".env"))

# Import exact backend agent & confidence engine implementations
from app.services.llm_service import (
    call_primary_grading_agent,
    call_auditor_verification_agent,
    get_openrouter_api_key
)
from app.services.confidence import evaluate_confidence_and_status

if not get_openrouter_api_key():
    print("❌ Error: No OPENROUTER_API_KEY found in evaluation/.env")
    sys.exit(1)

# ---------------------------------------------------------
# KNOWN PRESET MODELS & PRICING
# ---------------------------------------------------------
PRESET_MODELS = {
    "A": {
        "id": "A",
        "name": "Gemini 3.1 Flash Lite",
        "file_tag": "Gemini_3.1_Flash_Lite",
        "model_str": os.getenv("MODEL_A_STR", "google/gemini-3.1-flash-lite"),
        "cost_per_1k_in": 0.0001,
        "cost_per_1k_out": 0.0004
    },
    "B": {
        "id": "B",
        "name": "Nemotron 3 Super 120B",
        "file_tag": "Nemotron_3_Super_120B",
        "model_str": os.getenv("MODEL_B_STR", "nvidia/nemotron-3-super-120b-a12b"),
        "cost_per_1k_in": 0.0002,
        "cost_per_1k_out": 0.0008
    },
    "C": {
        "id": "C",
        "name": "Claude 4.6 Sonnet",
        "file_tag": "Claude_4.6_Sonnet",
        "model_str": os.getenv("MODEL_C_STR", "anthropic/claude-sonnet-4.6"),
        "cost_per_1k_in": 0.0030,
        "cost_per_1k_out": 0.0150
    }
}

# ---------------------------------------------------------
# SPECIALIZED OPEN-ENDED GRADING PROMPT INSTRUCTIONS
# (Modify this prompt string to customize open-ended rules)
# ---------------------------------------------------------
OPEN_ENDED_GRADING_RULES = """
### OPEN-ENDED GRADING PROTOCOL
You are grading an open-ended response from an undergraduate pharmacy
student. Grade the response against the provided question and marking
rubric.

1. RUBRIC-BASED EVALUATION
Break the marking rubric into distinct scoring criteria and evaluate each
criterion independently.

For each criterion:
1. Identify the knowledge, reasoning, mechanism, or justification that the
   criterion is assessing.
2. Identify relevant evidence in the student's response.
3. Decide whether the evidence demonstrates the required criterion.
4. Award the mark if the criterion is demonstrated.
5. Withhold the mark if the criterion is not demonstrated.

The rubric defines the expected knowledge and scoring points. Use it as the
primary basis for grading.

2. CONCEPTUAL EQUIVALENCE
Do not require the student's wording to exactly match the rubric.

Award a mark when the student's response demonstrates the same underlying
knowledge or concept required by the rubric criterion, even if the student
uses different wording, synonyms, terminology, examples, or sentence
structure.

The student does not need to reproduce the specific wording or keywords
used in the rubric if the intended concept is clearly demonstrated.

Before withholding a mark because the wording differs from the rubric,
consider whether a reasonable human marker would recognise the response
as demonstrating the same required concept.

Do not award a mark when the response is only generally related to the
topic, mentions a relevant keyword without demonstrating the required
concept, or does not address what the criterion is testing.

3. DISTINGUISH EQUIVALENT ANSWERS FROM RELATED ANSWERS
An answer should receive the mark when a reasonable pharmacy educator
would recognise that the student has demonstrated the knowledge required
by the criterion.

However, being related to the topic is not sufficient.

Do not award the mark when the response:
- only mentions a related concept or keyword;
- gives a vague statement without demonstrating the required knowledge;
- does not address what the criterion is testing;
- contains incorrect or contradictory information; or
- requires an assumption that the student did not communicate.

4. VALID ALTERNATIVE ANSWERS
The rubric may provide examples rather than an exhaustive list of all
acceptable responses.

Accept an alternative answer when it is scientifically, clinically,
pharmacologically, or pharmaceutically valid AND clearly fulfils the
intended scoring criterion.

If the rubric explicitly states ""any other reasonable point"", accept
another reasonable point when it satisfies the same requirement.

Do not award a mark merely because an alternative answer is plausible or
generally relevant to the topic.

5. EVIDENCE-BASED GRADING
For every awarded criterion, identify the specific evidence from the
student's response that supports the mark.

Quote the student's response verbatim.

Use only information actually stated or clearly communicated by the
student. Do not infer knowledge that the student has not demonstrated.

6. PARTIAL CREDIT
Follow the marking structure in the rubric exactly.

Award partial or fractional marks when the rubric divides a criterion
into separately awarded components or explicitly allows partial credit.

Do not invent partial-credit rules that are not supported by the rubric.

7. NO DOUBLE COUNTING
Award each scoring point only once.

A student's statement may support multiple marks only when it clearly
satisfies separate scoring criteria in the rubric.

Do not award multiple marks for different wording of the same idea.

8. ACCURACY AND RELEVANCE
Award marks only for responses that are relevant to the question and
factually accurate.

If a response contains both correct and incorrect information, award
marks only for the scoring criteria that are correctly demonstrated.

9. HUMAN-MARKER PERSPECTIVE
Apply the rubric as a reasonable human pharmacy educator would.

Do not penalise a student simply because their answer differs in wording,
structure, terminology, or level of detail from the rubric.

Focus on whether the student has demonstrated the knowledge or reasoning
being assessed.

10. MAXIMUM SCORE
The total awarded score MUST NOT exceed {max_score}.

11. FINAL VERIFICATION
Before returning the final score, verify that:

- every awarded mark corresponds to a rubric criterion;
- the student's evidence demonstrates the criterion;
- valid paraphrases and equivalent terminology have been accepted;
- merely related or vague answers have not been awarded;
- valid alternative answers have been considered;
- incorrect or contradictory information has not been awarded;
- no scoring point has been counted twice;
- no unsupported assumptions have been made; and
- the total score is calculated correctly."
"""

def resolve_model(input_val: str, default_role="Model"):
    """Resolves short key (A, B, C) or raw OpenRouter string into a model info dict."""
    val = input_val.strip()
    key_upper = val.upper()
    if key_upper in PRESET_MODELS:
        return PRESET_MODELS[key_upper]
    
    clean_tag = re.sub(r'[^a-zA-Z0-9_-]', '_', val)
    return {
        "id": val,
        "name": val,
        "file_tag": clean_tag,
        "model_str": val,
        "cost_per_1k_in": 0.0002,
        "cost_per_1k_out": 0.0008
    }

# ---------------------------------------------------------
# DATASET LOADER: Q22 OPEN-ENDED ONLY (25 Samples)
# ---------------------------------------------------------
def get_q22_dataset(samples=25, seed=42):
    """Loads dataset and samples exclusively from Question 22 (Open-Ended)."""
    dataset_path = os.path.join(script_dir, "Dataset for prompt.xlsx")
    df_questions = pd.read_excel(dataset_path, sheet_name="Question & Answer Scheme")
    df_responses = pd.read_excel(dataset_path, sheet_name="Response")
    df_questions.columns = df_questions.columns.str.strip()
    df_responses.columns = df_responses.columns.str.strip()

    # Filter for Question 22
    q22_responses = df_responses[df_responses['question_no'].astype(str).str.strip().str.replace('Q', '') == "22"]
    sampled_responses = q22_responses.sample(n=min(samples, len(q22_responses)), random_state=seed)

    matched_q = df_questions[df_questions['question_no'].astype(str).str.strip().str.replace('Q', '') == "22"]
    if matched_q.empty:
        raise ValueError("Question 22 not found in 'Question & Answer Scheme' sheet of dataset.")

    q_info = matched_q.iloc[0]
    return q_info, sampled_responses

# ---------------------------------------------------------
# METRIC EVALUATION FUNCTIONS (Matching Experiment 2 Standard)
# ---------------------------------------------------------
def compute_metrics(df_clean, pred_col="grader_score", target_col="human_score"):
    """Computes ICC(A,1), MAE, Mean Error (Bias), Pearson r, Spearman rho, Exact Match %, and ±1 Mark %."""
    if len(df_clean) < 3:
        return {}
    n = len(df_clean)
    diffs = df_clean[pred_col] - df_clean[target_col]
    abs_err = diffs.abs()
    mae = abs_err.mean()
    mean_error = diffs.mean()
    exact_match = (abs_err < 1e-5).sum() / n * 100.0
    within_1 = (abs_err <= 1.0).sum() / n * 100.0
    
    try:
        pearson_r = df_clean[[pred_col, target_col]].corr().iloc[0, 1]
        if pd.isna(pearson_r): pearson_r = 0.0
    except Exception:
        pearson_r = 0.0

    try:
        spearman_rho = df_clean[[pred_col, target_col]].corr(method="spearman").iloc[0, 1]
        if pd.isna(spearman_rho): spearman_rho = 0.0
    except Exception:
        spearman_rho = 0.0

    try:
        icc_df = pd.concat([
            pd.DataFrame({'target': df_clean['response_id'], 'rater': 'Human', 'rating': df_clean[target_col]}),
            pd.DataFrame({'target': df_clean['response_id'], 'rater': 'AI', 'rating': df_clean[pred_col]})
        ], ignore_index=True)
        icc_res = pg.intraclass_corr(data=icc_df, targets='target', raters='rater', ratings='rating')
        icc_val = icc_res.set_index('Type').loc['ICC(A,1)', 'ICC']
        if pd.isna(icc_val): icc_val = 0.0
    except Exception:
        icc_val = 0.0

    return {
        "N": n,
        "ICC": round(float(icc_val), 3),
        "MAE": round(float(mae), 3),
        "Mean_Error": round(float(mean_error), 3),
        "Pearson_r": round(float(pearson_r), 3),
        "Spearman_rho": round(float(spearman_rho), 3),
        "Exact_Match_Pct": round(float(exact_match), 1),
        "Within_1_Mark_Pct": round(float(within_1), 1)
    }

def compute_quality_control_metrics(df_res):
    """Computes full Confusion Matrix for Error Detection: Recall, Precision, F1-Score, Leakage, and Automation Rate."""
    if df_res.empty:
        return {}

    total_n = len(df_res)
    actual_errors = df_res['actual_error_ge_1mark'].values
    flagged = (df_res['status'] == 'flagged').values
    
    tp = int(((flagged) & (actual_errors)).sum())
    fp = int(((flagged) & (~actual_errors)).sum())
    tn = int(((~flagged) & (~actual_errors)).sum())
    fn = int(((~flagged) & (actual_errors)).sum())

    total_actual_errors = tp + fn
    total_clean_grades = fp + tn

    flag_rate = (tp + fp) / total_n * 100.0 if total_n > 0 else 0.0
    automation_rate = 100.0 - flag_rate

    recall = (tp / total_actual_errors * 100.0) if total_actual_errors > 0 else 100.0
    precision = (tp / (tp + fp) * 100.0) if (tp + fp) > 0 else 0.0
    
    if (precision + recall) > 0:
        f1_score = (2.0 * precision * recall) / (precision + recall)
    else:
        f1_score = 0.0

    fn_leakage_rate = (fn / total_actual_errors * 100.0) if total_actual_errors > 0 else 0.0
    fp_overflag_rate = (fp / total_clean_grades * 100.0) if total_clean_grades > 0 else 0.0

    return {
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "Total_N": total_n,
        "Flag_Rate_Pct": round(flag_rate, 1),
        "Automation_Rate_Pct": round(automation_rate, 1),
        "Recall_Pct": round(recall, 1),
        "Precision_Pct": round(precision, 1),
        "F1_Score_Pct": round(f1_score, 1),
        "Leakage_FN_Pct": round(fn_leakage_rate, 1),
        "Overflag_FP_Pct": round(fp_overflag_rate, 1)
    }

# ---------------------------------------------------------
# AGENT 2: PRIMARY GRADER RUNNER (With Q22 Open-Ended Prompt)
# ---------------------------------------------------------
def grade_with_open_ended_agent(grader_model_info, question_no, question_text, rubric_text, max_score, student_answer):
    clean_ans = str(student_answer).strip() if pd.notna(student_answer) else ""
    if not clean_ans or clean_ans.lower() in ["-", "n/a", "none", "nan"]:
        return {
            "overall_score": 0.0,
            "confidence_score": 1.0,
            "status": "graded",
            "feedback": {"summary": "Blank submission.", "breakdown": [{"question_number": f"Q{question_no}", "score_awarded": 0.0, "max_score": float(max_score), "reasoning": "Blank response"}]},
            "highlights": []
        }, 0.0, 0, 0, 0.0, 0

    model_str = grader_model_info["model_str"]
    combined_guidelines = f"{rubric_text}\n\n{OPEN_ENDED_GRADING_RULES.format(max_score=max_score)}"
    structured_rubric = {
        "structured_rules": [
            {
                "question_number": f"Q{question_no}",
                "max_score": float(max_score),
                "grading_guidelines": combined_guidelines
            }
        ]
    }
    raw_rubric_json = [{"question_number": f"Q{question_no}", "max_score": float(max_score), "criterion": combined_guidelines}]

    start_time = time.time()
    res = call_primary_grading_agent(
        student_text=clean_ans,
        structured_rubric=structured_rubric,
        raw_rubric_json=raw_rubric_json,
        model_answer=rubric_text,
        rag_context="",
        total_max_score=float(max_score),
        model=model_str
    )
    latency_ms = round((time.time() - start_time) * 1000)

    if not res:
        return {
            "overall_score": 0.0,
            "confidence_score": 0.0,
            "status": "flagged",
            "feedback": {"summary": "Primary model call failed", "breakdown": []},
            "highlights": []
        }, 0.0, 0, 0, 0.0, latency_ms

    score = float(res.get("overall_score", 0.0))
    score = max(0.0, min(float(max_score), score))

    usage = res.get("_usage", {})
    actual_in_tok = usage.get("prompt_tokens", int((len(clean_ans) + len(rubric_text) + 800) / 4))
    actual_out_tok = usage.get("completion_tokens", int(len(json.dumps(res)) / 4))
    cost = (actual_in_tok / 1000.0 * grader_model_info.get("cost_per_1k_in", 0.0002)) + (actual_out_tok / 1000.0 * grader_model_info.get("cost_per_1k_out", 0.0008))

    return res, score, actual_in_tok, actual_out_tok, cost, latency_ms

# ---------------------------------------------------------
# AGENT 3: AUDITOR VERIFICATION RUNNER
# ---------------------------------------------------------
def audit_with_backend_agent(auditor_model_info, question_no, rubric_text, max_score, student_answer, primary_eval):
    clean_ans = str(student_answer).strip() if pd.notna(student_answer) else ""
    if not clean_ans or clean_ans.lower() in ["-", "n/a", "none", "nan"]:
        return primary_eval.get("overall_score", 0.0), True, [], "", [], 0, 0, 0.0, 0

    model_str = auditor_model_info["model_str"]
    raw_rubric_json = [{"question_number": f"Q{question_no}", "max_score": float(max_score), "criterion": rubric_text}]

    start_time = time.time()
    auditor_res = call_auditor_verification_agent(
        student_text=clean_ans,
        rubric_json=raw_rubric_json,
        primary_eval=primary_eval,
        model=model_str
    )
    latency_ms = round((time.time() - start_time) * 1000)

    if not auditor_res:
        return float(primary_eval.get("overall_score", 0.0)), True, [], "Audit call failed", [], 0, 0, 0.0, latency_ms

    audit_passed = bool(auditor_res.get("audit_passed", True))
    auditor_score = float(auditor_res.get("auditor_score", primary_eval.get("overall_score", 0.0)))
    auditor_score = max(0.0, min(float(max_score), auditor_score))
    conflicting_qs = auditor_res.get("conflicting_questions", [])
    discrepancy_note = auditor_res.get("reconciliation_reason", auditor_res.get("discrepancy_note", ""))

    auditor_breakdown = auditor_res.get("auditor_breakdown", [])
    if not isinstance(auditor_breakdown, list):
        auditor_breakdown = []

    usage = auditor_res.get("_usage", {})
    actual_in_tok = usage.get("prompt_tokens", int((len(clean_ans) + len(rubric_text) + 600) / 4))
    actual_out_tok = usage.get("completion_tokens", int(len(json.dumps(auditor_res)) / 4))
    cost = (actual_in_tok / 1000.0 * auditor_model_info.get("cost_per_1k_in", 0.0002)) + (actual_out_tok / 1000.0 * auditor_model_info.get("cost_per_1k_out", 0.0008))

    return auditor_score, audit_passed, conflicting_qs, discrepancy_note, auditor_breakdown, actual_in_tok, actual_out_tok, cost, latency_ms

# ---------------------------------------------------------
# SAVE MULTI-TAB EXCEL WORKBOOK (Q22 Multi-Agent)
# ---------------------------------------------------------
def save_open_ended_audit_excel(df_res, pair_title, arch_type, excel_file):
    if df_res.empty: return

    tot_time_s = round(df_res['total_latency_ms'].sum() / 1000.0, 1)
    duration_str = f"{int(tot_time_s // 60)}m {int(tot_time_s % 60)}s"
    n_res = len(df_res)
    tot_cost = round(df_res['total_cost_usd'].sum(), 6)
    cost_100q = round(tot_cost * (100.0 / n_res), 4) if n_res > 0 else tot_cost

    try:
        with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
            # 1. Summary Metrics Sheet with EXACT requested columns
            q_all_metrics = compute_metrics(df_res, pred_col="grader_score")
            q_unflagged = df_res[df_res['status'] == 'graded']
            q_unflagged_metrics = compute_metrics(q_unflagged, pred_col="grader_score") if len(q_unflagged) >= 3 else {}
            qc = compute_quality_control_metrics(df_res)
            
            summary_rows = [{
                "Grader ICC": q_all_metrics.get("ICC", 0.0),
                "Grader MAE": q_all_metrics.get("MAE", 0.0),
                "Auto-Approved ICC": unflagged_metrics.get("ICC", q_all_metrics.get("ICC", 0.0)),
                "Auto-Approved MAE": unflagged_metrics.get("MAE", q_all_metrics.get("MAE", 0.0)),
                "Automation Rate (%)": f"{qc.get('Automation_Rate_Pct', 0.0)}%",
                "Flag Rate (%)": f"{qc.get('Flag_Rate_Pct', 0.0)}%",
                "Flagging Recall (%)": f"{qc.get('Recall_Pct', 0.0)}%",
                "Flagging Precision (%)": f"{qc.get('Precision_Pct', 0.0)}%",
                "Flagging F1-Score (%)": f"{qc.get('F1_Score_Pct', 0.0)}%",
                "Leakage (FN Rate) (%)": f"{qc.get('Leakage_FN_Pct', 0.0)}%",
                "Over-flag (FP Rate) (%)": f"{qc.get('Overflag_FP_Pct', 0.0)}%",
                "Avg Latency (s)": round(df_res['total_latency_ms'].mean() / 1000.0, 2),
                "Total Run Time": duration_str,
                "Total Cost (100 Qs)": f"${cost_100q:.4f}"
            }]

            df_sum = pd.DataFrame(summary_rows)
            df_sum.to_excel(writer, sheet_name="Audit_Summary", index=False)

            # Also save Summary Metrics to CSV directly
            summary_csv_file = excel_file.replace(".xlsx", "_summary.csv")
            df_sum.to_csv(summary_csv_file, index=False)

            # Update Master Comparison CSV
            master_csv = os.path.join(script_dir, "results_open_ended_audit_master_summary.csv")
            try:
                if os.path.exists(master_csv) and os.path.getsize(master_csv) > 0:
                    prev_master = pd.read_csv(master_csv)
                    # Filter out old entry for this pair if exists
                    if "Model Setup" in prev_master.columns:
                        prev_master = prev_master[prev_master["Model Setup"] != pair_title]
                    master_row = df_sum.copy()
                    master_row.insert(0, "Model Setup", pair_title)
                    master_df = pd.concat([prev_master, master_row], ignore_index=True)
                else:
                    master_df = df_sum.copy()
                    master_df.insert(0, "Model Setup", pair_title)
                master_df.to_csv(master_csv, index=False)
            except Exception as e:
                pass

            # 2. Detailed Q22 Sheet
            q_cols = [
                "response_id", "question_no", "human_score", "grader_score", "auditor_score",
                "score_discrepancy", "audit_passed", "status", "confidence_score", "flag_reasons",
                "actual_error_ge_1mark", "grader_absolute_error", "grader_latency_ms", "auditor_latency_ms",
                "total_cost_usd", "audit_note", "student_answer", "grader_reasoning"
            ]
            available_cols = [c for c in q_cols if c in df_res.columns]
            df_res[available_cols].to_excel(writer, sheet_name="Q22_Audit", index=False)

            # 3. Flagged Review Queue (Submissions sent to lecturer)
            flagged_df = df_res[df_res['status'] == 'flagged'].copy()
            if not flagged_df.empty:
                f_cols = ["response_id", "question_no", "human_score", "grader_score", "auditor_score", "score_discrepancy", "flag_reasons", "audit_note", "student_answer"]
                available_f_cols = [c for c in f_cols if c in flagged_df.columns]
                flagged_df[available_f_cols].to_excel(writer, sheet_name="Flagged_For_Lecturer", index=False)

        print(f"\n📊 Multi-Agent Excel report saved to: {excel_file}")
        print(f"📄 Summary Metrics CSV saved to: {summary_csv_file}")
        print(f"📁 Detailed Responses CSV saved to: {excel_file.replace('.xlsx', '.csv')}")
    except Exception as e:
        print(f"  ⚠️ Warning saving files: {e}")

# ---------------------------------------------------------
# RUN MULTI-AGENT EXPERIMENT ON Q22
# ---------------------------------------------------------
def run_q22_multi_agent_experiment(grader_model_info, auditor_model_info, samples=25, seed=42, fresh=False):
    grader_name = grader_model_info["name"]
    auditor_name = auditor_model_info["name"]
    pair_tag = f"{grader_model_info['file_tag']}_to_{auditor_model_info['file_tag']}"
    pair_title = f"{grader_name} (Grader w/ Q22 Prompt) ➔ {auditor_name} (Auditor)"
    is_self_audit = (grader_model_info["model_str"] == auditor_model_info["model_str"])
    arch_type = "Self-Audit" if is_self_audit else "Heterogeneous Multi-Agent"

    print("\n" + "="*85)
    print(f"🚀 RUNNING MULTI-AGENT OPEN-ENDED (Q22): {pair_title}")
    print(f"   Architecture: {arch_type} | Samples: {samples} | Seed: {seed}")
    print("="*85)

    q_info, df_sample = get_q22_dataset(samples=samples, seed=seed)
    question_text = q_info['question']
    rubric_text = q_info['answer']
    max_score = float(q_info['max_mark'])

    csv_file = os.path.join(script_dir, f"results_open_ended_audit_{pair_tag}_Q22.csv")
    excel_file = os.path.join(script_dir, f"results_open_ended_audit_{pair_tag}_Q22.xlsx")

    results = []
    completed_ids = set()

    if fresh and os.path.exists(csv_file):
        os.remove(csv_file)
        print(f"🧹 Fresh run requested: Cleared previous checkpoint for {pair_title}.")

    # Load checkpoint if exists
    if not fresh and os.path.exists(csv_file) and os.path.getsize(csv_file) > 0:
        try:
            prev_df = pd.read_csv(csv_file)
            results = prev_df.to_dict('records')
            completed_ids = set(str(r['response_id']) for r in results)
            print(f"🔄 Checkpoint: Loaded {len(completed_ids)} already evaluated responses.")
        except Exception:
            pass

    for idx, row in df_sample.iterrows():
        resp_id = str(row['ID Number'])
        if resp_id in completed_ids:
            continue

        human_score = float(row['grade'])
        ans_text = row['Response']

        print(f"  [{len(results)+1}/{samples}] Q22 | Student {resp_id} | Grader: {grader_name} ➔ Auditor: {auditor_name}...")

        # Step 1: Execute Primary Grader using Q22 Open-Ended Prompt
        primary_eval, grader_score, g_in_tok, g_out_tok, g_cost, g_lat = grade_with_open_ended_agent(
            grader_model_info=grader_model_info,
            question_no="22",
            question_text=question_text,
            rubric_text=rubric_text,
            max_score=max_score,
            student_answer=ans_text
        )

        # Step 2: Execute Auditor Agent
        auditor_score, audit_passed, conflict_qs, audit_note, a_breakdown, a_in_tok, a_out_tok, a_cost, a_lat = audit_with_backend_agent(
            auditor_model_info=auditor_model_info,
            question_no="22",
            rubric_text=rubric_text,
            max_score=max_score,
            student_answer=ans_text,
            primary_eval=primary_eval
        )

        score_discrepancy = round(abs(grader_score - auditor_score), 2)
        max_denom = max_score if max_score > 0 else 6.0
        agreement_ratio = max(0.0, 1.0 - (score_discrepancy / max_denom))

        # Step 3: Attach Audit Result & Run Confidence Engine
        primary_eval["multi_agent_audit"] = {
            "auditor_passed": audit_passed,
            "auditor_score": auditor_score,
            "auditor_breakdown": a_breakdown,
            "score_discrepancy": score_discrepancy,
            "agreement_ratio": round(agreement_ratio, 2),
            "conflicting_questions": conflict_qs,
            "audit_note": audit_note,
            "model_used": auditor_model_info["model_str"]
        }

        conf_result = evaluate_confidence_and_status(primary_eval, str(ans_text), max_score)
        confidence_score = conf_result["confidence_score"]
        status = conf_result["status"]  # "graded" or "flagged"
        flag_reasons = "; ".join(conf_result.get("flag_reasons", []))

        # Ground truth error definition: Was there an actual human-AI error (>= 1.0 mark)?
        actual_error = abs(grader_score - human_score) >= 1.0
        grader_reasoning = primary_eval.get("reasoning", "")
        if not grader_reasoning and isinstance(primary_eval.get("feedback"), dict):
            grader_reasoning = primary_eval["feedback"].get("summary", "")

        rec = {
            "response_id": resp_id,
            "question_no": "Q22",
            "human_score": human_score,
            "max_score": max_score,
            "grader_score": grader_score,
            "auditor_score": auditor_score,
            "score_discrepancy": score_discrepancy,
            "audit_passed": audit_passed,
            "confidence_score": confidence_score,
            "status": status,
            "flag_reasons": flag_reasons,
            "actual_error_ge_1mark": actual_error,
            "grader_absolute_error": round(abs(grader_score - human_score), 2),
            "grader_latency_ms": g_lat,
            "auditor_latency_ms": a_lat,
            "total_latency_ms": g_lat + a_lat,
            "grader_cost_usd": round(g_cost, 6),
            "auditor_cost_usd": round(a_cost, 6),
            "total_cost_usd": round(g_cost + a_cost, 6),
            "audit_note": audit_note,
            "grader_reasoning": grader_reasoning,
            "student_answer": ans_text
        }
        results.append(rec)

        # Auto-save after each response (fail-safe checkpoint)
        pd.DataFrame(results).to_csv(csv_file, index=False)

    df_res = pd.DataFrame(results)
    save_open_ended_audit_excel(df_res, pair_title, arch_type, excel_file)
    return df_res

# ---------------------------------------------------------
# CLI & MAIN ENTRYPOINT
# ---------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="AutoGrade+ Multi-Agent Benchmark for Open-Ended Question 22")
    parser.add_argument("--grader", "-g", "--model", "-m", type=str, default=None, help="Grader Model: A (Gemini 3.1 Flash Lite), B (Nemotron 120B), C (Claude Sonnet), or custom string")
    parser.add_argument("--auditor", "-a", type=str, default=None, help="Auditor Model: A, B, C, or custom string")
    parser.add_argument("--samples", "-n", type=int, default=25, help="Number of Q22 responses to evaluate (default: 25)")
    parser.add_argument("--seed", type=int, default=42, help="Random sampling seed (default: 42)")
    parser.add_argument("--fresh", action="store_true", help="Force a fresh run clearing previous checkpoint")
    args = parser.parse_args()

    grader_arg = args.grader
    auditor_arg = args.auditor
    is_fresh = args.fresh

    # Interactive prompt if models not passed
    if not grader_arg or not auditor_arg:
        if sys.stdin.isatty():
            print("="*65)
            print("🤖 MULTI-AGENT OPEN-ENDED (Q22) BENCHMARK SELECTION")
            print("="*65)
            print("Available Preset Models:")
            print("  [A / 1] Gemini 3.1 Flash Lite (Fast, High-Throughput)")
            print("  [B / 2] Nemotron 3 Super 120B (High Reasoning, Accurate)")
            print("  [C / 3] Claude 4.6 Sonnet (Deep Evaluation)")
            print("="*65)
            try:
                if not grader_arg:
                    g_in = input("Select GRADER model (A/B/C) [Default: B (Nemotron)]: ").strip().upper()
                    grader_arg = {"1": "A", "2": "B", "3": "C"}.get(g_in, g_in or "B")
                if not auditor_arg:
                    a_in = input("Select AUDITOR model (A/B/C) [Default: A (Gemini)]: ").strip().upper()
                    auditor_arg = {"1": "A", "2": "B", "3": "C"}.get(a_in, a_in or "A")

                fresh_in = input("Force fresh rerun (clear previous checkpoint)? (y/N) [Default: N]: ").strip().lower()
                if fresh_in in ["y", "yes"]:
                    is_fresh = True
            except (KeyboardInterrupt, EOFError):
                print("\nOperation cancelled.")
                sys.exit(0)
        else:
            grader_arg = grader_arg or "B"
            auditor_arg = auditor_arg or "A"

    grader_info = resolve_model(grader_arg, default_role="Grader")
    auditor_info = resolve_model(auditor_arg, default_role="Auditor")

    df_res = run_q22_multi_agent_experiment(
        grader_model_info=grader_info,
        auditor_model_info=auditor_info,
        samples=args.samples,
        seed=args.seed,
        fresh=is_fresh
    )

    # Print summary metrics to terminal
    g_metrics = compute_metrics(df_res, pred_col="grader_score")
    a_metrics = compute_metrics(df_res, pred_col="auditor_score")
    qc = compute_quality_control_metrics(df_res)
    unflagged = df_res[df_res['status'] == 'graded']
    unflagged_metrics = compute_metrics(unflagged, pred_col="grader_score") if len(unflagged) >= 3 else {}
    tot_time_s = round(df_res['total_latency_ms'].sum() / 1000.0, 1)
    duration_str = f"{int(tot_time_s // 60)}m {int(tot_time_s % 60)}s"
    n_res = len(df_res)
    tot_cost = round(df_res['total_cost_usd'].sum(), 6)
    cost_100q = round(tot_cost * (100.0 / n_res), 4) if n_res > 0 else tot_cost

    output_row = {
        "Grader ICC": f"{g_metrics.get('ICC', 0.0):.3f}",
        "Grader MAE": f"{g_metrics.get('MAE', 0.0):.3f}",
        "Auto-Approved ICC": f"{unflagged_metrics.get('ICC', g_metrics.get('ICC', 0.0)):.3f}",
        "Auto-Approved MAE": f"{unflagged_metrics.get('MAE', g_metrics.get('MAE', 0.0)):.3f}",
        "Automation Rate (%)": f"{qc.get('Automation_Rate_Pct', 0.0)}%",
        "Flag Rate (%)": f"{qc.get('Flag_Rate_Pct', 0.0)}%",
        "Flagging Recall (%)": f"{qc.get('Recall_Pct', 0.0)}%",
        "Flagging Precision (%)": f"{qc.get('Precision_Pct', 0.0)}%",
        "Flagging F1-Score (%)": f"{qc.get('F1_Score_Pct', 0.0)}%",
        "Leakage (FN Rate) (%)": f"{qc.get('Leakage_FN_Pct', 0.0)}%",
        "Over-flag (FP Rate) (%)": f"{qc.get('Overflag_FP_Pct', 0.0)}%",
        "Avg Latency (s)": f"{round(df_res['total_latency_ms'].mean() / 1000.0, 2):.2f}",
        "Total Run Time": duration_str,
        "Total Cost (100 Qs)": f"${cost_100q:.4f}"
    }

    df_out = pd.DataFrame([output_row])

    print("\n" + "="*120)
    print("🏆 EXPERIMENT 2 BENCHMARK OUTPUT (Q22 OPEN-ENDED)")
    print("="*120)
    print(f"Setup: {grader_info['name']} (Grader) ➔ {auditor_info['name']} (Auditor)")
    print(f"Sample Size: N = {len(df_res)} | Max Mark = 6.0")
    print("-" * 120)
    print(df_out.to_string(index=False))
    print("-" * 120)
    print("📋 TAB-SEPARATED ROW (Direct copy-paste into Excel / Google Sheets):")
    print("\t".join(output_row.keys()))
    print("\t".join(output_row.values()))
    print("="*120 + "\n")

if __name__ == "__main__":
    main()
