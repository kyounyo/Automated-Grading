"""
One-time reformat of evaluation/results/baseline_<model>_raw.csv into the
exact column layout used by main branch's run_experiment_suite.py, using
only data already saved (the per-response JSON log + the seed=42 dataset for
student_answer) -- no API calls, no added cost.

Main's columns:
  response_id, question_no, human_score, predicted_score, max_score,
  absolute_error, difference (AI - Human), latency_ms, actual_input_tokens,
  actual_output_tokens, estimated_cost_usd, student_answer, reasoning, raw_json
Appended after (our own addition, not on main): ai_feedback

Usage:
    python migrate_baseline_csv_to_main_schema.py [model_key ...]
"""

import os
import sys
import json
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from data_loader import load_dataset
from model_config import MODELS

RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")


def extract_feedback_text(fb) -> str:
    if isinstance(fb, dict):
        return fb.get("summary", "")
    return fb or ""


def migrate(model_key: str):
    csv_path = os.path.join(RESULTS_DIR, f"baseline_{model_key}_raw.csv")
    json_path = os.path.join(RESULTS_DIR, f"baseline_{model_key}_raw.json")
    if not os.path.exists(csv_path) or not os.path.exists(json_path):
        print(f"[{model_key}] missing csv/json, skipping.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        json_log = json.load(f)
    eval_map = {(e["response_id"], e["question_no"]): e.get("ai_evaluation", {}) for e in json_log}

    records = load_dataset()
    answer_map = {(r["response_id"], r["question_no"]): r["student_answer"] for r in records}

    df = pd.read_csv(csv_path)
    new_rows = []
    for _, row in df.iterrows():
        key = (row["response_id"], row["question_no"])
        ev = eval_map.get(key, {})
        predicted_score = float(row["ai_score"])
        human_score = float(row["human_score"])
        new_rows.append({
            "response_id": row["response_id"],
            "question_no": row["question_no"],
            "human_score": human_score,
            "predicted_score": predicted_score,
            "max_score": row["max_score"],
            "absolute_error": round(abs(predicted_score - human_score), 2),
            "difference (AI - Human)": round(predicted_score - human_score, 2),
            "latency_ms": round(float(row["latency_s"]) * 1000),
            "actual_input_tokens": row["input_tokens"],
            "actual_output_tokens": row["output_tokens"],
            "estimated_cost_usd": row["cost_usd"],
            "student_answer": str(answer_map.get(key, "")),
            "reasoning": str(ev.get("reasoning", "")),
            "raw_json": json.dumps(ev, ensure_ascii=False),
            "ai_feedback": row.get("ai_feedback", extract_feedback_text(ev.get("feedback", ""))),
            "error": row.get("error"),
        })

    out_df = pd.DataFrame(new_rows)
    out_df.to_csv(csv_path, index=False)
    print(f"[{model_key}] migrated {len(out_df)} rows to main-branch column schema.")


if __name__ == "__main__":
    keys = sys.argv[1:] or list(MODELS.keys())
    for k in keys:
        if k == "free":
            continue
        migrate(k)
