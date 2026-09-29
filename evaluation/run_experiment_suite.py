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
    grade_q22_batch_session,
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
    for q_no in [6,8,9,22]:
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
        model=model_str,
        question_no=question_no,
        question_text=question_text
    )
    latency_ms = round((time.time() - start_time) * 1000)

    if not res:
        # Previously this recorded a fabricated predicted_score of 0.0 for a failed API
        # call, which silently gets included in ICC/MAE/bias computations as if it were
        # a real (very wrong) grade -- exactly the kind of corrupted data point that cost
        # a real Q22 response a -6 error. Use NaN instead: compute_metrics() already
        # calls dropna() on predicted_score/human_score, so a failed call is correctly
        # excluded from the statistics rather than silently poisoning them.
        return {"overall_score": None, "reasoning": "Model call failed after all retries -- excluded from metrics."}, float("nan"), 0, 0, 0.0, latency_ms

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
def _q22_mode_tag(q22_mode: str) -> str:
    """Canonical uppercase tag for a Q22 grading mode, used in filenames and result rows."""
    return {"rubric_semantic": "RUBRIC_SEMANTIC"}.get(q22_mode, "V8")


def run_single_model(model_key, df_questions, df_sample, q22_mode="v8"):
    model_info = MODELS[model_key]
    model_name = model_info["name"]
    file_tag = model_info["file_tag"]
    mode_tag = _q22_mode_tag(q22_mode)

    print("\n" + "="*80)
    print(f"🚀 EVALUATING MODEL {model_key}: {model_name} [Q22 mode: {mode_tag}] (100 responses: 25 per Question)")
    print("="*80)

    # Mode-tagged filenames so different Q22 grading policies can NEVER collide via the
    # checkpoint/resume logic below -- previously "v8" and "rubric_semantic" runs would
    # both write to the same results_<tag>.csv, so re-running with a different
    # Q22_GRADING_MODE silently skipped every response already present in that file
    # (the checkpoint saw a matching response_id/question_no and reused the OLD mode's
    # score instead of re-grading). "v8" keeps the original bare filename for backward
    # compatibility with earlier runs/analysis; every other mode gets its own file.
    if q22_mode == "v8":
        csv_file = os.path.join(script_dir, f"results_{file_tag}.csv")
        excel_file = os.path.join(script_dir, f"results_{file_tag}.xlsx")
    else:
        csv_file = os.path.join(script_dir, f"results_{mode_tag}_{file_tag}.csv")
        excel_file = os.path.join(script_dir, f"results_{mode_tag}_{file_tag}.xlsx")

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
            "q22_mode": mode_tag if q_no == "22" else "",
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


