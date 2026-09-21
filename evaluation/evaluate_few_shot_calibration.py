#!/usr/bin/env python3
"""
Few-Shot Calibration Empirical Evaluation Experiment
====================================================
Controlled experiment comparing Zero-Shot vs 1-Shot vs 3-Shot vs 5-Shot grading.

Scientific Methodology:
1. Strict Control of Randomness:
   - Same held-out evaluation dataset (never includes calibration pool exemplars).
   - Same LLM model (google/gemini-3.1-flash-lite).
   - Same generation parameters (temperature = 0.0 for deterministic outputs).
   - Same base rubric and prompt template.
   - Question-matched exemplar injection only.
2. Metrics Computed:
   - ICC(A,1): Two-way random effects, absolute agreement intraclass correlation.
   - MAE: Mean Absolute Error between Human and AI marks.
   - Bias (Mean Error): Mean signed difference (AI - Human).
   - ≥ 1-Mark Discrepancy Rate (%): Proportion of grades differing by 1.0 or more.
   - Exact Agreement Rate (%): Proportion of grades exactly matching human marks.
3. Export:
   - Comprehensive multi-sheet Excel summary report:
     - Comparison_Metrics (summary comparison table across shots)
     - Per_Student_Detailed (item-level score deltas)
     - Calibration_Pool (documented exemplars and anchor classifications)
"""

import os
import re
import sys
import json
import time
import argparse
import pandas as pd
import pingouin as pg
from dotenv import load_dotenv

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Paths
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(script_dir, "../backend"))
sys.path.append(backend_dir)

# Load environment variables
load_dotenv(dotenv_path=os.path.join(script_dir, ".env"))

DEFAULT_MODEL = "google/gemini-3.1-flash-lite"

