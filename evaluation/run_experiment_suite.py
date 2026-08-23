import os
import re
import sys
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

# Import exact backend agent implementations
from app.services.llm_service import (
    call_primary_grading_agent,
    get_openrouter_api_key
)

if not get_openrouter_api_key():
    print("❌ Error: No OPENROUTER_API_KEY found in evaluation/.env")
    sys.exit(1)

# ---------------------------------------------------------
# MODEL DEFINITIONS (Claude disabled for fast evaluation)
# ---------------------------------------------------------
MODELS = {
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
        "cost_per_1k_out": 0.0150}
}

# ---------------------------------------------------------
# SAMPLING & DATASET LOADER (Stratified 25 x 4 = 100 Responses)
# ---------------------------------------------------------
def get_stratified_dataset(samples_per_question=25, seed=42):
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
# STATISTICAL METRICS CALCULATOR
# ---------------------------------------------------------
def compute_metrics(df_results, pred_col="predicted_score", target_col="human_score"):
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

# ---------------------------------------------------------
# RUNNER: BACKEND AGENT 2 PRIMARY GRADER
# ---------------------------------------------------------
def grade_with_backend_agent(model_key, question_no, question_text, rubric_text, max_score, student_answer):
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

    model_info = MODELS[model_key]
    model_str = model_info["model_str"]

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
    cost = (actual_in_tok / 1000.0 * model_info["cost_per_1k_in"]) + (actual_out_tok / 1000.0 * model_info["cost_per_1k_out"])

    return res, score, actual_in_tok, actual_out_tok, cost, latency_ms

# ---------------------------------------------------------
# RUN SINGLE MODEL ACROSS ALL 100 RESPONSES
# ---------------------------------------------------------
def run_single_model(model_key, df_questions, df_sample):
    model_info = MODELS[model_key]
    model_name = model_info["name"]
    file_tag = model_info["file_tag"]
    
    print("\n" + "="*80)
    print(f"🚀 EVALUATING MODEL {model_key}: {model_name} (100 responses: 25 per Question)")
    print("="*80)
    
    csv_file = os.path.join(script_dir, f"results_{file_tag}.csv")
    excel_file = os.path.join(script_dir, f"results_{file_tag}.xlsx")
    
    results = []
    completed_keys = set()
    
    if os.path.exists(csv_file) and os.path.getsize(csv_file) > 0:
        try:
            prev_df = pd.read_csv(csv_file)
            results = prev_df.to_dict('records')
            for r in results:
                q_clean = str(r['question_no']).strip().replace('Q', '')
                completed_keys.add(f"{r['response_id']}_{q_clean}")
            print(f"🔄 Checkpoint: Loaded {len(completed_keys)} already graded responses for {model_name}.")
        except Exception:
            pass

    model_start_time = time.time()
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

        print(f"  [{len(results)+1}/100] Q{q_no} | Student {resp_id} | Grading with {model_name}...")
        
        raw_eval, score, in_tok, out_tok, cost, latency = grade_with_backend_agent(
            model_key=model_key,
            question_no=q_no,
            question_text=question_text,
            rubric_text=rubric,
            max_score=max_score,
            student_answer=ans_text
        )

        rec = {
            "response_id": resp_id,
            "question_no": f"Q{q_no}",
            "human_score": human_score,
            "predicted_score": score,
            "max_score": max_score,
            "absolute_error": round(abs(score - human_score), 2),
            "difference (AI - Human)": round(score - human_score, 2),
            "latency_ms": latency,
            "actual_input_tokens": in_tok,
            "actual_output_tokens": out_tok,
            "estimated_cost_usd": round(cost, 6),
            "student_answer": str(ans_text),
            "reasoning": str(raw_eval.get("reasoning", "")),
            "raw_json": json.dumps(raw_eval, ensure_ascii=False)
        }
        results.append(rec)
        # Continuous Checkpoint save to CSV & Excel
        pd.DataFrame(results).to_csv(csv_file, index=False)
        if len(results) % 5 == 0 or len(results) == len(df_sample):
            save_model_excel(pd.DataFrame(results), model_name, excel_file)

    df_model_res = pd.DataFrame(results)
    save_model_excel(df_model_res, model_name, excel_file)
    return df_model_res


