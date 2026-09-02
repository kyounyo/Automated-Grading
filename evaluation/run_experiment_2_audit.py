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
    },
    "D": {
        "id": "D",
        "name": "Gemini 3.5 Flash Lite",
        "file_tag": "Gemini_3.5_Flash_Lite",
        "model_str": os.getenv("MODEL_D_STR", "google/gemini-3.5-flash-lite"),
        "cost_per_1k_in": 0.0001,
        "cost_per_1k_out": 0.0004
    }
}

def resolve_model(input_val: str, default_role="Model"):
    """Resolves short key (A, B, C) or raw OpenRouter string into a model info dict."""
    val = input_val.strip()
    key_upper = val.upper()
    if key_upper in PRESET_MODELS:
        return PRESET_MODELS[key_upper]
    
    # Custom model string
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
# SAMPLING & DATASET LOADER (Stratified 25 x 4 = 100 Responses)
# ---------------------------------------------------------
def get_stratified_dataset(samples_per_question=10, seed=40):
    """Loads dataset and creates reproducible 100-sample slice (25 per question)."""
    dataset_path = os.path.join(script_dir, "Dataset for prompt.xlsx")
    df_questions = pd.read_excel(dataset_path, sheet_name="Question & Answer Scheme")
    df_responses = pd.read_excel(dataset_path, sheet_name="Response")
    df_questions.columns = df_questions.columns.str.strip()
    df_responses.columns = df_responses.columns.str.strip()

    sampled_dfs = []
    for q_no in [6, 8, 9, 22]:
        q_subset = df_responses[df_responses['question_no'].astype(str).str.strip().str.replace('Q', '') == str(q_no)]
        sampled = q_subset.sample(n=min(samples_per_question, len(q_subset)), random_state=seed)
        sampled_dfs.append(sampled)

    df_sampled = pd.concat(sampled_dfs, ignore_index=True)
    return df_questions, df_sampled

# ---------------------------------------------------------
# STATISTICAL METRICS & F1-SCORE CALCULATOR
# ---------------------------------------------------------
def compute_metrics(df_results, pred_col="grader_score", target_col="human_score"):
    """Computes ICC(A,1), MAE, Normalized MAE (%), Mean Error (Bias), Pearson, Spearman, Exact Match %, and ±1 Mark %."""
    df_clean = df_results.dropna(subset=[pred_col, target_col]).copy()
    if len(df_clean) < 3:
        return {}

    n = len(df_clean)
    diffs = df_clean[pred_col] - df_clean[target_col]
    abs_errors = diffs.abs()
    mae = abs_errors.mean()
    mean_error = diffs.mean()

    # Scale-normalized MAE (%) if max_score is available
    if 'max_score' in df_clean and (df_clean['max_score'] > 0).all():
        norm_mae_pct = (abs_errors / df_clean['max_score'] * 100.0).mean()
    else:
        norm_mae_pct = (abs_errors / 10.0 * 100.0).mean()

    exact_match_pct = (abs_errors < 1e-5).sum() / n * 100.0
    within_1_mark_pct = (abs_errors <= 1.0).sum() / n * 100.0

    try:
        pearson_r = df_clean[[pred_col, target_col]].corr().iloc[0, 1]
    except Exception as e:
        print(f"  ⚠️ Warning calculating Pearson r: {e}")
        pearson_r = float("nan")
        
    try:
        spearman_rho = df_clean[[pred_col, target_col]].corr(method="spearman").iloc[0, 1]
    except Exception as e:
        print(f"  ⚠️ Warning calculating Spearman rho: {e}")
        spearman_rho = float("nan")

    # Construct unique composite target identifier (e.g. Q6_31109578) to avoid collision across questions
    q_col = df_clean['question_no'].astype(str) if 'question_no' in df_clean else "Q"
    df_clean['composite_target_id'] = q_col + "_" + df_clean['response_id'].astype(str)

    try:
        icc_df_format = pd.concat([
            pd.DataFrame({'target': df_clean['composite_target_id'], 'rater': 'Human', 'rating': df_clean[target_col]}),
            pd.DataFrame({'target': df_clean['composite_target_id'], 'rater': 'AI', 'rating': df_clean[pred_col]})
        ], ignore_index=True)
        icc = pg.intraclass_corr(data=icc_df_format, targets='target', raters='rater', ratings='rating')
        icc_val = icc.set_index('Type').loc['ICC(A,1)', 'ICC']
    except Exception as e:
        print(f"  ⚠️ Warning calculating ICC(A,1): {e}")
        icc_val = float("nan")

    return {
        "N": n,
        "ICC": round(icc_val, 3),
        "MAE": round(mae, 3),
        "Normalized_MAE_Pct": round(norm_mae_pct, 1),
        "Mean_Error": round(mean_error, 3),
        "Pearson_r": round(pearson_r, 3),
        "Spearman_rho": round(spearman_rho, 3),
        "Exact_Match_Pct": round(exact_match_pct, 1),
        "Within_1_Mark_Pct": round(within_1_mark_pct, 1)
    }