# =============================================================================
# FIXED CALIBRATION EXEMPLARS POOL (NEVER INCLUDED IN HELD-OUT TEST DATASET)
# =============================================================================
# 5 distinct exemplars per question with examiner anchor classification
CALIBRATION_POOLS = {
    "6": [
        {
            "id": 31107125,
            "anchor_type": "high",
            "score": 9.0,
            "max_score": 10.0,
            "text": "a) Advantages - drug encapsulated within the spheres can slowly degrade over time to give sustained drug release, improving patient compliance by reducing dosing frequency. Biodegradable polymers degrade harmlessly. Disadvantages - burst release where a large amount of drug is released immediately, and risk of localized tissue irritation.",
            "justification": "Comprehensive coverage of sustained release kinetics, compliance benefits, biodegradable breakdown, and burst release risk. Full marks on 4 distinct rubric criteria."
        },
        {
            "id": 31107990,
            "anchor_type": "high",
            "score": 8.0,
            "max_score": 10.0,
            "text": "(a) Advantages: - The polymer will slowly degrade over a period of time to release the drug slowly. This helps avoid frequent dosing and maintains constant therapeutic plasma levels. Disadvantages: - Preparation requires organic solvents which might be toxic. Burst release effect may cause drug toxicity.",
            "justification": "Clear explanation of controlled release and formulation toxicity risks. Minor omission regarding degradation acidic microenvironment."
        },
        {
            "id": 30881447,
            "anchor_type": "borderline",
            "score": 5.0,
            "max_score": 10.0,
            "text": "(a) Advantages: * Prolonged the plasma half-lives which improve the patient compliance * Target specific site of action. Disadvantages: * High manufacturing cost * Difficult to manufacture.",
            "justification": "Identified half-life prolongation and patient compliance (3 pts), but cited generic manufacturing cost rather than polymer-specific pharmacology challenges like burst release or stability (2 pts deducted)."
        },
        {
            "id": 30897254,
            "anchor_type": "borderline",
            "score": 5.0,
            "max_score": 10.0,
            "text": "(a) advantages - polymer microspheres is it is degradable and it will break down in the body without surgical removal. Disadvantage is it may trigger immune response if foreign material is detected.",
            "justification": "Correctly notes biodegradable avoidance of surgery, but discussion of release kinetics is superficial and disadvantages lack mention of burst release or acidic microenvironment."
        },
        {
            "id": 30883350,
            "anchor_type": "low",
            "score": 2.0,
            "max_score": 10.0,
            "text": "(a) Advantages: - particle size reduction for enhancing solubility - provide coating protection. Disadvantages: - hard to swallow tablets.",
            "justification": "Demonstrates fundamental misconception confusing microsphere drug delivery systems with oral tablet micronization. Only awarded minimal courtesy marks for general protection mention."
        }
    ],
    "8": [
        {
            "id": 31920918,
            "anchor_type": "high",
            "score": 9.0,
            "max_score": 10.0,
            "text": "(a) Disagree, they also come as a prefilled syringe (solution form) in the case of fast acting peptides, or suspensions. Lyophilisation is used when aqueous stability is poor. (b) Agree, peptides have higher molecular weight and tertiary structures prone to denaturation and aggregation during freezing and drying stresses, requiring cryoprotectants.",
            "justification": "Directly refutes the false absolute statement with clinical alternatives (prefilled solutions) and details protein freezing/drying physical instability mechanisms."
        },
        {
            "id": 31508073,
            "anchor_type": "high",
            "score": 8.0,
            "max_score": 10.0,
            "text": "a) Disagree. The peptide can also be prepared in a solution form for injectable drugs if refrigerated stability is sufficient. b) Agree. Peptides are complex proteins that easily degrade, aggregate, or unfold during temperature changes and drying stresses.",
            "justification": "Correct disagreement with valid solution alternative. Solid mechanical explanation of peptide denaturation under freezing stresses."
        },
        {
            "id": 30720842,
            "anchor_type": "borderline",
            "score": 6.0,
            "max_score": 10.0,
            "text": "(A) LYOPHILIZATION IS NOT THE ONLY OPTION. Peptides can be stored in liquid form with preservatives or frozen solutions. (B) Peptides are sensitive to heat and moisture so freeze drying removes water.",
            "justification": "Part (a) correctly disagrees and provides liquid option (4 pts). Part (b) is brief and misses specific cold denaturation / aggregation mechanics (2 pts partial credit)."
        },
        {
            "id": 30884772,
            "anchor_type": "borderline",
            "score": 5.0,
            "max_score": 10.0,
            "text": "a) Agree. They are prepared as lyophilized solid powder products in a vial as it ensures stability. b) Agree, proteins can easily denature and lose their 3D confirmation during processing.",
            "justification": "Fell into part (a) trap by agreeing lyophilization is the ONLY option (0/5 for part a). Part (b) correctly explains 3D conformational denaturation (5/5 for part b)."
        },
        {
            "id": 30897254,
            "anchor_type": "low",
            "score": 1.0,
            "max_score": 10.0,
            "text": "(a) agree because lyophilisation improves long time stability of peptides by reducing moisture content. (b) disagree because proteins are very tough molecules.",
            "justification": "Severe misconception stating proteins are tough molecules resistant to stress. Misses part (a) absolute trap and demonstrates flawed pharmacology rationale."
        }
    ]
}


def build_calibration_block(question_no: str, num_shots: int) -> str:
    """
    Retrieves fixed calibration exemplars for the question and formats them.
    0-shot: Empty string.
    1-shot: 1 Borderline anchor.
    3-shot: 1 High, 1 Borderline, 1 Low anchor.
    5-shot: All 5 exemplars (2 High, 2 Borderline, 1 Low).
    """
    clean_q = str(question_no).strip().replace("Q", "")
    pool = CALIBRATION_POOLS.get(clean_q, [])
    if not pool or num_shots <= 0:
        return ""

    if num_shots == 1:
        # Select 1 Borderline exemplar
        selected = [ex for ex in pool if ex["anchor_type"] == "borderline"][:1]
    elif num_shots == 3:
        # Select 1 High, 1 Borderline, 1 Low
        high = [ex for ex in pool if ex["anchor_type"] == "high"][:1]
        mid = [ex for ex in pool if ex["anchor_type"] == "borderline"][:1]
        low = [ex for ex in pool if ex["anchor_type"] == "low"][:1]
        selected = high + mid + low
    else:
        # 5-shot: All 5 exemplars
        selected = pool[:num_shots]

    blocks = []
    for idx, ex in enumerate(selected, 1):
        anchor_title = ex["anchor_type"].capitalize()
        blocks.append(
            f"  [Examiner Benchmark {idx} ({anchor_title} Anchor) — Score: {ex['score']}/{ex['max_score']}]\n"
            f"  Student Response: \"{ex['text']}\"\n"
            f"  Examiner Rubric Justification: \"{ex['justification']}\""
        )

    return (
        f"\n### EXAMINER CALIBRATION BENCHMARKS (QUESTION Q{clean_q})\n"
        f"The course examiner has established the following {len(selected)} response(s) as the official few-shot benchmark for marking strictness and partial-credit thresholds:\n\n"
        + "\n\n".join(blocks)
        + "\n"
    )


