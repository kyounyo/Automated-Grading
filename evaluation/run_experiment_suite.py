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
    interpret_rubric_spec,
    grade_with_spec,
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
    for q_no in [22]:
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
# DYNAMIC RUBRIC-INTERPRETER ARCHITECTURE (question-type routing, not
# question-number routing -- see llm_service.py's module comment above
# _build_rubric_interpreter_prompt for the full rationale)
# ---------------------------------------------------------
def run_single_model_dynamic(model_key, df_questions, df_sample):
    """
    Grades every response in df_sample using the dynamic Rubric Interpreter
    architecture (interpret_rubric_spec + grade_with_spec) -- question-TYPE
    routing, no question-number checks, no hardcoded per-question constants.

    Interprets the rubric ONCE per question (not once per response -- see
    interpret_rubric_spec's docstring for why re-interpreting per response would
    corrupt the comparison), prints the resulting Grading Specification's
    question_type and any review_flags so you can eyeball what the interpreter
    produced before trusting the scores below it, then grades every response to
    that question with the same spec.

    Writes to results_DYNAMIC_<tag>.csv/.xlsx -- entirely separate from every
    legacy-path file (results_<tag>.csv, results_RUBRIC_SEMANTIC_<tag>.csv, the
    Q22_BATCH_SESSION_* files) so this can never collide with or be confused for
    a hardcoded-path result.
    """
    model_info = MODELS[model_key]
    model_name = model_info["name"]
    model_str = model_info["model_str"]
    file_tag = model_info["file_tag"]

    print("\n" + "="*80)
    print(f"🚀 EVALUATING MODEL {model_key}: {model_name} [ARCHITECTURE: DYNAMIC RUBRIC INTERPRETER] ({len(df_sample)} responses)")
    print("="*80)

    csv_file = os.path.join(script_dir, f"results_DYNAMIC_{file_tag}.csv")
    excel_file = os.path.join(script_dir, f"results_DYNAMIC_{file_tag}.xlsx")

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

    for q_no_raw in sorted(df_sample['question_no'].astype(str).str.strip().str.replace('Q', '').unique(), key=lambda x: (len(x), x)):
        q_group = df_sample[df_sample['question_no'].astype(str).str.strip().str.replace('Q', '') == q_no_raw]
        matched_q = df_questions[df_questions['question_no'].astype(str).str.strip().str.replace('Q', '') == q_no_raw]
        if matched_q.empty:
            print(f"  ⚠️ No question/rubric entry found for Q{q_no_raw} -- skipping.")
            continue

        q_row = matched_q.iloc[0]
        question_text = q_row['question']
        rubric_text = q_row['answer']
        max_score = float(q_row['max_mark'])

        # Interpret the rubric ONCE for this question, reuse for every response to it.
        # This single call is far higher-leverage than any one grading call -- a
        # failure here silently excludes every response to this question from
        # metrics, not just one row -- so it gets its own retry loop on top of
        # _call_openrouter_api's internal HTTP retries, to ride out a transient
        # API hiccup rather than losing an entire question's worth of data to it.
        print(f"\n  --- Interpreting rubric for Q{q_no_raw} ({len(q_group)} responses) ---")
        interp_start = time.time()
        spec = None
        INTERPRETER_MAX_ATTEMPTS = 3
        for attempt in range(1, INTERPRETER_MAX_ATTEMPTS + 1):
            spec = interpret_rubric_spec(question_text, rubric_text, max_score, model=model_str)
            if spec:
                break
            if attempt < INTERPRETER_MAX_ATTEMPTS:
                print(f"     ⚠️ Interpreter attempt {attempt}/{INTERPRETER_MAX_ATTEMPTS} failed for "
                      f"Q{q_no_raw} -- retrying...")
                time.sleep(3)
        interp_latency_ms = round((time.time() - interp_start) * 1000)
        if spec:
            print(f"  ✅ Q{q_no_raw} classified as: {spec.get('question_type')} "
                  f"(interpreter took {interp_latency_ms}ms)")
            for rf in spec.get("_review_flags", []):
                print(f"     ⚠️ REVIEW FLAG: {rf}")
        else:
            print(f"  ❌ Q{q_no_raw}: Rubric Interpreter failed after {INTERPRETER_MAX_ATTEMPTS} attempts -- "
                  f"every response to this question will be excluded from metrics.")

        for idx, row in q_group.iterrows():
            resp_id = str(row['ID Number'])
            human_score = float(row['grade'])
            ans_text = row['Response']

            item_key = f"{resp_id}_{q_no_raw}"
            if item_key in completed_keys:
                continue

            clean_ans = str(ans_text).strip() if pd.notna(ans_text) else ""
            print(f"  [{len(results)+1}/{len(df_sample)}] Q{q_no_raw} | Student {resp_id} | Grading with {model_name} (dynamic)...")

            start_time = time.time()
            if not clean_ans or clean_ans.lower() in ["-", "n/a", "none", "nan"]:
                res, score, latency = {"reasoning": "Blank answer provided. 0 marks awarded."}, 0.0, 0
            elif not spec:
                res, score, latency = (
                    {"reasoning": "Rubric interpretation failed for this question -- excluded from metrics."},
                    float("nan"), round((time.time() - start_time) * 1000),
                )
            else:
                res = grade_with_spec(clean_ans, question_text, spec, model_str)
                latency = round((time.time() - start_time) * 1000)
                if not res:
                    res, score = {"reasoning": "Dynamic grading call failed after all retries -- excluded from metrics."}, float("nan")
                else:
                    score = max(0.0, min(max_score, float(res.get("overall_score", 0.0))))

            rec = {
                "response_id": resp_id,
                "question_no": f"Q{q_no_raw}",
                "question_type": spec.get("question_type") if spec else "",
                "human_score": human_score,
                "predicted_score": score,
                "max_score": max_score,
                "absolute_error": round(abs(score - human_score), 2) if pd.notna(score) else None,
                "difference (AI - Human)": round(score - human_score, 2) if pd.notna(score) else None,
                "latency_ms": latency,
                "student_answer": str(ans_text),
                "reasoning": str(res.get("reasoning", "")),
                "flag_reasons": "; ".join(res.get("flag_reasons", [])) if isinstance(res.get("flag_reasons"), list) else "",
                "raw_json": json.dumps(res, ensure_ascii=False),
            }
            results.append(rec)
            pd.DataFrame(results).to_csv(csv_file, index=False)
            if len(results) % 5 == 0 or len(results) == len(df_sample):
                save_model_excel(pd.DataFrame(results), model_name, excel_file)

    df_model_res = pd.DataFrame(results)
    save_model_excel(df_model_res, model_name, excel_file)
    return df_model_res