def save_model_excel(df_model_res, model_name, excel_file):
    """Saves multi-tab Excel workbook for a model (called continuously and on completion)."""
    if df_model_res.empty:
        return

    total_model_duration_s = round(df_model_res['latency_ms'].sum() / 1000.0, 1)
    duration_str = f"{int(total_model_duration_s // 60)}m {int(total_model_duration_s % 60)}s"

    try:
        with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
            # Sheet 1: Summary by Question & Overall
            summary_rows = []
            for q_name in ["Q6", "Q8", "Q9", "Q22"]:
                q_df = df_model_res[df_model_res['question_no'] == q_name]
                if q_df.empty:
                    continue
                q_metrics = compute_metrics(q_df)
                q_max = q_df['max_score'].iloc[0] if not q_df.empty else 10.0
                q_time_s = round(q_df['latency_ms'].sum() / 1000.0, 1) if not q_df.empty else 0.0
                cost_col = 'estimated_cost_usd' if 'estimated_cost_usd' in q_df else 'cost_usd'
                q_cost = round(q_df[cost_col].sum(), 4) if not q_df.empty and cost_col in q_df else 0.0
                summary_rows.append({
                    "Question": q_name,
                    "Max Mark": q_max,
                    "Sample Size (N)": len(q_df),
                    "ICC (A,1)": q_metrics.get("ICC", 0.0),
                    "MAE": q_metrics.get("MAE", 0.0),
                    "Normalized MAE (%)": f"{q_metrics.get('Normalized_MAE_Pct', 0.0)}%",
                    "Mean Error (Bias)": q_metrics.get("Mean_Error", 0.0),
                    "Exact Match (%)": f"{q_metrics.get('Exact_Match_Pct', 0.0)}%",
                    "±1 Mark (%)": f"{q_metrics.get('Within_1_Mark_Pct', 0.0)}%",
                    "Pearson r": q_metrics.get("Pearson_r", 0.0),
                    "Spearman ρ": q_metrics.get("Spearman_rho", 0.0),
                    "Avg Latency (s)": round(q_df['latency_ms'].mean() / 1000.0, 2) if not q_df.empty else 0.0,
                    "Section Run Time": f"{int(q_time_s // 60)}m {int(q_time_s % 60)}s",
                    "Total Cost ($)": q_cost
                })

            overall_metrics = compute_metrics(df_model_res)
            cost_col_all = 'estimated_cost_usd' if 'estimated_cost_usd' in df_model_res else 'cost_usd'
            tot_cost_all = round(df_model_res[cost_col_all].sum(), 4) if not df_model_res.empty and cost_col_all in df_model_res else 0.0
            summary_rows.append({
                "Question": "TOTAL / OVERALL",
                "Max Mark": "All",
                "Sample Size (N)": len(df_model_res),
                "ICC (A,1)": overall_metrics.get("ICC", 0.0),
                "MAE": overall_metrics.get("MAE", 0.0),
                "Normalized MAE (%)": f"{overall_metrics.get('Normalized_MAE_Pct', 0.0)}%",
                "Mean Error (Bias)": overall_metrics.get("Mean_Error", 0.0),
                "Exact Match (%)": f"{overall_metrics.get('Exact_Match_Pct', 0.0)}%",
                "±1 Mark (%)": f"{overall_metrics.get('Within_1_Mark_Pct', 0.0)}%",
                "Pearson r": overall_metrics.get("Pearson_r", 0.0),
                "Spearman ρ": overall_metrics.get("Spearman_rho", 0.0),
                "Avg Latency (s)": round(df_model_res['latency_ms'].mean() / 1000.0, 2),
                "Section Run Time": duration_str,
                "Total Cost ($)": tot_cost_all
            })
            
            df_summary = pd.DataFrame(summary_rows)
            df_summary.to_excel(writer, sheet_name="Summary_Metrics", index=False)

            # Sheets 2-5: Individual Question tabs
            for q_name in ["Q6", "Q8", "Q9", "Q22"]:
                q_df = df_model_res[df_model_res['question_no'] == q_name].copy()
                if not q_df.empty:
                    clean_q_cols = ["response_id", "human_score", "predicted_score", "absolute_error", "difference (AI - Human)", "latency_ms", "reasoning", "student_answer"]
                    q_df[clean_q_cols].to_excel(writer, sheet_name=f"{q_name}_({len(q_df)}_Students)", index=False)

            # Sheet 6: Full Raw Dataset
            df_model_res.to_excel(writer, sheet_name="All_Responses", index=False)
    except Exception as e:
        print(f"  ⚠️ Warning saving Excel: {e}")