def compute_quality_control_metrics(df_res):
    """Computes full Confusion Matrix for Error Detection: Recall, Precision, F1-Score, Leakage, and Automation Rate."""
    if df_res.empty:
        return {}

    total_n = len(df_res)
    # Ground Truth Error: |Grader - Human| > 1.0 mark (discrepancy exceeding acceptable +/-1 mark tolerance)
    if 'actual_error_gt_1mark' in df_res:
        actual_errors = df_res['actual_error_gt_1mark'].values
    elif 'grader_absolute_error' in df_res:
        actual_errors = (df_res['grader_absolute_error'] > 1.0 + 1e-5).values
    elif 'grader_score' in df_res and 'human_score' in df_res:
        actual_errors = (abs(df_res['grader_score'] - df_res['human_score']) > 1.0 + 1e-5).values
    else:
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

    recall = (tp / total_actual_errors * 100.0) if total_actual_errors > 0 else float("nan")
    precision = (tp / (tp + fp) * 100.0) if (tp + fp) > 0 else float("nan")
    
    # Flagging F1-Score
    if not (pd.isna(precision) or pd.isna(recall)) and (precision + recall) > 0:
        f1_score = (2.0 * precision * recall) / (precision + recall)
    else:
        f1_score = float("nan")

    fn_leakage_rate = (fn / total_actual_errors * 100.0) if total_actual_errors > 0 else float("nan")
    fp_overflag_rate = (fp / total_clean_grades * 100.0) if total_clean_grades > 0 else float("nan")

    return {
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "Total_N": total_n,
        "Flag_Rate_Pct": round(flag_rate, 1),
        "Automation_Rate_Pct": round(automation_rate, 1),
        "Recall_Pct": round(recall, 1) if not pd.isna(recall) else "N/A",
        "Precision_Pct": round(precision, 1) if not pd.isna(precision) else "N/A",
        "F1_Score_Pct": round(f1_score, 1) if not pd.isna(f1_score) else "N/A",
        "Leakage_FN_Pct": round(fn_leakage_rate, 1) if not pd.isna(fn_leakage_rate) else "N/A",
        "Overflag_FP_Pct": round(fp_overflag_rate, 1) if not pd.isna(fp_overflag_rate) else "N/A"
    }

# ---------------------------------------------------------
# AGENT 2: PRIMARY GRADER RUNNER
# ---------------------------------------------------------
def grade_with_backend_agent(grader_model_info, question_no, question_text, rubric_text, max_score, student_answer):
    clean_ans = str(student_answer).strip() if pd.notna(student_answer) else ""
    if not clean_ans or clean_ans.lower() in ["-", "n/a", "none", "nan"]:
        blank_eval = {
            "overall_score": 0.0,
            "confidence_score": 1.0,
            "status": "graded",
            "reasoning": "Blank answer provided. 0 marks awarded.",
            "feedback": {"summary": "No response provided.", "breakdown": []},
            "highlights": []
        }
        return blank_eval, 0.0, 0, 0, 0.0, 0

    model_str = grader_model_info["model_str"]

    structured_rubric = {
        "structured_rules": [
            {
                "question_number": f"Q{question_no}",
                "max_score": float(max_score),
                "grading_guidelines": rubric_text
            }
        ]
    }
    raw_rubric_json = [{"question_number": f"Q{question_no}", "max_score": float(max_score), "criterion": rubric_text}]

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
        return {"overall_score": 0.0, "reasoning": "Model call failed."}, 0.0, 0, 0, 0.0, latency_ms

    score = float(res.get("overall_score", 0.0))
    score = max(0.0, min(float(max_score), score))
    
    usage = res.get("_usage", {})
    actual_in_tok = usage.get("prompt_tokens", int((len(clean_ans) + len(rubric_text) + len(question_text) + 600) / 4))
    actual_out_tok = usage.get("completion_tokens", int(len(json.dumps(res)) / 4))
    cost = (actual_in_tok / 1000.0 * grader_model_info.get("cost_per_1k_in", 0.0002)) + (actual_out_tok / 1000.0 * grader_model_info.get("cost_per_1k_out", 0.0008))

    return res, score, actual_in_tok, actual_out_tok, cost, latency_ms