# ---------------------------------------------------------
# Q22 BATCH-SESSION EXPERIMENT (isolates cohort-calibration variable)
# ---------------------------------------------------------
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

def generate_master_comparison_dynamic():
    """
    Reads the results_DYNAMIC_<tag>.csv files written by run_single_model_dynamic()
    and builds a master comparison Excel workbook, with metrics broken down by both
    question_no and question_type so misclassifications are visible alongside ICC.
    """
    print("\n" + "="*80)
    print("📊 GENERATING DYNAMIC-ARCHITECTURE MASTER COMPARISON EXCEL...")
    print("="*80)

    master_excel = os.path.join(script_dir, "Model_Comparison_Master_DYNAMIC.xlsx")
    model_data = {}
    for m_key, m_info in MODELS.items():
        csv_file = os.path.join(script_dir, f"results_DYNAMIC_{m_info['file_tag']}.csv")
        if os.path.exists(csv_file):
            model_data[m_info['name']] = pd.read_csv(csv_file)

    if not model_data:
        print("No completed dynamic-architecture evaluations found.")
        return

    all_questions = sorted({q for df_m in model_data.values() for q in df_m['question_no'].unique()})

    with pd.ExcelWriter(master_excel, engine='openpyxl') as writer:
        overall_rows = []
        for m_name, df_m in model_data.items():
            metrics = compute_metrics(df_m)
            avg_lat = df_m['latency_ms'].mean() / 1000.0 if not df_m.empty and 'latency_ms' in df_m else 0.0
            overall_rows.append({
                "Model": m_name,
                "Overall ICC (A,1)": metrics.get("ICC", 0.0),
                "Overall MAE": metrics.get("MAE", 0.0),
                "Mean Error (Bias)": metrics.get("Mean_Error", 0.0),
                "Pearson r": metrics.get("Pearson_r", 0.0),
                "Spearman ρ": metrics.get("Spearman_rho", 0.0),
                "N": metrics.get("N", 0),
                "Avg Latency / Response (s)": round(avg_lat, 2),
            })
        df_overall = pd.DataFrame(overall_rows)
        df_overall.to_excel(writer, sheet_name="Overall_Leaderboard", index=False)

        icc_matrix_rows = []
        for m_name, df_m in model_data.items():
            row = {"Model": m_name}
            for q_name in all_questions:
                q_df = df_m[df_m['question_no'] == q_name]
                row[f"{q_name} ICC"] = compute_metrics(q_df).get("ICC", 0.0) if not q_df.empty else 0.0
                row[f"{q_name} question_type"] = q_df['question_type'].iloc[0] if not q_df.empty and 'question_type' in q_df else ""
            icc_matrix_rows.append(row)
        df_icc = pd.DataFrame(icc_matrix_rows)
        df_icc.to_excel(writer, sheet_name="ICC_Per_Question_Matrix", index=False)

        for m_name, df_m in model_data.items():
            df_m.to_excel(writer, sheet_name=f"All_{m_name[:25]}", index=False)

    print(f"🌟 Dynamic-architecture comparison Excel generated: {master_excel}")
    print("\n--- 🏆 Overall Leaderboard (DYNAMIC) ---")
    print(df_overall.to_string(index=False))
    print("\n--- 📋 Per-Question ICC Matrix (DYNAMIC) ---")
    print(df_icc.to_string(index=False))
    print("\nCompare each row above against the SAME question's ICC in the existing "
          "results_<model>.csv (legacy hardcoded path) to see whether the dynamic "
          "architecture reproduces comparable agreement.")