# ---------------------------------------------------------
# GENERATE MASTER COMPARISON EXCEL
# ---------------------------------------------------------
def generate_master_comparison():
    """Builds side-by-side comparative Excel across all evaluated models."""
    print("\n" + "="*80)
    print("📊 GENERATING MASTER MODEL COMPARISON EXCEL...")
    print("="*80)
    
    master_excel = os.path.join(script_dir, "Model_Comparison_Master.xlsx")
    model_data = {}
    
    for m_key, m_info in MODELS.items():
        csv_file = os.path.join(script_dir, f"results_{m_info['file_tag']}.csv")
        if os.path.exists(csv_file):
            model_data[m_info['name']] = pd.read_csv(csv_file)

    if not model_data:
        print("No completed model evaluations found.")
        return

    with pd.ExcelWriter(master_excel, engine='openpyxl') as writer:
        # Sheet 1: Overall Model Comparison Leaderboard
        overall_rows = []
        for m_name, df_m in model_data.items():
            metrics = compute_metrics(df_m)
            avg_lat = df_m['latency_ms'].mean() / 1000.0 if not df_m.empty and 'latency_ms' in df_m else 0.0
            tot_time_s = round(df_m['latency_ms'].sum() / 1000.0, 1) if not df_m.empty and 'latency_ms' in df_m else 0.0
            cost_col = 'estimated_cost_usd' if 'estimated_cost_usd' in df_m else 'cost_usd'
            tot_cost = df_m[cost_col].sum() if not df_m.empty and cost_col in df_m else 0.0
            
            overall_rows.append({
                "Model": m_name,
                "Overall ICC (A,1)": metrics.get("ICC", 0.0),
                "Overall MAE": metrics.get("MAE", 0.0),
                "Normalized MAE (%)": f"{metrics.get('Normalized_MAE_Pct', 0.0)}%",
                "Mean Error (Bias)": metrics.get("Mean_Error", 0.0),
                "Exact Match (%)": f"{metrics.get('Exact_Match_Pct', 0.0)}%",
                "±1 Mark (%)": f"{metrics.get('Within_1_Mark_Pct', 0.0)}%",
                "Pearson r": metrics.get("Pearson_r", 0.0),
                "Spearman ρ": metrics.get("Spearman_rho", 0.0),
                "Avg Latency / Response (s)": round(avg_lat, 2),
                "Total Run Time": f"{int(tot_time_s // 60)}m {int(tot_time_s % 60)}s",
                "Total Cost (100 Qs)": f"${round(tot_cost, 4)}"
            })
        df_overall = pd.DataFrame(overall_rows)
        df_overall.to_excel(writer, sheet_name="Overall_Leaderboard", index=False)

        # Sheet 2: Per-Question ICC Matrix (Q6, Q8, Q9, Q22, Average, Overall)
        icc_matrix_rows = []
        for m_name, df_m in model_data.items():
            row = {"Model": m_name}
            q_iccs = []
            for q_name in ["Q6", "Q8", "Q9", "Q22"]:
                q_df = df_m[df_m['question_no'] == q_name]
                q_icc = compute_metrics(q_df).get("ICC", 0.0) if not q_df.empty else 0.0
                row[f"{q_name} ICC"] = q_icc
                q_iccs.append(q_icc)
            row["Average Question ICC"] = round(sum(q_iccs) / len(q_iccs), 3) if q_iccs else 0.0
            row["Total Overall ICC"] = compute_metrics(df_m).get("ICC", 0.0)
            icc_matrix_rows.append(row)
        df_icc = pd.DataFrame(icc_matrix_rows)
        df_icc.to_excel(writer, sheet_name="ICC_Per_Question_Matrix", index=False)

        # Sheet 3: Per-Question MAE Matrix
        mae_matrix_rows = []
        for m_name, df_m in model_data.items():
            row = {"Model": m_name}
            q_maes = []
            for q_name in ["Q6", "Q8", "Q9", "Q22"]:
                q_df = df_m[df_m['question_no'] == q_name]
                q_mae = compute_metrics(q_df).get("MAE", 0.0) if not q_df.empty else 0.0
                row[f"{q_name} MAE"] = q_mae
                q_maes.append(q_mae)
            row["Average Question MAE"] = round(sum(q_maes) / len(q_maes), 3) if q_maes else 0.0
            row["Total Overall MAE"] = compute_metrics(df_m).get("MAE", 0.0)
            mae_matrix_rows.append(row)
        df_mae = pd.DataFrame(mae_matrix_rows)
        df_mae.to_excel(writer, sheet_name="MAE_Per_Question_Matrix", index=False)

    print(f"🌟 Master comparison Excel generated: {master_excel}")
    print("\n--- 🏆 Overall Leaderboard ---")
    print(df_overall.to_string(index=False))
    print("\n--- 📋 Per-Question ICC Matrix ---")
    print(df_icc.to_string(index=False))

# ---------------------------------------------------------
# MAIN CLI
# ---------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Evaluate models individually and generate Excel reports.")
    parser.add_argument("--model", type=str, choices=["A", "B", "C", "all"], default="all",
                        help="Choose 'A' (Gemini 3.1 Flash Lite), 'B' (Nemotron 3 Super 120B), 'C' (Claude 4.6 Sonnet), or 'all'.")
    args = parser.parse_args()

    print("Loading datasets...")
    df_questions, df_sample = get_stratified_dataset(samples_per_question=25, seed=42)
    print(f"Sampled {len(df_sample)} student responses (25 per question across Q6, Q8, Q9, Q22).")

    if args.model in ["A", "all"]:
        run_single_model("A", df_questions, df_sample)
    if args.model in ["B", "all"]:
        run_single_model("B", df_questions, df_sample)
    if args.model in ["C", "all"]:
        run_single_model("C", df_questions, df_sample)

    generate_master_comparison()

if __name__ == "__main__":
    main()