# ---------------------------------------------------------
# AGENT 3: AUDITOR VERIFICATION RUNNER
# ---------------------------------------------------------
# AGENT 3: AUDITOR VERIFICATION & RECONCILIATION RUNNER
# ---------------------------------------------------------
def audit_with_backend_agent(auditor_model_info, question_no, rubric_text, max_score, student_answer, primary_eval):
    clean_ans = str(student_answer).strip() if pd.notna(student_answer) else ""
    if not clean_ans or clean_ans.lower() in ["-", "n/a", "none", "nan"]:
        return primary_eval.get("overall_score", 0.0), primary_eval.get("overall_score", 0.0), True, "AGREEMENT", "NONE", [], "Blank submission", [], 0, 0, 0.0, 0

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
        p_sc = float(primary_eval.get("overall_score", 0.0))
        return p_sc, p_sc, True, "FALLBACK_GRADER", "NONE", [], "Audit call failed", [], 0, 0, 0.0, latency_ms

    audit_passed = bool(auditor_res.get("audit_passed", True))
    auditor_score = float(auditor_res.get("auditor_score", primary_eval.get("overall_score", 0.0)))
    auditor_score = max(0.0, min(float(max_score), auditor_score))
    
    reconciled_score = float(auditor_res.get("reconciled_score", auditor_score))
    reconciled_score = max(0.0, min(float(max_score), reconciled_score))
    
    recommendation = auditor_res.get("recommendation", "ADOPT_AUDITOR")
    severity = auditor_res.get("disagreement_severity", "MINOR")
    conflicting_qs = auditor_res.get("conflicting_questions", [])
    reconciliation_reason = auditor_res.get("reconciliation_reason", auditor_res.get("discrepancy_note", ""))

    auditor_breakdown = auditor_res.get("auditor_breakdown", [])
    if not isinstance(auditor_breakdown, list):
        auditor_breakdown = []

    usage = auditor_res.get("_usage", {})
    actual_in_tok = usage.get("prompt_tokens", int((len(clean_ans) + len(rubric_text) + 600) / 4))
    actual_out_tok = usage.get("completion_tokens", int(len(json.dumps(auditor_res)) / 4))
    cost = (actual_in_tok / 1000.0 * auditor_model_info.get("cost_per_1k_in", 0.0002)) + (actual_out_tok / 1000.0 * auditor_model_info.get("cost_per_1k_out", 0.0008))
    return auditor_score, reconciled_score, audit_passed, recommendation, severity, conflicting_qs, reconciliation_reason, auditor_breakdown, actual_in_tok, actual_out_tok, cost, latency_ms