def format_evaluation_prompt(question_text: str, rubric_text: str, max_score: float, student_answer: str, cal_block: str) -> str:
    """Constructs the exact Chain-of-Thought grading prompt."""
    prompt = f"""### ROLE
You are an expert academic evaluator specializing in objective short-answer grading.
Your task is to evaluate the student response against the rubric accurately, objectively, and consistently.

### CONTEXT
Question: {question_text}
Max Score: {max_score}
Rubric: {rubric_text}
{cal_block}
### GRADING PROTOCOL
1. OBJECTIVE STANDARDS: Match student meaning and technical concepts to the rubric criteria.
2. FEW-SHOT ALIGNMENT: If examiner calibration benchmarks are provided above, strictly adhere to their partial-credit boundaries and marking strictness.
3. STRICT CAPPING: Do not award more than the maximum allocated marks for any criterion or for the total question ({max_score}).
4. REASONING FIRST: Evaluate each criterion step-by-step before finalizing the score.

### STUDENT ANSWER
{student_answer}

### REQUIRED OUTPUT FORMAT
You must return your evaluation STRICTLY as a valid JSON object. Do NOT wrap in markdown blocks or include extra commentary text.
{{
  "reasoning": "Step-by-step breakdown of how the student answer maps to the rubric and matches calibration anchors.",
  "criteria_breakdown": [
    {{
      "criterion": "Name or concept from rubric",
      "evidence": "Exact quote or 'None'",
      "score": 0.0
    }}
  ],
  "feedback": "Concise feedback for the student.",
  "total_score": 0.0
}}"""
    return prompt


def extract_score_from_response(raw_text: str, max_score: float) -> float:
    """Safely extracts total_score from LLM response."""
    if not raw_text:
        return 0.0
    clean = raw_text.strip()
    # Strip think tags if present
    clean = re.sub(r"<think>.*?</think>", "", clean, flags=re.DOTALL).strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    if clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()

    start_idx = clean.find("{")
    end_idx = clean.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        clean = clean[start_idx:end_idx + 1]

    try:
        data = json.loads(clean)
        score = data.get("total_score")
        if score is None:
            score = data.get("overall_score")
        if score is None:
            score = data.get("score", 0.0)
        return round(max(0.0, min(max_score, float(score))), 2)
    except Exception:
        # Fallback regex search for total_score
        m = re.search(r'"total_score"\s*:\s*([0-9\.]+)', raw_text)
        if m:
            return round(max(0.0, min(max_score, float(m.group(1)))), 2)
        return 0.0


def call_llm(client, model: str, prompt: str, max_retries: int = 3) -> str:
    """Calls OpenRouter LLM deterministically at temperature=0.0."""
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a precise academic grading assistant. Always respond strictly in valid JSON format."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,  # CRITICAL: strictly deterministic
                max_tokens=2000
            )
            content = resp.choices[0].message.content
            if content:
                return content
            time.sleep(1)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"    [API Error] Failed call after {max_retries} attempts: {e}")
                return ""
    return ""