# ---------------------------------------------------------
# MAIN CLI
# ---------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Evaluate models using the dynamic Rubric Interpreter architecture and generate Excel reports."
    )
    parser.add_argument("--model", type=str, choices=["A", "B", "C", "all"], default="all",
                        help="Choose 'A' (Gemini 3.1 Flash Lite), 'B' (Nemotron 3 Super 120B), 'C' (Claude 4.6 Sonnet), or 'all'.")
    args = parser.parse_args()

    print("Loading datasets...")
    # samples_per_question is capped at however many responses actually exist
    # per question (see get_stratified_dataset's n=min(samples_per_question,
    # len(q_subset))), so 130 here pulls every Q22 response rather than a
    # 25-response sample -- change this number to adjust coverage.
    df_questions, df_sample = get_stratified_dataset(samples_per_question=130, seed=42)
    print(f"Sampled {len(df_sample)} student responses (currently Q22 only -- see get_stratified_dataset's question loop).")

    if args.model in ["A", "all"]:
        run_single_model_dynamic("A", df_questions, df_sample)
    if args.model in ["B", "all"]:
        run_single_model_dynamic("B", df_questions, df_sample)
    if args.model in ["C", "all"]:
        run_single_model_dynamic("C", df_questions, df_sample)

    generate_master_comparison_dynamic()

if __name__ == "__main__":
    main()