# ---------------------------------------------------------
# RUN CUSTOM GRADER + AUDITOR PAIR ACROSS RESPONSES
# ---------------------------------------------------------
def run_manual_audit_experiment(grader_model_info, auditor_model_info, df_questions, df_sample, fresh=False):
    grader_name = grader_model_info["name"]
    auditor_name = auditor_model_info["name"]
    pair_tag = f"{grader_model_info['file_tag']}_to_{auditor_model_info['file_tag']}"
    pair_title = f"{grader_name} (Grader) ➔ {auditor_name} (Auditor)"
    arch_type = "Self-Audit" if (grader_model_info["model_str"] == auditor_model_info["model_str"]) else "Heterogeneous"

    print("\n" + "="*85)
    print(f"🚀 RUNNING EXPERIMENT 2: {pair_title}")
    print(f"   Architecture: {arch_type}")
    print(f"   Total Sample Size: {len(df_sample)} Responses")
    print("="*85)
    
    csv_file = os.path.join(script_dir, f"results_exp2_{pair_tag}.csv")
    excel_file = os.path.join(script_dir, f"results_exp2_{pair_tag}.xlsx")
    
    results = []
    completed_keys = set()
    
    if fresh and os.path.exists(csv_file):
        try:
            os.remove(csv_file)
            print(f"🧹 Fresh run: Cleared previous checkpoint file {csv_file}")
        except Exception:
            pass

    if not fresh and os.path.exists(csv_file) and os.path.getsize(csv_file) > 0:
        try:
            prev_df = pd.read_csv(csv_file)
            results = prev_df.to_dict('records')
            for r in results:
                q_clean = str(r['question_no']).strip().replace('Q', '')
                completed_keys.add(f"{r['response_id']}_{q_clean}")
            print(f"🔄 Checkpoint: Loaded {len(completed_keys)} already audited responses for {pair_tag}.")
        except Exception:
            pass

    total_target = len(df_sample)
    for idx, row in df_sample.iterrows():
        resp_id = str(row['ID Number'])
        q_no = str(row['question_no']).strip().replace('Q', '')
        human_score = float(row['grade'])
        ans_text = row['Response']

        item_key = f"{resp_id}_{q_no}"
        if item_key in completed_keys:
            continue

        matched_q = df_questions[df_questions['question_no'].astype(str).str.strip().str.replace('Q', '') == q_no]
        if matched_q.empty: continue
        
        q_row = matched_q.iloc[0]
        question_text = q_row['question']
        rubric = q_row['answer']
        max_score = float(q_row['max_mark'])

        print(f"  [{len(results)+1}/{total_target}] Q{q_no} | Student {resp_id} | Grader: {grader_name} ➔ Auditor: {auditor_name}...")
        
        # Step 1: Execute Primary Grader
        primary_eval, grader_score, g_in_tok, g_out_tok, g_cost, g_lat = grade_with_backend_agent(
            grader_model_info=grader_model_info,
            question_no=q_no,
            question_text=question_text,
            rubric_text=rubric,
            max_score=max_score,
            student_answer=ans_text
        )

        # Step 2: Execute Auditor Agent (Verification & Reconciliation)
        auditor_score, a_reconciled_score, audit_passed, recommendation, severity, conflict_qs, reconciliation_reason, a_breakdown, a_in_tok, a_out_tok, a_cost, a_lat = audit_with_backend_agent(
            auditor_model_info=auditor_model_info,
            question_no=q_no,
            rubric_text=rubric,
            max_score=max_score,
            student_answer=ans_text,
            primary_eval=primary_eval
        )

        score_discrepancy = round(abs(grader_score - auditor_score), 2)
        max_denom = max_score if max_score > 0 else 10.0
        agreement_ratio = max(0.0, 1.0 - (score_discrepancy / max_denom))
        
        # Step 3: Attach Audit Result & Run Confidence Engine
        primary_eval["multi_agent_audit"] = {
            "auditor_passed": audit_passed,
            "auditor_score": auditor_score,
            "reconciled_score": a_reconciled_score,
            "recommendation": recommendation,
            "disagreement_severity": severity,
            "auditor_breakdown": a_breakdown,
            "score_discrepancy": score_discrepancy,
            "agreement_ratio": round(agreement_ratio, 2),
            "conflicting_questions": conflict_qs,
            "audit_note": reconciliation_reason,
            "reconciliation_reason": reconciliation_reason,
            "model_used": auditor_model_info["model_str"]
        }
        
        conf_result = evaluate_confidence_and_status(primary_eval, str(ans_text), max_score)
        confidence_score = conf_result["confidence_score"]
        status = conf_result["status"]  # "graded" or "flagged"
        flag_reasons = "; ".join(conf_result.get("flag_reasons", []))

        # Stage 3 — Reconciliation Decision:
        # If Grader == Auditor: Reconciled = Grader (Exact Agreement)
        # If Grader != Auditor: Reconciled = Auditor-resolved score (Reconciliation)
        if grader_score == auditor_score:
            final_reconciled_score = grader_score
            reconciliation_action = "EXACT_AGREEMENT"
        else:
            final_reconciled_score = a_reconciled_score
            reconciliation_action = recommendation

        # Ground truth error definition: Was there an actual human-AI error (> 1.0 mark)?
        actual_error = abs(grader_score - human_score) > 1.0 + 1e-5

        rec = {
            "response_id": resp_id,
            "question_no": f"Q{q_no}",
            "human_score": human_score,
            "max_score": max_score,
            "grader_score": grader_score,
            "auditor_score": auditor_score,
            "reconciled_score": final_reconciled_score,
            "reconciliation_action": reconciliation_action,
            "disagreement_pts": score_discrepancy,
            "disagreement_severity": severity,
            "reconciliation_reason": reconciliation_reason,
            "audit_passed": audit_passed,
            "confidence_score": confidence_score,
            "status": status,
            "flag_reasons": flag_reasons,
            "actual_error_gt_1mark": actual_error,
            "actual_error_ge_1mark": abs(grader_score - human_score) >= 1.0,
            "grader_absolute_error": round(abs(grader_score - human_score), 2),
            "auditor_absolute_error": round(abs(auditor_score - human_score), 2),
            "reconciled_absolute_error": round(abs(final_reconciled_score - human_score), 2),
            "grader_latency_ms": g_lat,
            "auditor_latency_ms": a_lat,
            "total_latency_ms": g_lat + a_lat,
            "total_cost_usd": round(g_cost + a_cost, 6),
            "student_answer": str(ans_text),
            "grader_reasoning": str(primary_eval.get("reasoning", ""))
        }
        results.append(rec)
        completed_keys.add(item_key)

        # Checkpoint save to CSV & Excel
        pd.DataFrame(results).to_csv(csv_file, index=False)
        if len(results) % 5 == 0 or len(results) == len(df_sample):
            save_audit_excel(pd.DataFrame(results), pair_title, arch_type, excel_file)

    df_res = pd.DataFrame(results)
    save_audit_excel(df_res, pair_title, arch_type, excel_file)
    return df_res

