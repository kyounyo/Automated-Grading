#!/usr/bin/env python3
"""
Three Tests Evaluation & Comparison Tool
========================================
Compares AI grading outputs across 3 assignment conditions against the ground truth in Dataset for prompt.xlsx:
1. No Tolerance (0%), No Calibration (0-Shot)
2. 10% Tolerance, No Calibration (0-Shot)
3. 0% Tolerance, 3-Submission Calibration (6 question exemplars)

Matches student responses by Student ID and Question Number.
Computes:
- Item-level score deltas (Human Ground Truth vs AI Score)
- Summary metrics: MAE, Mean Bias, Exact Agreement %, Major Error %, Flag Rate %, Automation Rate %, and ICC(A,1).
- Exports formatted comparison reports to evaluation/three_tests_results_comparison.csv
  and evaluation/three_tests_summary_metrics.csv
"""

import os
import re
import sys
import json
import argparse
from pathlib import Path
import pandas as pd
import numpy as np
import pingouin as pg
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_DIR / "backend"
DATASET_PATH = SCRIPT_DIR / "Dataset for prompt.xlsx"
DB_PATH = BACKEND_DIR / "autograde_dev.db"

sys.path.append(str(BACKEND_DIR))
from app.models import Assignment, Submission, CalibrationExample


def normalize_student_id(s_id):
    if s_id is None:
        return ""
    val = str(s_id).strip()
    if val.endswith(".0"):
        val = val[:-2]
    return val


def normalize_question_no(q_str):
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


def load_ground_truth(dataset_path: Path):
    if not dataset_path.exists():
        raise FileNotFoundError(f"Benchmark dataset not found at {dataset_path}")
    df = pd.read_excel(dataset_path, sheet_name="Response")
    lookup = {}
    for _, row in df.iterrows():
        s_id = normalize_student_id(row.get("ID Number"))
        q_no = normalize_question_no(row.get("question_no"))
        grade = row.get("grade")
        if s_id and q_no and pd.notna(grade):
            key = f"{s_id}_{q_no}"
            lookup[key] = float(grade)
    return lookup, df


