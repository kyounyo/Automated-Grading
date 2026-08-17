import os
import re
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np

# Directory & CSV Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
EVAL_DIR = BASE_DIR / "evaluation"
DATASET_PATH = EVAL_DIR / "Dataset for prompt.xlsx"
COMPARISON_CSV_PATH = EVAL_DIR / "backend_score_comparison.csv"
ICC_RESULTS_CSV_PATH = EVAL_DIR / "backend_icc_results.csv"

_dataset_cache: Optional[Dict[str, Any]] = None
_dataset_mtime: float = 0.0


def normalize_student_id(s_id: Any) -> str:
    """Normalizes student ID by stripping whitespace and removing trailing .0 from floats."""
    if s_id is None:
        return ""
    val = str(s_id).strip()
    if val.endswith(".0"):
        val = val[:-2]
    return val


def extract_main_question_no(q_str: Any) -> str:
    """
    Extracts the main question number digits.
    e.g. 'Q6(a)' -> '6', 'Q8(a-e)' -> '8', 'Question 22' -> '22', '6' -> '6'
    """
    if q_str is None:
        return ""
    s = str(q_str).strip().upper()
    m = re.search(r'(?:QUESTION|Q)?\s*(\d+)', s, re.IGNORECASE)
    if m:
        return m.group(1)
    val = re.sub(r'^(?:QUESTION|Q)\s*', '', s, flags=re.IGNORECASE).strip()
    if val.endswith(".0"):
        val = val[:-2]
    return val


def load_benchmark_dataset() -> Dict[str, Any]:
    """Loads and caches the benchmark evaluation dataset from Dataset for prompt.xlsx."""
    global _dataset_cache, _dataset_mtime

    target_path = DATASET_PATH
    if not target_path.exists():
        alt_paths = [
            Path.cwd() / "evaluation" / "Dataset for prompt.xlsx",
            Path.cwd() / "Dataset for prompt.xlsx",
            Path(__file__).resolve().parent.parent.parent / "evaluation" / "Dataset for prompt.xlsx",
        ]
        for p in alt_paths:
            if p.exists():
                target_path = p
                break

    if not target_path.exists():
        print(f"[ICC Tracker] Warning: Evaluation dataset not found at {DATASET_PATH}")
        return {"lookup": {}, "student_rows": {}, "df_responses": pd.DataFrame()}

    try:
        current_mtime = os.path.getmtime(target_path)
        if _dataset_cache is not None and current_mtime == _dataset_mtime:
            return _dataset_cache

        df_responses = pd.read_excel(target_path, sheet_name="Response")
        df_responses.columns = df_responses.columns.str.strip()

        lookup = {}
        student_rows = {}

        for _, row in df_responses.iterrows():
            s_id = normalize_student_id(row.get("ID Number"))
            q_no = extract_main_question_no(row.get("question_no"))
            try:
                human_grade = float(row.get("grade", 0.0))
            except (ValueError, TypeError):
                human_grade = 0.0

            if s_id and q_no:
                lookup[(s_id, q_no)] = human_grade
                if s_id not in student_rows:
                    student_rows[s_id] = []
                student_rows[s_id].append({
                    "question_no": q_no,
                    "human_grade": human_grade,
                    "response": row.get("Response ", row.get("Response", ""))
                })

        _dataset_cache = {
            "lookup": lookup,
            "student_rows": student_rows,
            "df_responses": df_responses
        }
        _dataset_mtime = current_mtime
        print(f"[ICC Tracker] Loaded {len(lookup)} student-question benchmark scores from {target_path.name}")
        return _dataset_cache

    except Exception as e:
        print(f"[ICC Tracker Error] Failed to load benchmark dataset: {e}")
        return {"lookup": {}, "student_rows": {}, "df_responses": pd.DataFrame()}


def compute_icc_anova(human_scores: np.ndarray, ai_scores: np.ndarray) -> tuple:
    """
    Computes ICC(A,1) [Two-way random, single rater, absolute agreement]
    and ICC(C,1) [Two-way random, single rater, consistency] via Two-Way ANOVA.
    Works accurately for any sample size k >= 2.
    """
    k = len(human_scores)
    m = 2  # Two raters: Human and AI
    if k < 2:
        return "N/A", "N/A"

    matrix = np.column_stack((human_scores, ai_scores))  # shape: (k, m)
    grand_mean = np.mean(matrix)
    row_means = np.mean(matrix, axis=1)  # shape: (k,)
    col_means = np.mean(matrix, axis=0)  # shape: (m,)

    SST = np.sum((matrix - grand_mean) ** 2)
    SSR = m * np.sum((row_means - grand_mean) ** 2)
    SSC = k * np.sum((col_means - grand_mean) ** 2)
    SSE = max(0.0, SST - SSR - SSC)

    df_r = k - 1
    df_c = m - 1
    df_e = (k - 1) * (m - 1)

    MSR = SSR / df_r if df_r > 0 else 0.0
    MSC = SSC / df_c if df_c > 0 else 0.0
    MSE = SSE / df_e if df_e > 0 else 0.0

    # Avoid zero variance division
    denom_a1 = MSR + (m - 1) * MSE + (m / k) * (MSC - MSE)
    denom_c1 = MSR + (m - 1) * MSE

    if denom_a1 <= 0 or denom_c1 <= 0:
        # If identical ratings
        if np.array_equal(human_scores, ai_scores):
            return 1.0, 1.0
        return "N/A", "N/A"

    icc_a1 = (MSR - MSE) / denom_a1
    icc_c1 = (MSR - MSE) / denom_c1

    # Clamp to [-1.0, 1.0]
    icc_a1 = max(-1.0, min(1.0, icc_a1))
    icc_c1 = max(-1.0, min(1.0, icc_c1))

    return round(float(icc_a1), 4), round(float(icc_c1), 4)