# ---------------------------------------------------------
# SAVE MULTI-TAB EXCEL WORKBOOK FOR EXP 2 CONFIGURATION
# ---------------------------------------------------------
def save_audit_excel(df_res, pair_title, arch_type, excel_file):
    if df_res.empty: return

    tot_time_s = round(df_res['total_latency_ms'].sum() / 1000.0, 1)
    duration_str = f"{int(tot_time_s // 60)}m {int(tot_time_s % 60)}s"

    try:
        with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
            # 1. Summary Metrics Sheet
            summary_rows = []
            for q_name in ["Q6", "Q8", "Q9", "Q22"]:
                q_df = df_res[df_res['question_no'] == q_name]
                if q_df.empty: continue
                
                q_grader_m = compute_metrics(q_df, pred_col="grader_score")
                q_auditor_m = compute_metrics(q_df, pred_col="auditor_score")
                q_reconciled_m = compute_metrics(q_df, pred_col="reconciled_score" if "reconciled_score" in q_df else "grader_score")
                
                q_unflagged = q_df[q_df['status'] == 'graded']
                pred_col = "reconciled_score" if "reconciled_score" in q_unflagged else "grader_score"
                q_unflagged_metrics = compute_metrics(q_unflagged, pred_col=pred_col) if len(q_unflagged) >= 3 else {}
                
                qc = compute_quality_control_metrics(q_df)
                
                summary_rows.append({
                    "Question": q_name,
                    "Sample Size (N)": len(q_df),
                    "Grader ICC": q_grader_m.get("ICC", 0.0),
                    "Grader MAE": q_grader_m.get("MAE", 0.0),
                    "Auditor ICC": q_auditor_m.get("ICC", 0.0),
                    "Auditor MAE": q_auditor_m.get("MAE", 0.0),
                    "Reconciled ICC": q_reconciled_m.get("ICC", 0.0),
                    "Reconciled MAE": q_reconciled_m.get("MAE", 0.0),
                    "Auto-Approved (N)": len(q_unflagged),
                    "Auto-Approved ICC": q_unflagged_metrics.get("ICC", q_reconciled_m.get("ICC", 0.0)),
                    "Auto-Approved MAE": q_unflagged_metrics.get("MAE", q_reconciled_m.get("MAE", 0.0)),
                    "Automation Rate (%)": f"{qc.get('Automation_Rate_Pct', 0.0)}%",
                    "Flag Rate (%)": f"{qc.get('Flag_Rate_Pct', 0.0)}%",
                    "Flagging Recall (%)": f"{qc.get('Recall_Pct', 0.0)}%",
                    "Flagging Precision (%)": f"{qc.get('Precision_Pct', 0.0)}%",
                    "Flagging F1-Score (%)": f"{qc.get('F1_Score_Pct', 0.0)}%",
                    "Leakage (FN Rate) (%)": f"{qc.get('Leakage_FN_Pct', 0.0)}%",
                    "Over-flag (FP Rate) (%)": f"{qc.get('Overflag_FP_Pct', 0.0)}%",
                    "Avg Latency (s)": round(q_df['total_latency_ms'].mean() / 1000.0, 2),
                    "Total Cost ($)": round(q_df['total_cost_usd'].sum(), 4)
                })

            overall_grader = compute_metrics(df_res, pred_col="grader_score")
            overall_auditor = compute_metrics(df_res, pred_col="auditor_score")
            overall_reconciled = compute_metrics(df_res, pred_col="reconciled_score" if "reconciled_score" in df_res else "grader_score")
            
            unflagged_all = df_res[df_res['status'] == 'graded']
            pred_col_all = "reconciled_score" if "reconciled_score" in unflagged_all else "grader_score"
            unflagged_metrics = compute_metrics(unflagged_all, pred_col=pred_col_all) if len(unflagged_all) >= 3 else {}
            
            qc_all = compute_quality_control_metrics(df_res)

            summary_rows.append({
                "Question": "TOTAL / OVERALL",
                "Sample Size (N)": len(df_res),
                "Grader ICC": overall_grader.get("ICC", 0.0),
                "Grader MAE": overall_grader.get("MAE", 0.0),
                "Auditor ICC": overall_auditor.get("ICC", 0.0),
                "Auditor MAE": overall_auditor.get("MAE", 0.0),
                "Reconciled ICC": overall_reconciled.get("ICC", 0.0),
                "Reconciled MAE": overall_reconciled.get("MAE", 0.0),
                "Auto-Approved (N)": len(unflagged_all),
                "Auto-Approved ICC": unflagged_metrics.get("ICC", 0.0),
                "Auto-Approved MAE": unflagged_metrics.get("MAE", 0.0),
                "Automation Rate (%)": f"{qc_all.get('Automation_Rate_Pct', 0.0)}%",
                "Flag Rate (%)": f"{qc_all.get('Flag_Rate_Pct', 0.0)}%",
                "Flagging Recall (%)": f"{qc_all.get('Recall_Pct', 0.0)}%",
                "Flagging Precision (%)": f"{qc_all.get('Precision_Pct', 0.0)}%",
                "Flagging F1-Score (%)": f"{qc_all.get('F1_Score_Pct', 0.0)}%",
                "Leakage (FN Rate) (%)": f"{qc_all.get('Leakage_FN_Pct', 0.0)}%",
                "Over-flag (FP Rate) (%)": f"{qc_all.get('Overflag_FP_Pct', 0.0)}%",
                "Avg Latency (s)": round(df_res['total_latency_ms'].mean() / 1000.0, 2),
                "Total Cost ($)": round(df_res['total_cost_usd'].sum(), 4)
            })

            df_sum = pd.DataFrame(summary_rows)
            df_sum.to_excel(writer, sheet_name="Audit_Summary", index=False)

            # 2. 3-Way Comparative Evaluation Sheet (Grader vs Auditor vs Reconciled vs Human)
            comp_rows = []
            score_types = [
                ("1. Primary Grader (Baseline)", "grader_score", df_res),
                ("2. Auditor (Secondary Verification)", "auditor_score", df_res),
                ("3. Reconciled Final Score (Proposed)", "reconciled_score" if "reconciled_score" in df_res else "grader_score", df_res),
                ("4. Auto-Approved Subset (Reconciled)", "reconciled_score" if "reconciled_score" in unflagged_all else "grader_score", unflagged_all)
            ]
            for label, p_col, target_df in score_types:
                m = compute_metrics(target_df, pred_col=p_col) if len(target_df) >= 3 else {}
                comp_rows.append({
                    "Evaluation Score Stream": label,
                    "Evaluated N": len(target_df),
                    "ICC(A,1)": m.get("ICC", 0.0),
                    "MAE (pts)": m.get("MAE", 0.0),
                    "Norm MAE (%)": f"{m.get('Normalized_MAE_Pct', 0.0)}%",
                    "Mean Error (Bias)": m.get("Mean_Error", 0.0),
                    "Pearson r": m.get("Pearson_r", 0.0),
                    "Spearman rho": m.get("Spearman_rho", 0.0),
                    "Exact Match (%)": f"{m.get('Exact_Match_Pct', 0.0)}%",
                    "Within ±1 Mark (%)": f"{m.get('Within_1_Mark_Pct', 0.0)}%"
                })
            df_comp = pd.DataFrame(comp_rows)
            df_comp.to_excel(writer, sheet_name="3Way_Score_Comparison", index=False)

            # 3. Individual Question Tabs
            for q_name in ["Q6", "Q8", "Q9", "Q22"]:
                q_df = df_res[df_res['question_no'] == q_name].copy()
                if not q_df.empty:
                    q_cols = ["response_id", "human_score", "grader_score", "auditor_score", "reconciled_score", "score_discrepancy", "status", "confidence_score", "flag_reasons", "student_answer", "audit_note"]
                    available_cols = [c for c in q_cols if c in q_df.columns]
                    q_df[available_cols].to_excel(writer, sheet_name=f"{q_name}_Audit", index=False)

            # 4. Flagged Review Queue (Submissions sent to lecturer)
            flagged_df = df_res[df_res['status'] == 'flagged'].copy()
            if not flagged_df.empty:
                f_cols = ["response_id", "question_no", "human_score", "grader_score", "auditor_score", "reconciled_score", "score_discrepancy", "flag_reasons", "audit_note", "student_answer"]
                available_f_cols = [c for c in f_cols if c in flagged_df.columns]
                flagged_df[available_f_cols].to_excel(writer, sheet_name="Flagged_For_Lecturer", index=False)

            # 5. Full Dataset
            df_res.to_excel(writer, sheet_name="All_Responses", index=False)

        print(f"✅ Excel saved: {excel_file}")
        print("\n" + df_sum.to_string(index=False))
        print("\n--- 📊 3-Way Score Stream Comparison ---")
        print(df_comp.to_string(index=False))
    except Exception as e:
        print(f"  ⚠️ Warning saving Excel: {e}")