def calculate_metrics(df_sub: pd.DataFrame, human_col: str, ai_col: str) -> dict:
    """Computes ICC(A,1), MAE, Bias, Discrepancy Rate, and Exact Match Rate."""
    clean = df_sub.dropna(subset=[human_col, ai_col]).copy()
    n = len(clean)
    if n == 0:
        return {"N": 0, "ICC": float("nan"), "MAE": 0.0, "Discrepancy_Pct": 0.0, "Exact_Pct": 0.0}

    deltas = (clean[ai_col] - clean[human_col]).abs()
    mae = float(deltas.mean())
    bias = float((clean[ai_col] - clean[human_col]).mean())
    discrepancy_1plus = float((deltas >= 1.0).sum() / n * 100.0)
    exact_match = float((deltas == 0.0).sum() / n * 100.0)
    within_half = float((deltas <= 0.5).sum() / n * 100.0)

    # ICC(A,1) computation via pingouin
    try:
        targets = [f"item_{i}" for i in range(n)]
        icc_df = pd.concat([
            pd.DataFrame({"target": targets, "rater": "Human", "rating": clean[human_col]}),
            pd.DataFrame({"target": targets, "rater": "AI", "rating": clean[ai_col]})
        ], ignore_index=True)
        res = pg.intraclass_corr(data=icc_df, targets="target", raters="rater", ratings="rating")
        icc_val = float(res.set_index("Type").loc["ICC(A,1)", "ICC"])
    except Exception as e:
        icc_val = float("nan")

    return {
        "N": n,
        "ICC": round(icc_val, 3),
        "MAE": round(mae, 3),
        "Bias": round(bias, 3),
        "Discrepancy_ge1_pct": round(discrepancy_1plus, 1),
        "Exact_Match_pct": round(exact_match, 1),
        "Within_0.5_pct": round(within_half, 1)
    }


