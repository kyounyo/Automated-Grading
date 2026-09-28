import os
import re
import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import time
import pandas as pd
import pingouin as pg
from dotenv import load_dotenv

# Path setup
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(script_dir, "../backend"))
sys.path.append(backend_dir)

# Load environment variables
load_dotenv(dotenv_path=os.path.join(script_dir, ".env"))

# Import exact backend agent & key helper
from app.services.llm_service import (
    call_primary_grading_agent,
    get_openrouter_api_key
)

if not get_openrouter_api_key():
    print("❌ Error: No OPENROUTER_API_KEY found in evaluation/.env")
    sys.exit(1)

# ---------------------------------------------------------
# KNOWN PRESET MODELS & PRICING (Matching Experiment 2)
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

def resolve_model(input_val: str):
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

def compute_metrics(df_clean, pred_col="ai_score", target_col="human_score"):
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
        "ICC": round(icc_val, 3),
        "MAE": round(mae, 3),
        "Mean_Error": round(mean_error, 3),
        "Pearson_r": round(pearson_r, 3),
        "Spearman_rho": round(spearman_rho, 3),
        "Exact_Match_Pct": round(exact_match, 1),
        "Within_1_Mark_Pct": round(within_1, 1)
    }

def run_open_ended_experiment_for_model(model_key="A", target_q="22", samples=25, seed=42, fresh=False):
    m_info = resolve_model(model_key)
    m_name = m_info["name"]
    m_str = m_info["model_str"]
    file_tag = m_info["file_tag"]

    print("\n" + "="*85)
    print(f"🚀 TESTING MODEL: {m_name} ({m_str}) [Question Q{target_q}]")
    print("="*85)

    dataset_path = os.path.join(script_dir, "Dataset for prompt.xlsx")
    df_questions = pd.read_excel(dataset_path, sheet_name="Question & Answer Scheme")
    df_responses = pd.read_excel(dataset_path, sheet_name="Response")
    df_questions.columns = df_questions.columns.str.strip()
    df_responses.columns = df_responses.columns.str.strip()

    q_subset = df_responses[df_responses['question_no'].astype(str).str.strip().str.replace('Q', '') == str(target_q)]
    df_sample = q_subset.sample(n=min(samples, len(q_subset)), random_state=seed).copy()

    matched_q = df_questions[df_questions['question_no'].astype(str).str.strip().str.replace('Q', '') == str(target_q)].iloc[0]
    rubric_text = matched_q['answer']
    max_score = float(matched_q['max_mark'])

    csv_file = os.path.join(script_dir, f"results_open_ended_{file_tag}_Q{target_q}.csv")
    
    results = []
    completed_ids = set()

    if fresh and os.path.exists(csv_file):
        os.remove(csv_file)
        print(f"🧹 Fresh run requested: Cleared previous checkpoint for {m_name}.")

    # Load checkpoint if exists (Matching run_experiment_suite.py pattern)
    if not fresh and os.path.exists(csv_file) and os.path.getsize(csv_file) > 0:
        try:
            prev_df = pd.read_csv(csv_file)
            results = prev_df.to_dict('records')
            completed_ids = set(str(r['response_id']) for r in results)
            print(f"🔄 Checkpoint: Loaded {len(completed_ids)} already evaluated responses for {m_name}.")
        except Exception:
            pass

    combined_guidelines = f"{rubric_text}\n\n{OPEN_ENDED_GRADING_RULES}"
    structured_rubric = {
        "structured_rules": [
            {
                "question_number": f"Q{target_q}",
                "max_score": max_score,
                "grading_guidelines": combined_guidelines
            }
        ]
    }
    raw_rubric_json = [{"question_number": f"Q{target_q}", "max_score": max_score, "criterion": combined_guidelines}]

    for idx, row in df_sample.iterrows():
        resp_id = str(row['ID Number'])
        if resp_id in completed_ids:
            continue

        human_grade = float(row['grade'])
        ans_text = str(row['Response']).strip() if pd.notna(row['Response']) else ""

        start_t = time.time()
        res = call_primary_grading_agent(
            student_text=ans_text,
            structured_rubric=structured_rubric,
            raw_rubric_json=raw_rubric_json,
            model_answer=rubric_text,
            rag_context="",
            total_max_score=max_score,
            model=m_str
        )

        latency_ms = round((time.time() - start_t) * 1000)
        ai_score = float(res.get("overall_score", 0.0)) if res else 0.0
        reasoning = str(res.get("reasoning", "")) if res else ""
        
        usage = res.get("_usage", {}) if res else {}
        in_tok = usage.get("prompt_tokens", 500)
        out_tok = usage.get("completion_tokens", 300)
        cost = (in_tok / 1000.0 * m_info["cost_per_1k_in"]) + (out_tok / 1000.0 * m_info["cost_per_1k_out"])

        rec = {
            "response_id": resp_id,
            "question_no": f"Q{target_q}",
            "human_score": human_grade,
            "ai_score": ai_score,
            "max_score": max_score,
            "absolute_error": round(abs(ai_score - human_grade), 2),
            "difference (AI - Human)": round(ai_score - human_grade, 2),
            "latency_ms": latency_ms,
            "cost_usd": round(cost, 6),
            "student_answer": ans_text,
            "reasoning": reasoning,
            "model_name": m_name,
            "model_str": m_str
        }
        results.append(rec)

        # Continuous CSV Checkpoint (Matching run_experiment_suite.py pattern)
        pd.DataFrame(results).to_csv(csv_file, index=False)
        print(f"   [Resp #{resp_id}] Human: {human_grade} | AI: {ai_score} | Time: {latency_ms/1000.0:.1f}s", flush=True)
        time.sleep(0.5)

    df_res = pd.DataFrame(results)
    metrics = compute_metrics(df_res, pred_col="ai_score")

    tot_time_s = round(df_res['latency_ms'].sum() / 1000.0, 1)
    avg_time_s = round(df_res['latency_ms'].mean() / 1000.0, 2)
    tot_cost = round(df_res['cost_usd'].sum(), 4)

    metrics["Model"] = m_name
    metrics["Model_String"] = m_str
    metrics["Avg_Time_per_Q_s"] = avg_time_s
    metrics["Total_Run_Time"] = f"{int(tot_time_s // 60)}m {int(tot_time_s % 60)}s"
    metrics["Total_Cost_25_Qs"] = f"${tot_cost}"

    return metrics, df_res

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark models on open-ended exam questions.")
    parser.add_argument("--model", type=str, choices=["A", "B", "C", "all", "a", "b", "c", "ALL"], default=None,
                        help="Choose model: 'A' (Gemini), 'B' (Nemotron), 'C' (Claude), or 'all'.")
    parser.add_argument("--question", type=str, choices=["22", "6", "both"], default="22",
                        help="Target question: '22', '6', or 'both'. Default: '22'.")
    parser.add_argument("--fresh", action="store_true",
                        help="Force a fresh run by ignoring previously saved CSV checkpoints.")
    args = parser.parse_args()

    selected_model = args.model
    is_fresh = args.fresh

    if not selected_model:
        if sys.stdin.isatty():
            print("\n" + "="*60)
            print("🤖 SELECT MODEL FOR OPEN-ENDED EVALUATION")
            print("="*60)
            print("  [A / 1] Gemini 3.1 Flash Lite")
            print("  [B / 2] Nemotron 3 Super 120B")
            print("  [C / 3] Claude 4.6 Sonnet")
            print("  [ALL / 4] Run All Models")
            print("="*60)
            try:
                user_choice = input("Enter choice (A/B/C/ALL) [Default: B]: ").strip().upper()
                if user_choice in ["1", "A"]:
                    selected_model = "A"
                elif user_choice in ["2", "B"]:
                    selected_model = "B"
                elif user_choice in ["3", "C"]:
                    selected_model = "C"
                elif user_choice in ["4", "ALL"]:
                    selected_model = "ALL"
                elif not user_choice:
                    selected_model = "B"
                else:
                    selected_model = user_choice

                fresh_choice = input("Force a fresh rerun (clear previous checkpoint)? (y/N) [Default: N]: ").strip().lower()
                if fresh_choice in ["y", "yes"]:
                    is_fresh = True
            except (KeyboardInterrupt, EOFError):
                print("\nOperation cancelled.")
                sys.exit(0)
        else:
            selected_model = "B"

    selected_model = selected_model.upper()
    models_to_run = ["A", "B", "C"] if selected_model == "ALL" else [selected_model]
    target_qs = ["6", "22"] if args.question == "both" else [args.question]

    print("="*85)
    print(f"🔬 OPEN-ENDED QUESTION MODEL BENCHMARK (Models: {', '.join(models_to_run)} | Questions: {', '.join(target_qs)})")
    print("="*85)

    all_metrics = []
    all_responses_df_list = []

    for m_key in models_to_run:
        model_dfs = []
        for q in target_qs:
            _, df_res = run_open_ended_experiment_for_model(model_key=m_key, target_q=q, samples=25, seed=42, fresh=is_fresh)
            model_dfs.append(df_res)
        
        combined_df = pd.concat(model_dfs, ignore_index=True)
        m_info = resolve_model(m_key)
        metrics = compute_metrics(combined_df, pred_col="ai_score")

        tot_time_s = round(combined_df['latency_ms'].sum() / 1000.0, 1)
        avg_time_s = round(combined_df['latency_ms'].mean() / 1000.0, 2)
        tot_cost = round(combined_df['cost_usd'].sum(), 4)

        metrics["Model"] = m_info["name"]
        metrics["Model_String"] = m_info["model_str"]
        metrics["Avg_Time_per_Q_s"] = avg_time_s
        metrics["Total_Run_Time"] = f"{int(tot_time_s // 60)}m {int(tot_time_s % 60)}s"
        metrics["Total_Cost"] = f"${tot_cost}"
        all_metrics.append(metrics)
        all_responses_df_list.append(combined_df)

    df_leaderboard = pd.DataFrame(all_metrics)
    cols = ["Model", "N", "ICC", "MAE", "Mean_Error", "Pearson_r", "Spearman_rho", "Exact_Match_Pct", "Within_1_Mark_Pct", "Avg_Time_per_Q_s", "Total_Run_Time", "Total_Cost"]
    df_leaderboard = df_leaderboard[cols].sort_values(by="ICC", ascending=False)

    print("\n" + "="*85)
    print(f"🏆 OPEN-ENDED MODEL BENCHMARK RESULTS")
    print("="*85)
    print(df_leaderboard.to_string(index=False))

    # Save Multi-Tab Master Excel (Matching run_experiment_suite.py pattern)
    out_excel = os.path.join(script_dir, "results_open_ended_model_benchmark.xlsx")
    try:
        with pd.ExcelWriter(out_excel, engine='openpyxl') as writer:
            df_leaderboard.to_excel(writer, sheet_name="Leaderboard_Summary", index=False)
            
            for df_res in all_responses_df_list:
                if not df_res.empty:
                    m_name_clean = re.sub(r'[^a-zA-Z0-9_-]', '_', df_res['model_name'].iloc[0])[:30]
                    df_res.to_excel(writer, sheet_name=f"{m_name_clean}_Q22", index=False)

        print(f"\n📊 Excel benchmark report saved to: {out_excel}")
    except Exception as e:
        print(f"  ⚠️ Warning saving Excel: {e}")

if __name__ == "__main__":
    main()