# ---------------------------------------------------------
# GENERATE MASTER AUDIT COMPARISON EXCEL ACROSS ALL RUNS
# ---------------------------------------------------------
def generate_master_audit_comparison():
    print("\n" + "="*85)
    print("📊 GENERATING MASTER EXPERIMENT 2 COMPARISON EXCEL...")
    print("="*85)
    
    master_excel = os.path.join(script_dir, "Experiment_2_Audit_Master_Comparison.xlsx")
    csv_files = glob.glob(os.path.join(script_dir, "results_exp2_*.csv"))

    if not csv_files:
        print("No completed Experiment 2 CSV results found.")
        return

    with pd.ExcelWriter(master_excel, engine='openpyxl') as writer:
        leaderboard_rows = []
        comp_leaderboard_rows = []
        for csv_path in sorted(csv_files):
            file_name = os.path.basename(csv_path)
            # Tag parsing e.g. results_exp2_Gemini_3.1_Flash_Lite_to_Nemotron_3_Super_120B.csv
            tag = file_name.replace("results_exp2_", "").replace(".csv", "")
            parts = tag.split("_to_")
            g_tag = parts[0] if len(parts) > 0 else tag
            a_tag = parts[1] if len(parts) > 1 else tag
            
            g_name = g_tag.replace("_", " ")
            a_name = a_tag.replace("_", " ")
            title = f"{g_name} ➔ {a_name}"
            arch_type = "Self-Audit" if g_tag == a_tag else "Heterogeneous"

            try:
                df_c = pd.read_csv(csv_path)
                if df_c.empty: continue
            except Exception:
                continue

            grader_m = compute_metrics(df_c, pred_col="grader_score")
            auditor_m = compute_metrics(df_c, pred_col="auditor_score")
            reconciled_m = compute_metrics(df_c, pred_col="reconciled_score" if "reconciled_score" in df_c else "grader_score")
            
            unflagged_df = df_c[df_c['status'] == 'graded']
            pred_col_unflagged = "reconciled_score" if "reconciled_score" in unflagged_df else "grader_score"
            unflagged_metrics = compute_metrics(unflagged_df, pred_col=pred_col_unflagged) if len(unflagged_df) >= 3 else {}
            
            qc = compute_quality_control_metrics(df_c)
            tot_time_s = round(df_c['total_latency_ms'].sum() / 1000.0, 1) if 'total_latency_ms' in df_c else 0.0
            tot_cost = df_c['total_cost_usd'].sum() if 'total_cost_usd' in df_c else 0.0

            leaderboard_rows.append({
                "Architecture / Model Pairing": title,
                "Type": arch_type,
                "Grader ICC": grader_m.get("ICC", 0.0),
                "Grader MAE": grader_m.get("MAE", 0.0),
                "Auditor ICC": auditor_m.get("ICC", 0.0),
                "Auditor MAE": auditor_m.get("MAE", 0.0),
                "Reconciled ICC": reconciled_m.get("ICC", 0.0),
                "Reconciled MAE": reconciled_m.get("MAE", 0.0),
                "Auto-Approved ICC": unflagged_metrics.get("ICC", 0.0),
                "Auto-Approved MAE": unflagged_metrics.get("MAE", 0.0),
                "Automation Rate (%)": f"{qc.get('Automation_Rate_Pct', 0.0)}%",
                "Flag Rate (%)": f"{qc.get('Flag_Rate_Pct', 0.0)}%",
                "Flagging Recall (%)": f"{qc.get('Recall_Pct', 0.0)}%",
                "Flagging Precision (%)": f"{qc.get('Precision_Pct', 0.0)}%",
                "Flagging F1-Score (%)": f"{qc.get('F1_Score_Pct', 0.0)}%",
                "Leakage (FN Rate) (%)": f"{qc.get('Leakage_FN_Pct', 0.0)}%",
                "Over-flag (FP Rate) (%)": f"{qc.get('Overflag_FP_Pct', 0.0)}%",
                "Avg Latency (s)": round(df_c['total_latency_ms'].mean() / 1000.0, 2) if 'total_latency_ms' in df_c else 0.0,
                "Total Run Time": f"{int(tot_time_s // 60)}m {int(tot_time_s % 60)}s",
                "Total Cost (100 Qs)": f"${round(tot_cost, 4)}"
            })

            comp_leaderboard_rows.append({
                "Architecture": title,
                "Grader ICC": grader_m.get("ICC", 0.0),
                "Grader MAE": grader_m.get("MAE", 0.0),
                "Auditor ICC": auditor_m.get("ICC", 0.0),
                "Auditor MAE": auditor_m.get("MAE", 0.0),
                "Reconciled ICC": reconciled_m.get("ICC", 0.0),
                "Reconciled MAE": reconciled_m.get("MAE", 0.0),
                "ICC Delta (Reconciled - Grader)": round(reconciled_m.get("ICC", 0.0) - grader_m.get("ICC", 0.0), 3),
                "MAE Delta (Reconciled - Grader)": round(reconciled_m.get("MAE", 0.0) - grader_m.get("MAE", 0.0), 3),
                "Auto-Approved ICC": unflagged_metrics.get("ICC", 0.0),
                "Auto-Approved MAE": unflagged_metrics.get("MAE", 0.0)
            })

        df_leaderboard = pd.DataFrame(leaderboard_rows)
        df_leaderboard.to_excel(writer, sheet_name="Audit_Architecture_Leaderboard", index=False)
        
        df_comp_leaderboard = pd.DataFrame(comp_leaderboard_rows)
        df_comp_leaderboard.to_excel(writer, sheet_name="3Way_Stream_Comparison", index=False)

    print(f"🌟 Master Experiment 2 Excel saved: {master_excel}")
    print("\n--- 🏆 Experiment 2: Multi-Agent Auditor Leaderboard ---")
    print(df_leaderboard.to_string(index=False))

    print(f"🌟 Master Experiment 2 Excel saved: {master_excel}")
    print("\n--- 🏆 Experiment 2: Multi-Agent Auditor Leaderboard ---")
    print(df_leaderboard.to_string(index=False))