def run_experiment():
    parser = argparse.ArgumentParser(description="Empirical Few-Shot Calibration Evaluation")
    parser.add_argument("--sample-size", type=int, default=20, help="Number of held-out test responses per question (default 20)")
    parser.add_argument("--questions", type=str, default="6,8", help="Comma-separated questions to evaluate (default: 6,8)")
    parser.add_argument("--conditions", type=str, default="0,1,3,5", help="Few-shot conditions (default: 0,1,3,5)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"OpenRouter model string (default: {DEFAULT_MODEL})")
    parser.add_argument("--output", type=str, default=os.path.join(script_dir, "results_few_shot_calibration.xlsx"), help="Output Excel path")
    parser.add_argument("--dry-run", action="store_true", help="Inspect datasets without making API calls")
    args = parser.parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key and not args.dry_run:
        print("❌ Error: No OPENROUTER_API_KEY found in evaluation/.env")
        sys.exit(1)

    client = None
    if not args.dry_run:
        client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

    dataset_path = os.path.join(script_dir, "Dataset for prompt.xlsx")
    if not os.path.exists(dataset_path):
        print(f"❌ Error: Dataset file not found at {dataset_path}")
        sys.exit(1)

    print("=" * 80)
    print("  AutoGrade+ Few-Shot Calibration Controlled Benchmark")
    print(f"  Model: {args.model} | Temperature: 0.0 (Deterministic)")
    print(f"  Questions: {args.questions} | Sample Size Per Question: {args.sample_size}")
    print(f"  Conditions: {args.conditions}-shot")
    print("=" * 80)

    # 1. Load Dataset
    df_questions = pd.read_excel(dataset_path, sheet_name="Question & Answer Scheme")
    df_responses = pd.read_excel(dataset_path, sheet_name="Response")

    target_questions = [q.strip().replace("Q", "") for q in args.questions.split(",")]
    conditions = [int(c.strip()) for c in args.conditions.split(",")]

    # All calibration pool IDs across target questions to exclude from held-out set
    calibration_pool_ids = set()
    for q_no in target_questions:
        for ex in CALIBRATION_POOLS.get(q_no, []):
            calibration_pool_ids.add(ex["id"])

    print(f"🔒 Identified {len(calibration_pool_ids)} calibration pool exemplars across target questions.")
    print("   These exemplars are STRICTLY HELD OUT from test evaluation data.\n")

    # Filter responses: must match target questions AND NOT be in calibration pool
    clean_responses = df_responses.copy()
    clean_responses["clean_q"] = clean_responses["question_no"].astype(str).str.strip().str.replace("Q", "")
    clean_responses = clean_responses[clean_responses["clean_q"].isin(target_questions)]
    clean_responses = clean_responses[~clean_responses["ID Number"].isin(calibration_pool_ids)]

    # Take deterministic fixed sample per question
    sampled_test_rows = []
    for q_no in target_questions:
        q_subset = clean_responses[clean_responses["clean_q"] == q_no].copy()
        if args.sample_size and len(q_subset) > args.sample_size:
            q_subset = q_subset.head(args.sample_size)
        sampled_test_rows.append(q_subset)

    df_test_set = pd.concat(sampled_test_rows, ignore_index=True)
    print(f"📊 Fixed Held-Out Test Set Created: {len(df_test_set)} total student responses.")
    for q_no in target_questions:
        count = len(df_test_set[df_test_set["clean_q"] == q_no])
        print(f"   - Question {q_no}: {count} held-out responses")

    if args.dry_run:
        print("\n[DRY RUN] Verifying prompt construction and calibration pool integrity:")
        for q_no in target_questions:
            q_meta = df_questions[df_questions["question_no"].astype(str).str.strip().str.replace("Q", "") == q_no].iloc[0]
            for num_shots in conditions:
                cal_b = build_calibration_block(q_no, num_shots)
                print(f"\n--- Question Q{q_no} ({num_shots}-Shot Prompt Preview) ---")
                preview = format_evaluation_prompt(q_meta["question"], q_meta["answer"], float(q_meta["max_mark"]), "[SAMPLE RESPONSE]", cal_b)
                print(preview[:400] + "\n...[TRUNCATED]...")
        print("\n✅ Dry run verification complete. Exiting without making API calls.")
        return

    # Cache file to support safe resumption
    cache_csv = os.path.join(script_dir, "raw_few_shot_calibration_results.csv")
    existing_records = []
    cached_keys = set()
    if os.path.exists(cache_csv):
        try:
            cached_df = pd.read_csv(cache_csv)
            existing_records = cached_df.to_dict("records")
            for r in existing_records:
                cached_keys.add(f"{r['ID Number']}_{r['question_no']}_{r['shots']}")
            print(f"🔁 Loaded {len(existing_records)} cached evaluations from {os.path.basename(cache_csv)}")
        except Exception as e:
            print(f"⚠️ Could not load cache: {e}")

    # 2. Execution Loop
    results = list(existing_records)
    total_calls = len(df_test_set) * len(conditions)
    current_call = len(cached_keys)

    print(f"\n🚀 Starting Controlled Evaluation ({total_calls} total evaluations)...")

    for idx, row in df_test_set.iterrows():
        resp_id = row["ID Number"]
        q_no = row["clean_q"]
        stu_ans = str(row["Response "]).strip() if pd.notna(row["Response "]) else ""
        human_mark = float(row["grade"])

        # Fetch question metadata
        q_match = df_questions[df_questions["question_no"].astype(str).str.strip().str.replace("Q", "") == q_no]
        if q_match.empty:
            continue
        q_meta = q_match.iloc[0]
        q_text = str(q_meta["question"])
        rubric_text = str(q_meta["answer"])
        max_score = float(q_meta["max_mark"])

        for num_shots in conditions:
            cache_key = f"{resp_id}_{q_no}_{num_shots}"
            if cache_key in cached_keys:
                continue

            current_call += 1
            print(f"[{current_call}/{total_calls}] Q{q_no} | ID: {resp_id} | {num_shots}-Shot | Human: {human_mark}/{max_score}...", end="", flush=True)

            # Handle blank submission
            if not stu_ans or stu_ans in ["-", "N/A", "none", "nan"]:
                ai_score = 0.0
                raw_out = '{"total_score": 0.0, "reasoning": "Blank response"}'
                print(f" -> Blank (0.0)")
            else:
                cal_block = build_calibration_block(q_no, num_shots)
                prompt = format_evaluation_prompt(q_text, rubric_text, max_score, stu_ans, cal_block)
                t0 = time.time()
                raw_out = call_llm(client, args.model, prompt)
                dur = round(time.time() - t0, 2)
                ai_score = extract_score_from_response(raw_out, max_score)
                delta = round(ai_score - human_mark, 2)
                print(f" -> AI: {ai_score} (Δ: {delta:+} in {dur}s)")

            rec = {
                "ID Number": resp_id,
                "question_no": f"Q{q_no}",
                "student_answer": stu_ans,
                "human_grade": human_mark,
                "max_score": max_score,
                "shots": num_shots,
                "condition": f"{num_shots}-Shot",
                "ai_grade": ai_score,
                "error_delta": round(ai_score - human_mark, 2),
                "absolute_error": round(abs(ai_score - human_mark), 2),
                "discrepancy_ge1": bool(abs(ai_score - human_mark) >= 1.0),
                "exact_match": bool(abs(ai_score - human_mark) == 0.0),
                "model": args.model
            }
            results.append(rec)
            cached_keys.add(cache_key)

            # Persist incrementally
            pd.DataFrame(results).to_csv(cache_csv, index=False)

    print("\n✅ All evaluations completed successfully. Computing benchmark metrics...")

    # 3. Compute Metrics
    df_all_results = pd.DataFrame(results)

    summary_rows = []
    # Compute per-question metrics
    for q_no in target_questions:
        q_tag = f"Q{q_no}"
        q_data = df_all_results[df_all_results["question_no"] == q_tag]
        for num_shots in conditions:
            cond_data = q_data[q_data["shots"] == num_shots]
            m = calculate_metrics(cond_data, "human_grade", "ai_grade")
            summary_rows.append({
                "Question": q_tag,
                "Condition": f"{num_shots}-Shot",
                "Shots": num_shots,
                "N": m["N"],
                "ICC(A,1)": m["ICC"],
                "MAE": m["MAE"],
                "Bias (AI - Human)": m["Bias"],
                "≥ 1-Mark Discrepancy (%)": m["Discrepancy_ge1_pct"],
                "Exact Match (%)": m["Exact_Match_pct"],
                "Within 0.5 Mark (%)": m["Within_0.5_pct"]
            })

    # Compute aggregate (overall) metrics
    for num_shots in conditions:
        cond_data = df_all_results[df_all_results["shots"] == num_shots]
        m = calculate_metrics(cond_data, "human_grade", "ai_grade")
        summary_rows.append({
            "Question": "Overall (All Evaluated)",
            "Condition": f"{num_shots}-Shot",
            "Shots": num_shots,
            "N": m["N"],
            "ICC(A,1)": m["ICC"],
            "MAE": m["MAE"],
            "Bias (AI - Human)": m["Bias"],
            "≥ 1-Mark Discrepancy (%)": m["Discrepancy_ge1_pct"],
            "Exact Match (%)": m["Exact_Match_pct"],
            "Within 0.5 Mark (%)": m["Within_0.5_pct"]
        })

    df_summary = pd.DataFrame(summary_rows)

    # 4. Print Summary Table
    print("\n" + "=" * 95)
    print("                    FEW-SHOT CALIBRATION BENCHMARK RESULTS")
    print("=" * 95)
    print(df_summary.to_string(index=False))
    print("=" * 95)

    # 5. Build Detailed Student Pivot View
    pivot_scores = df_all_results.pivot_table(
        index=["ID Number", "question_no", "human_grade", "max_score"],
        columns="condition",
        values="ai_grade"
    ).reset_index()

    # 6. Build Calibration Exemplars Table
    cal_exemplar_rows = []
    for q_no, exemplars in CALIBRATION_POOLS.items():
        if q_no in target_questions:
            for ex in exemplars:
                cal_exemplar_rows.append({
                    "Question": f"Q{q_no}",
                    "Student_ID": ex["id"],
                    "Anchor_Classification": ex["anchor_type"].capitalize(),
                    "Score_Awarded": ex["score"],
                    "Max_Score": ex["max_score"],
                    "Representative_Student_Response": ex["text"],
                    "Examiner_Rubric_Rationale": ex["justification"]
                })
    df_cal_exemplars = pd.DataFrame(cal_exemplar_rows)

    # 7. Write Multi-Sheet Excel
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="Comparison_Metrics", index=False)
        pivot_scores.to_excel(writer, sheet_name="Per_Student_Grades", index=False)
        df_all_results.to_excel(writer, sheet_name="Raw_Evaluations", index=False)
        df_cal_exemplars.to_excel(writer, sheet_name="Calibration_Exemplars_Pool", index=False)

    print(f"\n📁 Benchmark report successfully exported to:")
    print(f"   {args.output}")


if __name__ == "__main__":
    run_experiment()