# ---------------------------------------------------------
# DYNAMIC RUBRIC-INTERPRETER ARCHITECTURE (question-type routing, not
# question-number routing -- see llm_service.py's grade_with_dynamic_rubric_interpreter
# module comment for the full rationale)
# ---------------------------------------------------------
def run_single_model_dynamic(model_key, df_questions, df_sample):
    """
    Grades every response in df_sample using ONLY the dynamic rubric-interpreter
    path (interpret_rubric_spec + grade_with_spec) -- never call_primary_grading_agent,
    never the hardcoded _Q6/_Q8/_Q9/_Q22_* constants, never question-number routing.
    This is the function to use to answer "does the dynamic architecture reproduce
    the existing hardcoded ICCs on Q6/Q8/Q9/Q22 without seeing their identities."

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
        print(f"\n  --- Interpreting rubric for Q{q_no_raw} ({len(q_group)} responses) ---")
        interp_start = time.time()
        spec = interpret_rubric_spec(question_text, rubric_text, max_score, model=model_str)
        interp_latency_ms = round((time.time() - interp_start) * 1000)
        if spec:
            print(f"  ✅ Q{q_no_raw} classified as: {spec.get('question_type')} "
                  f"(interpreter took {interp_latency_ms}ms)")
            for rf in spec.get("_review_flags", []):
                print(f"     ⚠️ REVIEW FLAG: {rf}")
        else:
            print(f"  ❌ Q{q_no_raw}: Rubric Interpreter failed or produced an invalid specification -- "
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
def run_q22_batch_session_experiment(model_key, df_questions, df_sample, q22_mode="v8"):
    """
    Grades every Q22 response in df_sample inside ONE continuous conversation via
    grade_q22_batch_session(), instead of run_single_model's N independent stateless
    calls. Tests whether cohort-relative calibration -- not criterion wording -- is
    what's capped Q22 ICC at ~0.5 across every per-response architecture (v4-v8) so
    far. See grade_q22_batch_session's docstring in llm_service.py for the full
    rationale (two externally-cited reference prompts reportedly hitting ~0.7 ICC
    both grade a full batch in one session rather than response-by-response).

    `q22_mode`: "v8" (default, engineered S1-S8/N1-N3 specs) or "rubric_semantic"
    (grades directly from the lecturer's literal numbered rubric bullets, no
    engineered boundary examples, and explicitly refuses to credit a fact the
    student never stated). Both modes are saved to differently-named files so
    results are kept side by side for comparison.

    Saves to a distinctly-named results file (results_Q22_BATCH_SESSION_<mode>_
    <tag>.csv/xlsx) so it never collides or checkpoint-merges with the existing
    per-response results for the same model. No checkpoint/resume here -- a
    batch session can't be cleanly resumed mid-conversation, and at N=15 a full
    re-run is cheap.
    """
    model_info = MODELS[model_key]
    model_name = model_info["name"]
    file_tag = model_info["file_tag"]
    model_str = model_info["model_str"]
    mode_tag = _q22_mode_tag(q22_mode)

    q22_df = df_sample[df_sample['question_no'].astype(str).str.strip().str.replace('Q', '') == "22"].copy()
    if q22_df.empty:
        print(f"⚠️ No Q22 responses found in the sampled dataset for {model_name}.")
        return pd.DataFrame()

    matched_q = df_questions[df_questions['question_no'].astype(str).str.strip().str.replace('Q', '') == "22"]
    if matched_q.empty:
        print("⚠️ No Q22 entry found in the question/answer scheme sheet.")
        return pd.DataFrame()
    q_row = matched_q.iloc[0]
    question_text = q_row['question']
    max_score = float(q_row['max_mark'])

    print("\n" + "="*80)
    print(f"🚀 Q22 BATCH-SESSION EXPERIMENT [{mode_tag}]: {model_name} ({len(q22_df)} responses, ONE continuous conversation)")
    print("="*80)

    responses = []
    human_scores = {}
    student_texts = {}
    for _, row in q22_df.iterrows():
        resp_id = str(row['ID Number'])
        ans_text = str(row['Response']).strip() if pd.notna(row['Response']) else ""
        if not ans_text or ans_text.lower() in ["-", "n/a", "none", "nan"]:
            ans_text = "(blank response)"
        responses.append({"id": resp_id, "student_text": ans_text})
        human_scores[resp_id] = float(row['grade'])
        student_texts[resp_id] = ans_text

    start_time = time.time()
    batch_results = grade_q22_batch_session(responses, question_text, model_str, refresh_every=15, mode=q22_mode)
    total_latency_ms = round((time.time() - start_time) * 1000)
    avg_latency_ms = round(total_latency_ms / max(1, len(batch_results)))

    results = []
    for res in batch_results:
        resp_id = res["id"]
        human_score = human_scores.get(resp_id, float("nan"))
        if res.get("status") == "failed" or res.get("overall_score") is None:
            score = float("nan")
        else:
            score = max(0.0, min(max_score, float(res.get("overall_score", 0.0))))

        results.append({
            "response_id": resp_id,
            "question_no": "Q22",
            "human_score": human_score,
            "predicted_score": score,
            "max_score": max_score,
            "absolute_error": round(abs(score - human_score), 2) if pd.notna(score) else None,
            "difference (AI - Human)": round(score - human_score, 2) if pd.notna(score) else None,
            "latency_ms": avg_latency_ms,
            "student_answer": student_texts.get(resp_id, ""),
            "reasoning": str(res.get("reasoning", "")),
            "raw_json": json.dumps(res, ensure_ascii=False),
        })

    df_batch_res = pd.DataFrame(results)
    csv_file = os.path.join(script_dir, f"results_Q22_BATCH_SESSION_{mode_tag}_{file_tag}.csv")
    excel_file = os.path.join(script_dir, f"results_Q22_BATCH_SESSION_{mode_tag}_{file_tag}.xlsx")
    df_batch_res.to_csv(csv_file, index=False)

    metrics = compute_metrics(df_batch_res)
    if not metrics:
        # compute_metrics() returns {} whenever fewer than 3 rows have BOTH a valid
        # predicted_score and human_score (e.g. several API calls failed mid-session).
        # pd.DataFrame([{}]) previously turned that into a Metrics sheet with ZERO
        # columns -- a blank sheet, not even a visible 0.0 -- which is why the ICC
        # value went missing from the spreadsheet instead of just reading as N/A.
        valid_n = df_batch_res.dropna(subset=["predicted_score", "human_score"]).shape[0] if not df_batch_res.empty else 0
        print(f"⚠️ Only {valid_n}/{len(df_batch_res)} responses had a valid score -- not enough to compute ICC/MAE. Check raw_json for failed calls.")
        metrics = {
            "N": valid_n, "ICC": float("nan"), "MAE": float("nan"), "Normalized_MAE_Pct": float("nan"),
            "Mean_Error": float("nan"), "Pearson_r": float("nan"), "Spearman_rho": float("nan"),
            "Exact_Match_Pct": float("nan"), "Within_1_Mark_Pct": float("nan"),
        }

    print(
        f"\n🎯 Q22 BATCH-SESSION [{mode_tag}] for {model_name}: "
        f"ICC(A,1) = {metrics.get('ICC')} | MAE = {metrics.get('MAE')} | "
        f"Bias = {metrics.get('Mean_Error')} | Pearson r = {metrics.get('Pearson_r')} | "
        f"Spearman ρ = {metrics.get('Spearman_rho')} | N = {metrics.get('N')}"
    )
    print(f"   (compare against results_Q22_BATCH_SESSION_V8_{file_tag}.csv / results_{file_tag}.csv Q22 rows)")

    run_time_s = round(total_latency_ms / 1000.0, 1)
    summary_row = {
        "Question": f"Q22 (BATCH-SESSION, {mode_tag})",
        "Max Mark": max_score,
        "Sample Size (N)": metrics.get("N", 0),
        "ICC (A,1)": metrics.get("ICC", float("nan")),
        "MAE": metrics.get("MAE", float("nan")),
        "Normalized MAE (%)": f"{metrics.get('Normalized_MAE_Pct', 0.0)}%",
        "Mean Error (Bias)": metrics.get("Mean_Error", float("nan")),
        "Exact Match (%)": f"{metrics.get('Exact_Match_Pct', 0.0)}%",
        "±1 Mark (%)": f"{metrics.get('Within_1_Mark_Pct', 0.0)}%",
        "Pearson r": metrics.get("Pearson_r", float("nan")),
        "Spearman ρ": metrics.get("Spearman_rho", float("nan")),
        "Total Run Time": f"{int(run_time_s // 60)}m {int(run_time_s % 60)}s",
    }
    df_summary = pd.DataFrame([summary_row])

    try:
        with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
            # Summary sheet written FIRST so it's the tab Excel opens by default --
            # previously the raw per-response sheet was first and Metrics was easy
            # to miss even on the runs where it did populate correctly.
            df_summary.to_excel(writer, sheet_name="Summary_Metrics", index=False)
            df_batch_res.to_excel(writer, sheet_name="Q22_Batch_Session", index=False)
    except Exception as e:
        print(f"  ⚠️ Warning saving batch-session Excel: {e}")

    return df_batch_res


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
def generate_master_comparison(q22_mode="v8"):
    """Builds side-by-side comparative Excel across all evaluated models."""
    mode_tag = _q22_mode_tag(q22_mode)
    print("\n" + "="*80)
    print(f"📊 GENERATING MASTER MODEL COMPARISON EXCEL [Q22 mode: {mode_tag}]...")
    print("="*80)

    master_excel = os.path.join(
        script_dir,
        "Model_Comparison_Master.xlsx" if q22_mode == "v8" else f"Model_Comparison_Master_{mode_tag}.xlsx",
    )
    model_data = {}

    for m_key, m_info in MODELS.items():
        # Match the same mode-tagged filename run_single_model() wrote to -- see its
        # docstring comment for why "v8" keeps the bare filename and other modes don't.
        fname = f"results_{m_info['file_tag']}.csv" if q22_mode == "v8" else f"results_{mode_tag}_{m_info['file_tag']}.csv"
        csv_file = os.path.join(script_dir, fname)
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


def generate_master_comparison_dynamic():
    """
    Same idea as generate_master_comparison(), but reads the results_DYNAMIC_<tag>.csv
    files (dynamic rubric-interpreter architecture) and breaks metrics down by
    question_no AND question_type, so you can directly compare e.g. Q6's dynamic-path
    ICC against Q6's existing hardcoded-path ICC in results_Gemini_3.1_Flash_Lite.csv.
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
    parser = argparse.ArgumentParser(description="Evaluate models individually and generate Excel reports.")
    parser.add_argument("--model", type=str, choices=["A", "B", "C", "all"], default="all",
                        help="Choose 'A' (Gemini 3.1 Flash Lite), 'B' (Nemotron 3 Super 120B), 'C' (Claude 4.6 Sonnet), or 'all'.")
    parser.add_argument("--batch-session", action="store_true",
                        help="Run the Q22 BATCH-SESSION experiment (grades all Q22 responses in one "
                             "continuous conversation instead of independent per-response calls) "
                             "instead of the normal per-response run. Saves to "
                             "results_Q22_BATCH_SESSION_<MODE>_<model>.csv/.xlsx and does not touch the "
                             "existing per-response results files.")
    parser.add_argument("--q22-mode", type=str, choices=["v8", "rubric_semantic"], default="v8",
                        help="Controls which Q22 grading policy is used, for BOTH the normal per-response "
                             "run and --batch-session (previously this only worked with --batch-session -- "
                             "a normal run always used v8 regardless of this flag, which is a bug that has "
                             "been fixed). 'v8' (default) uses the engineered S1-S8/N1-N3 specs. "
                             "'rubric_semantic' grades directly from the lecturer's literal numbered rubric "
                             "bullets with no engineered boundary examples, refusing to credit facts the "
                             "student never stated -- a controlled A/B arm on the exact same response set.")
    parser.add_argument("--architecture", type=str, choices=["legacy", "dynamic"], default="legacy",
                        help="'legacy' (default) uses call_primary_grading_agent() -- question-number "
                             "routing to the hardcoded _Q6/_Q8/_Q9/_Q22_* specialised templates, exactly "
                             "as every other flag in this script controls. 'dynamic' uses the Rubric "
                             "Interpreter architecture instead (interpret_rubric_spec + grade_with_spec) "
                             "-- question-TYPE routing with NO question-number checks and NO hardcoded "
                             "criteria/answer-key constants; the Grading Specification is extracted from "
                             "the raw question+rubric text at runtime. Ignores --batch-session and "
                             "--q22-mode (both are legacy-path-only concepts). Writes to "
                             "results_DYNAMIC_<model>.csv/.xlsx, entirely separate from every legacy file, "
                             "so this can be run on the SAME Q6/Q8/Q9/Q22 response set and compared "
                             "directly against the existing hardcoded-path results.")
    args = parser.parse_args()

    # Fixes the routing bug: call_primary_grading_agent() reads Q22_GRADING_MODE from the
    # environment for EVERY Q22 call (batch-session and normal per-response alike), but
    # nothing previously set this env var from --q22-mode outside the batch-session branch
    # below -- so a plain `run_experiment_suite.py --q22-mode rubric_semantic` silently
    # graded with the "v8" default the whole time. Setting it here, once, up front, makes
    # --q22-mode authoritative for both code paths.
    os.environ["Q22_GRADING_MODE"] = args.q22_mode

    print("Loading datasets...")
    df_questions, df_sample = get_stratified_dataset(samples_per_question=25, seed=42) #change number of scripts mark
    print(f"Sampled {len(df_sample)} student responses (25 per question across Q6, Q8, Q9, Q22).")

    if args.architecture == "dynamic":
        print("Architecture: DYNAMIC (Rubric Interpreter -- question-type routing, no question-number checks)")
        if args.model in ["A", "all"]:
            run_single_model_dynamic("A", df_questions, df_sample)
        if args.model in ["B", "all"]:
            run_single_model_dynamic("B", df_questions, df_sample)
        if args.model in ["C", "all"]:
            run_single_model_dynamic("C", df_questions, df_sample)
        generate_master_comparison_dynamic()
        return

    print(f"Q22 grading mode: {_q22_mode_tag(args.q22_mode)}")

    if args.batch_session:
        if args.model in ["A", "all"]:
            run_q22_batch_session_experiment("A", df_questions, df_sample, q22_mode=args.q22_mode)
        if args.model in ["B", "all"]:
            run_q22_batch_session_experiment("B", df_questions, df_sample, q22_mode=args.q22_mode)
        if args.model in ["C", "all"]:
            run_q22_batch_session_experiment("C", df_questions, df_sample, q22_mode=args.q22_mode)
        return

    if args.model in ["A", "all"]:
        run_single_model("A", df_questions, df_sample, q22_mode=args.q22_mode)
    if args.model in ["B", "all"]:
        run_single_model("B", df_questions, df_sample, q22_mode=args.q22_mode)
    if args.model in ["C", "all"]:
        run_single_model("C", df_questions, df_sample, q22_mode=args.q22_mode)

    generate_master_comparison(q22_mode=args.q22_mode)

if __name__ == "__main__":
    main()