def calculate_and_save_icc(df_comparison: pd.DataFrame) -> None:
    """
    Calculates ICC(A,1), ICC(C,1), MAE, RMSE, Pearson r across all matched pairs
    and per question, then writes to backend_icc_results.csv.
    """
    if df_comparison.empty or len(df_comparison) < 2:
        return

    icc_rows = []

    def compute_metrics_for_subset(subset: pd.DataFrame, scope_name: str):
        n = len(subset)
        if n == 0:
            return

        h_scores = subset["Human Score (Dataset)"].astype(float).values
        a_scores = subset["AI Score (Backend)"].astype(float).values

        mean_h = float(np.mean(h_scores))
        mean_a = float(np.mean(a_scores))
        mae = float(np.mean(np.abs(a_scores - h_scores)))
        rmse = float(np.sqrt(np.mean((a_scores - h_scores) ** 2)))

        # Pearson r
        if np.std(h_scores) > 1e-6 and np.std(a_scores) > 1e-6:
            pearson_r = float(np.corrcoef(h_scores, a_scores)[0, 1])
        else:
            pearson_r = 1.0 if np.array_equal(h_scores, a_scores) else 0.0

        # Calculate ANOVA ICC
        icc_a1_val, icc_c1_val = compute_icc_anova(h_scores, a_scores)

        icc_rows.append({
            "Scope": scope_name,
            "Sample Size (N)": n,
            "ICC(A,1) Absolute Agreement": icc_a1_val,
            "ICC(C,1) Consistency": icc_c1_val,
            "Mean Absolute Error (MAE)": round(mae, 3),
            "Root Mean Squared Error (RMSE)": round(rmse, 3),
            "Pearson Correlation (r)": round(pearson_r, 4),
            "Mean Human Score": round(mean_h, 2),
            "Mean AI Score": round(mean_a, 2),
            "Last Updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    # 1. Overall ICC across all matched student questions
    compute_metrics_for_subset(df_comparison, "Overall (All Questions)")

    # 2. Per-question breakdown (e.g. Q6, Q8, Q9, Q22)
    for q_no, q_group in df_comparison.groupby("Question No"):
        compute_metrics_for_subset(q_group, f"Question {q_no}")

    # Save to CSV
    try:
        EVAL_DIR.mkdir(parents=True, exist_ok=True)
        df_icc = pd.DataFrame(icc_rows)
        df_icc.to_csv(ICC_RESULTS_CSV_PATH, index=False)
        print(f"[ICC Tracker] Calculated ICC score successfully -> {ICC_RESULTS_CSV_PATH}")
    except Exception as e:
        print(f"[ICC Tracker Error] Failed writing ICC CSV: {e}")


def record_and_evaluate_submission(submission: Any) -> None:
    """
    Compares the generated AI scores of a submission with the evaluation dataset (Dataset for prompt.xlsx)
    based on student ID and question number, then updates both:
    1. evaluation/backend_score_comparison.csv
    2. evaluation/backend_icc_results.csv
    """
    if submission is None or getattr(submission, "score", None) is None:
        return

    benchmark = load_benchmark_dataset()
    lookup = benchmark.get("lookup", {})
    student_rows = benchmark.get("student_rows", {})

    s_id = normalize_student_id(getattr(submission, "student_id", ""))
    if not s_id:
        return

    matched_entries = []
    feedback = getattr(submission, "feedback", None) or {}
    breakdown = feedback.get("breakdown", []) if isinstance(feedback, dict) else []

    # Aggregate scores by main question number (e.g. Q6(a) + Q6(b) -> Q6)
    q_aggregates: Dict[str, Dict[str, Any]] = {}
    if breakdown and isinstance(breakdown, list):
        for item in breakdown:
            if not isinstance(item, dict):
                continue
            q_raw = item.get("question_number", "")
            q_main = extract_main_question_no(q_raw)
            if not q_main:
                continue

            score_awarded = float(item.get("score_awarded", 0.0) or 0.0)
            reasoning = item.get("reasoning", "")

            if q_main not in q_aggregates:
                q_aggregates[q_main] = {
                    "total_ai_score": 0.0,
                    "reasonings": []
                }
            q_aggregates[q_main]["total_ai_score"] += score_awarded
            if reasoning:
                q_aggregates[q_main]["reasonings"].append(f"[{q_raw}]: {reasoning}")

    # Check each aggregated question against benchmark dataset lookup
    for q_main, agg_data in q_aggregates.items():
        if (s_id, q_main) in lookup:
            h_score = lookup[(s_id, q_main)]
            ai_score = round(agg_data["total_ai_score"], 2)
            reasoning_str = " | ".join(agg_data["reasonings"]) or feedback.get("summary", "")
            matched_entries.append({
                "Student ID": s_id,
                "Question No": f"Q{q_main}",
                "Human Score (Dataset)": h_score,
                "AI Score (Backend)": ai_score,
                "Absolute Error": round(abs(ai_score - h_score), 2),
                "Difference (AI - Human)": round(ai_score - h_score, 2),
                "Submission ID": getattr(submission, "id", "N/A"),
                "Assignment ID": getattr(submission, "assignment_id", "N/A"),
                "Status": getattr(submission, "status", "graded"),
                "AI Confidence": f"{int((getattr(submission, 'confidence_score', 0.85) or 0.85) * 100)}%",
                "AI Summary / Feedback": reasoning_str,
                "Timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    # Direct match if no breakdown matched but student has single question in dataset
    if not matched_entries and s_id in student_rows:
        rows_for_student = student_rows[s_id]
        if len(rows_for_student) == 1:
            r = rows_for_student[0]
            q_main = r["question_no"]
            h_score = r["human_grade"]
            ai_score = round(float(getattr(submission, "score", 0.0) or 0.0), 2)
            matched_entries.append({
                "Student ID": s_id,
                "Question No": f"Q{q_main}",
                "Human Score (Dataset)": h_score,
                "AI Score (Backend)": ai_score,
                "Absolute Error": round(abs(ai_score - h_score), 2),
                "Difference (AI - Human)": round(ai_score - h_score, 2),
                "Submission ID": getattr(submission, "id", "N/A"),
                "Assignment ID": getattr(submission, "assignment_id", "N/A"),
                "Status": getattr(submission, "status", "graded"),
                "AI Confidence": f"{int((getattr(submission, 'confidence_score', 0.85) or 0.85) * 100)}%",
                "AI Summary / Feedback": feedback.get("summary", "") if isinstance(feedback, dict) else "",
                "Timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    if not matched_entries:
        return

    # Load existing comparison CSV or initialize new
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    if COMPARISON_CSV_PATH.exists() and os.path.getsize(COMPARISON_CSV_PATH) > 0:
        try:
            df_comp = pd.read_csv(COMPARISON_CSV_PATH)
        except Exception:
            df_comp = pd.DataFrame()
    else:
        df_comp = pd.DataFrame()

    # Convert existing records to dict keyed by (Student ID, Question No) for clean upsert
    existing_dict = {}
    if not df_comp.empty and "Student ID" in df_comp.columns and "Question No" in df_comp.columns:
        for _, row in df_comp.iterrows():
            k = (str(row["Student ID"]), str(row["Question No"]))
            existing_dict[k] = row.to_dict()

    for entry in matched_entries:
        k = (str(entry["Student ID"]), str(entry["Question No"]))
        existing_dict[k] = entry

    # Create updated DataFrame
    updated_df = pd.DataFrame(list(existing_dict.values()))
    
    # Sort for clean display
    if "Student ID" in updated_df.columns and "Question No" in updated_df.columns:
        updated_df = updated_df.sort_values(by=["Question No", "Student ID"])

    # Write back comparison CSV
    try:
        updated_df.to_csv(COMPARISON_CSV_PATH, index=False)
        print(f"[ICC Tracker] Saved {len(matched_entries)} comparison entry/entries to {COMPARISON_CSV_PATH}")
    except Exception as e:
        print(f"[ICC Tracker Error] Failed writing comparison CSV: {e}")

    # Re-calculate and save ICC summary
    calculate_and_save_icc(updated_df)


def sync_all_database_submissions(db_session: Any) -> None:
    """Scans all graded submissions in the database and updates comparison & ICC CSVs."""
    try:
        from ..models import Submission
        subs = db_session.query(Submission).filter(Submission.score.isnot(None)).all()
        for s in subs:
            record_and_evaluate_submission(s)
    except Exception as e:
        print(f"[ICC Tracker Error] Failed sync from database: {e}")
