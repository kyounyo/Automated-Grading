"""Shared dataset loading for the model/role evaluation scripts.

Uses the exact same stratified-random 25-responses-per-question sample as
the reference `evaluation/run_experiment_suite.py` /
`run_experiment_2_audit.py` on the main branch (random_state=42), so results
are directly comparable to the existing Gemini 3.1 Flash Lite / Nemotron 3
Super benchmark PDFs. Do NOT switch this back to a deterministic head(N) --
that silently grades a different set of students and produces
non-comparable ICC/MAE numbers (confirmed the hard way).
"""

import os
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(SCRIPT_DIR, "Dataset for prompt.xlsx")

STUDENTS_PER_QUESTION = 25
SAMPLE_SEED = 42
QUESTION_NUMBERS = [6, 8, 9, 22]


def load_dataset(students_per_question: int = STUDENTS_PER_QUESTION, seed: int = SAMPLE_SEED):
    df_questions = pd.read_excel(DATASET_PATH, sheet_name="Question & Answer Scheme")
    df_responses = pd.read_excel(DATASET_PATH, sheet_name="Response")
    df_questions.columns = df_questions.columns.str.strip()
    df_responses.columns = df_responses.columns.str.strip()

    if students_per_question:
        sampled_dfs = []
        for q_no in QUESTION_NUMBERS:
            q_subset = df_responses[
                df_responses["question_no"].astype(str).str.strip().str.replace("Q", "") == str(q_no)
            ]
            sampled_dfs.append(q_subset.sample(n=min(students_per_question, len(q_subset)), random_state=seed))
        df_responses = pd.concat(sampled_dfs, ignore_index=True)

    records = []
    for _, row in df_responses.iterrows():
        response_id = row["ID Number"]
        question_no = str(row["question_no"]).strip().replace("Q", "")
        student_answer = row["Response"]
        human_grade = float(row["grade"])

        matched = df_questions[
            df_questions["question_no"].astype(str).str.strip().str.replace("Q", "") == question_no
        ]
        if matched.empty:
            continue
        q_row = matched.iloc[0]

        records.append(
            {
                "response_id": response_id,
                "question_no": f"Q{question_no}",
                "question_text": q_row["question"],
                "rubric": q_row["answer"],
                "max_score": float(q_row["max_mark"]),
                "student_answer": student_answer,
                "human_score": human_grade,
            }
        )
    return records


def is_blank_answer(student_answer) -> bool:
    if pd.isna(student_answer):
        return True
    clean = str(student_answer).strip()
    return not clean or clean.lower() in ["-", "n/a", "none", "nan"]