# ---------------------------------------------------------
# MAIN CLI (Manual Model Specification)
# ---------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Experiment 2: Manual Grader ➔ Auditor Quality-Control Evaluation.")
    parser.add_argument("--grader", type=str, default=None,
                        help="Grader model key (A, B, C, D) or full OpenRouter model string (e.g. google/gemini-3.1-flash-lite).")
    parser.add_argument("--auditor", type=str, default=None,
                        help="Auditor model key (A, B, C, D) or full OpenRouter model string (e.g. nvidia/nemotron-3-super-120b-a12b).")
    parser.add_argument("--samples", type=int, default=10,
                        help="Number of student responses per question (e.g. 10 for 40 total, 25 for 100 total). [Default: 10]")
    parser.add_argument("--fresh", action="store_true",
                        help="Start a fresh run, ignoring previous checkpoint CSVs.")
    parser.add_argument("--compile_only", action="store_true",
                        help="Only re-generate Master comparison Excel from existing CSVs.")
    args = parser.parse_args()

    if args.compile_only:
        generate_master_audit_comparison()
        return

    # Interactive prompt if not supplied via CLI flags
    grader_input = args.grader
    if not grader_input:
        print("\nAvailable Preset Models:")
        print("  [A] Gemini 3.1 Flash Lite  (google/gemini-3.1-flash-lite)")
        print("  [B] Nemotron 3 Super 120B  (nvidia/nemotron-3-super-120b-a12b)")
        print("  [C] Claude 4.6 Sonnet      (anthropic/claude-sonnet-4.6)")
        print("  [D] Gemini 3.5 Flash Lite  (google/gemini-3.5-flash-lite)")
        grader_input = input("\nEnter Grader model (A, B, C, D, or custom OpenRouter string) [Default: A]: ").strip()
        if not grader_input:
            grader_input = "A"

    auditor_input = args.auditor
    if not auditor_input:
        auditor_input = input("Enter Auditor model (A, B, C, D, or custom OpenRouter string) [Default: B]: ").strip()
        if not auditor_input:
            auditor_input = "B"

    grader_info = resolve_model(grader_input, default_role="Grader")
    auditor_info = resolve_model(auditor_input, default_role="Auditor")

    print(f"\nSelected Configuration:")
    print(f"  • Primary Grader : {grader_info['name']} ({grader_info['model_str']})")
    print(f"  • Quality Auditor: {auditor_info['name']} ({auditor_info['model_str']})")

    print(f"\nLoading datasets ({args.samples} per question)...")
    df_questions, df_sample = get_stratified_dataset(samples_per_question=args.samples, seed=42)
    print(f"Sampled {len(df_sample)} student responses ({args.samples} per question across Q6, Q8, Q9, Q22).")

    run_manual_audit_experiment(grader_info, auditor_info, df_questions, df_sample, fresh=args.fresh)
    generate_master_audit_comparison()

if __name__ == "__main__":
    main()