def run_comparison(db_path: Path = DB_PATH, dataset_path: Path = DATASET_PATH, export_dir: Path = SCRIPT_DIR):
    engine = create_engine(f"sqlite:///{db_path}")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    ground_truth, df_raw = load_ground_truth(dataset_path)
    print(f"Loaded {len(ground_truth)} benchmark question scores from '{dataset_path.name}'.")

    assignments = session.query(Assignment).order_by(Assignment.created_at.asc()).all()
    if not assignments:
        print("No assignments found in the database.")
        session.close()
        return

    print(f"Found {len(assignments)} assignment(s) in database.\n")

    all_records = []
    condition_summaries = []

    for idx, assign in enumerate(assignments, 1):
        cal_count = session.query(CalibrationExample).filter(CalibrationExample.assignment_id == assign.id).count()
        cal_enabled = bool(assign.calibration_enabled) or (cal_count > 0)
        tol_rate = getattr(assign, "tolerance_rate", 0.10)
        if tol_rate is None:
            tol_rate = 0.10
        tol_pct = int(round(tol_rate * 100))

        # Auto-label condition
        if not cal_enabled and tol_pct == 0:
            cond_label = "Test 1: 0% Tolerance, No Calibration (Baseline)"
        elif not cal_enabled and tol_pct == 10:
            cond_label = "Test 2: 10% Tolerance, No Calibration"
        elif cal_enabled and tol_pct == 0:
            cond_label = f"Test 3: 0% Tolerance, Calibrated ({cal_count} exemplars)"
        elif cal_enabled and tol_pct == 10:
            cond_label = f"Test 4: 10% Tolerance, Calibrated ({cal_count} exemplars)"
        else:
            cond_label = f"Assignment {idx}: {assign.title} (Tol {tol_pct}%, Calib {'Yes' if cal_enabled else 'No'})"

        submissions = session.query(Submission).filter(
            Submission.assignment_id == assign.id,
            Submission.status.in_(["graded", "flagged"])
        ).all()

        if not submissions:
            print(f"[{cond_label}] (ID: {assign.id}) - No graded submissions yet.")
            continue

        item_records = []
        flagged_count = 0
        graded_count = 0

        for sub in submissions:
            if sub.status == "flagged":
                flagged_count += 1
            elif sub.status == "graded":
                graded_count += 1

            s_id = normalize_student_id(sub.student_id)
            feedback = sub.feedback or {}
            breakdown = feedback.get("breakdown", []) if isinstance(feedback, dict) else []

            # Aggregate breakdown by Main Question (e.g. Q6, Q8) so comparison is Question by Question
            main_q_scores = {}
            if breakdown and isinstance(breakdown, list):
                for item in breakdown:
                    if not isinstance(item, dict):
                        continue
                    q_raw = item.get("question_number") or item.get("criterion") or ""
                    q_no = normalize_question_no(q_raw)
                    if not q_no:
                        continue
                    sc = float(item.get("score_awarded", item.get("score", 0.0)))
                    mx = float(item.get("max_score", item.get("maxMark", 10.0)))
                    if q_no not in main_q_scores:
                        main_q_scores[q_no] = {"score": sc, "max_score": mx}
                    else:
                        main_q_scores[q_no]["score"] += sc
                        main_q_scores[q_no]["max_score"] += mx

            for q_no, q_data in main_q_scores.items():
                ai_q_score = round(q_data["score"], 1)
                max_q_score = q_data["max_score"]
                lookup_key = f"{s_id}_{q_no}"
                human_score = ground_truth.get(lookup_key)

                record = {
                    "assignment_id": assign.id,
                    "assignment_title": assign.title,
                    "test_condition": cond_label,
                    "tolerance_rate": f"{tol_pct}%",
                    "calibration_enabled": cal_enabled,
                    "calibration_count": cal_count,
                    "submission_id": sub.id,
                    "student_id": s_id,
                    "question_no": f"Q{q_no}",
                    "max_score": max_q_score,
                    "human_score": human_score,
                    "ai_score": ai_q_score,
                    "absolute_error": abs(ai_q_score - human_score) if human_score is not None else None,
                    "bias": (ai_q_score - human_score) if human_score is not None else None,
                    "status": sub.status,
                    "confidence": sub.confidence_score,
                    "is_calibration_sample": sub.is_calibration_sample
                }
                all_records.append(record)
                if human_score is not None:
                    item_records.append(record)

        total_subs = len(submissions)
        auto_rate = (graded_count / total_subs * 100.0) if total_subs > 0 else 0.0
        flag_rate = (flagged_count / total_subs * 100.0) if total_subs > 0 else 0.0

        if item_records:
            df_items = pd.DataFrame(item_records)
            mae = df_items["absolute_error"].mean()
            bias = df_items["bias"].mean()
            exact_pct = (df_items["absolute_error"] == 0).mean() * 100.0
            err_ge_1pt_pct = (df_items["absolute_error"] >= 1.0).mean() * 100.0
            major_err_pct = (df_items["absolute_error"] >= 2.0).mean() * 100.0

            # Compute Question-level ICC(A,1)
            icc_q_val = None
            try:
                df_icc_q = []
                for idx_row, row in df_items.iterrows():
                    target_id = f"{row['student_id']}_{row['question_no']}"
                    df_icc_q.append({"target": target_id, "rater": "Human", "score": row["human_score"]})
                    df_icc_q.append({"target": target_id, "rater": "AI", "score": row["ai_score"]})
                df_icc_res = pd.DataFrame(df_icc_q)
                icc_table = pg.intraclass_corr(data=df_icc_res, targets="target", raters="rater", ratings="score")
                icc_match = icc_table[icc_table["Type"].isin(["ICC(A,1)", "ICC2"])]
                if not icc_match.empty:
                    icc_q_val = round(float(icc_match.iloc[0]["ICC"]), 3)
                else:
                    icc_q_val = round(float(icc_table.iloc[1]["ICC"]), 3)
            except Exception:
                icc_q_val = None

            # Compute Total Paper-level ICC(A,1) and Pearson correlation r
            icc_paper_val = None
            r_paper_val = None
            try:
                paper_totals = df_items.groupby("student_id")[["human_score", "ai_score"]].sum().reset_index()
                df_icc_p = []
                for idx_row, row in paper_totals.iterrows():
                    target_id = str(row["student_id"])
                    df_icc_p.append({"target": target_id, "rater": "Human", "score": row["human_score"]})
                    df_icc_p.append({"target": target_id, "rater": "AI", "score": row["ai_score"]})
                icc_p_res = pd.DataFrame(df_icc_p)
                icc_p_table = pg.intraclass_corr(data=icc_p_res, targets="target", raters="rater", ratings="score")
                icc_p_match = icc_p_table[icc_p_table["Type"].isin(["ICC(A,1)", "ICC2"])]
                if not icc_p_match.empty:
                    icc_paper_val = round(float(icc_p_match.iloc[0]["ICC"]), 3)
                else:
                    icc_paper_val = round(float(icc_p_table.iloc[1]["ICC"]), 3)

                if len(paper_totals) > 2:
                    r_corr = paper_totals["human_score"].corr(paper_totals["ai_score"])
                    r_paper_val = round(float(r_corr), 3)
            except Exception:
                icc_paper_val = None

            condition_summaries.append({
                "Test Condition": cond_label,
                "Assignment Title": assign.title,
                "Tolerance": f"{tol_pct}%",
                "Calibration": f"Yes ({cal_count} exemplars)" if cal_enabled else "No (0-Shot)",
                "Total Submissions (N)": total_subs,
                "Total Questions Evaluated": len(df_items),
                "Automation Rate %": f"{auto_rate:.1f}%",
                "Flag Rate %": f"{flag_rate:.1f}%",
                "Question ICC (A,1)": icc_q_val if icc_q_val is not None else "N/A",
                "Total Paper ICC (A,1)": icc_paper_val if icc_paper_val is not None else "N/A",
                "Paper Correlation (r)": r_paper_val if r_paper_val is not None else "N/A",
                "MAE (marks)": f"{mae:.3f}",
                "Mean Bias (AI - Human)": f"{bias:+.3f}",
                "Exact Agreement %": f"{exact_pct:.1f}%",
                "Error ≥ 1pt %": f"{err_ge_1pt_pct:.1f}%",
                "Major Error (≥ 2pt) %": f"{major_err_pct:.1f}%"
            })

    session.close()

    if all_records:
        df_all = pd.DataFrame(all_records)
        export_csv_4 = export_dir / "four_tests_results_comparison.csv"
        df_all.to_csv(export_csv_4, index=False)
        # Also maintain three_tests_results_comparison.csv for backward compatibility
        df_all.to_csv(export_dir / "three_tests_results_comparison.csv", index=False)
        print(f"✅ Exported detailed per-question comparison to: {export_csv_4}")

    if condition_summaries:
        df_summary = pd.DataFrame(condition_summaries)
        summary_csv_4 = export_dir / "four_tests_summary_metrics.csv"
        df_summary.to_csv(summary_csv_4, index=False)
        # Also maintain three_tests_summary_metrics.csv for backward compatibility
        df_summary.to_csv(export_dir / "three_tests_summary_metrics.csv", index=False)
        print(f"✅ Exported summary metrics to: {summary_csv_4}\n")

        print("=" * 115)
        print("                        🏆 FOUR TESTS EVALUATION SUMMARY REPORT 🏆")
        print("=" * 115)
        print(df_summary.to_string(index=False))
        print("=" * 115)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare AI Grading Outputs against Ground Truth across 3 Tests")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to autograde_dev.db")
    parser.add_argument("--dataset", default=str(DATASET_PATH), help="Path to Dataset for prompt.xlsx")
    args = parser.parse_args()

    run_comparison(Path(args.db), Path(args.dataset))
