import os
import re
import uuid
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..models import Assignment, Submission, CalibrationSet, CalibrationExample
from .flexible_excel_parser import parse_flexible_calibration, detect_header_row, determine_anchor_type


# Column Aliases matching ungraded submissions parser tolerances
COLUMN_ALIASES = {
    "student_id": [
        "id number", "id_number", "id num", "id_num", "id no", "id_no",
        "student id", "student_id", "student no", "student_no",
        "matric no", "matric_no", "matric", "candidate id", "candidate_id",
        "candidate index", "candidate number", "id", "student number", "stu_id",
        "student_idx", "mat_no"
    ],
    "student_name": [
        "student name", "student_name", "student nam", "student_nam",
        "full name", "full_name", "fullname", "name", "candidate name"
    ],
    "student_email": [
        "student email", "student_email", "email", "gmail",
        "student_gmail", "student_gma", "student gma", "contact email", "mail"
    ],
    "question_number": [
        "question", "question number", "question_no", "question no",
        "question_n", "q_no", "q_num", "q no", "q num", "question_id", "q"
    ],
    "student_text": [
        "response", "response text", "student response", "student_response",
        "student answer", "student_answer", "answer", "submission text",
        "student text", "text", "student work", "submission"
    ],
    "examiner_score": [
        "score", "human score", "human_score", "human mark", "human grade", "human score (dataset)",
        "lecturer score", "lecturer_score", "examiner score", "examiner_score",
        "marks", "mark", "grade", "points", "awarded score"
    ],
    "max_score": [
        "max score", "max_score", "max mark", "max_mark",
        "total marks", "max points", "max", "out of", "maximum mark"
    ],
    "examiner_feedback": [
        "feedback", "justification", "comments", "comment",
        "reasoning", "examiner feedback", "examiner_feedback",
        "rubric rationale", "notes", "marker notes", "remarks"
    ],
    "anchor_type": [
        "anchor", "anchor type", "anchor_type", "classification", "anchor classification"
    ]
}


def normalize_str(val: Any) -> str:
    if val is None or pd.isna(val):
        return ""
    s = str(val).strip().lower()
    s = re.sub(r'[\r\n\t]+', ' ', s)
    s = re.sub(r'[_\-\.:]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def map_columns(df_columns: List[str]) -> Dict[str, str]:
    mapping = {}
    normalized_cols = {col: normalize_str(col) for col in df_columns}

    # 1. Exact match pass
    for canonical, aliases in COLUMN_ALIASES.items():
        for col, norm in normalized_cols.items():
            if norm in aliases and canonical not in mapping:
                mapping[canonical] = col
                break

    # 2. Substring match pass
    for canonical, aliases in COLUMN_ALIASES.items():
        if canonical in mapping:
            continue
        for col, norm in normalized_cols.items():
            if col in mapping.values():
                continue
            if any(alias == norm or alias in norm or norm in alias for alias in aliases if len(alias) >= 2):
                mapping[canonical] = col
                break

    return mapping


def parse_graded_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Parses a graded Excel/CSV file containing calibration data.
    First tries the template-tolerant parse_flexible_calibration engine,
    then falls back to deterministic parsing if needed.
    """
    # 1. Try flexible engine
    try:
        flexible_rows = parse_flexible_calibration(file_path)
        if flexible_rows and len(flexible_rows) > 0:
            return flexible_rows
    except Exception as e:
        print(f"[CalibrationImporter Warning] Flexible parser exception: {e}, falling back to deterministic.")

    # 2. Deterministic Legacy Fallback
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext not in [".csv", ".xlsx", ".xls"]:
        raise ValueError(f"Unsupported file format '{ext}'. Please upload an Excel (.xlsx/.xls) or CSV (.csv) file.")

    header_row = detect_header_row(file_path)

    if ext == ".csv":
        df = pd.read_csv(file_path, skiprows=header_row)
    else:
        df = pd.read_excel(file_path, skiprows=header_row)

    df = df.dropna(how="all")
    if df.empty:
        return []

    df.columns = [str(c).strip() for c in df.columns]
    col_map = map_columns(list(df.columns))

    q_col = col_map.get("question_number")
    resp_col = col_map.get("student_text")
    score_col = col_map.get("examiner_score")

    cols_lower = [str(c).strip().lower() for c in df.columns]

    if not resp_col:
        resp_col = next((df.columns[i] for i, c in enumerate(cols_lower) if any(k in c for k in [
            "response", "answer", "student_answer", "submission", "text"
        ])), None)

    if not score_col:
        score_col = next((df.columns[i] for i, c in enumerate(cols_lower) if any(k in c for k in [
            "score", "human_score", "human score", "lecturer_score", "marks", "mark", "grade"
        ])), None)

    if not resp_col:
        raise ValueError("Could not find a 'Student Response' or 'Answer' column in the uploaded file.")
    if not score_col:
        raise ValueError("Could not find a 'Lecturer Score' or 'Score' column in the uploaded file.")

    id_col = col_map.get("student_id")
    if not id_col:
        id_col = next((df.columns[i] for i, c in enumerate(cols_lower) if any(k in c for k in [
            "id number", "id_number", "student_id", "student id", "student_no", "matric", "id"
        ])), df.columns[0])

    name_col = col_map.get("student_name")
    if not name_col:
        name_col = next((df.columns[i] for i, c in enumerate(cols_lower) if (not id_col or c != str(id_col).lower()) and any(k in c for k in [
            "student_name", "student name", "student_nam", "name"
        ])), None)

    email_col = col_map.get("student_email")
    if not email_col:
        email_col = next((df.columns[i] for i, c in enumerate(cols_lower) if any(k in c for k in [
            "student_email", "student email", "email", "gmail", "student_gmail", "student_gma"
        ])), None)

    max_sc_col = col_map.get("max_score")
    fb_col = col_map.get("examiner_feedback")
    anchor_col = col_map.get("anchor_type")

    parsed_rows = []

    for idx, row in df.iterrows():
        # Student ID
        s_id = str(row[id_col]).strip() if id_col and not pd.isna(row[id_col]) else f"STU_{1001 + idx}"
        if s_id.endswith(".0"): s_id = s_id[:-2]
        if not s_id or s_id.lower() == "nan": s_id = f"STU_{1001 + idx}"

        # Student Name
        s_name = str(row[name_col]).strip() if name_col and not pd.isna(row[name_col]) else f"Student {s_id}"
        if s_name.lower() == "nan": s_name = f"Student {s_id}"

        # Student Email
        s_email = str(row[email_col]).strip() if email_col and not pd.isna(row[email_col]) else "N/A"
        if s_email.lower() == "nan": s_email = "N/A"

        # Question Number
        raw_q = str(row[q_col]).strip() if q_col and not pd.isna(row[q_col]) else f"Q{idx + 1}"
        if raw_q.endswith(".0"): raw_q = raw_q[:-2]
        clean_q = raw_q.upper()
        if not clean_q.startswith("Q") and clean_q.isdigit():
            clean_q = f"Q{clean_q}"

        # Student Response Text
        stu_text = str(row[resp_col]).strip() if not pd.isna(row[resp_col]) else ""
        if stu_text.lower() == "nan": stu_text = ""

        # Score
        raw_sc = row[score_col]
        try:
            score_val = round(float(raw_sc), 2)
        except (ValueError, TypeError):
            score_val = 0.0

        # Max Score
        if max_sc_col and not pd.isna(row[max_sc_col]):
            try: max_sc_val = round(float(row[max_sc_col]), 2)
            except (ValueError, TypeError): max_sc_val = 10.0
        else:
            max_sc_val = 10.0

        # Examiner Feedback
        fb_val = str(row[fb_col]).strip() if fb_col and not pd.isna(row[fb_col]) else ""
        if fb_val.lower() == "nan": fb_val = ""
        if not fb_val:
            fb_val = f"Examiner baseline standard for {clean_q}. Awarded {score_val}/{max_sc_val} marks."

        # Anchor Type
        explicit_anchor = str(row[anchor_col]).strip() if anchor_col and not pd.isna(row[anchor_col]) else None
        anchor_val = determine_anchor_type(score_val, max_sc_val, explicit_anchor)

        parsed_rows.append({
            "student_id": s_id,
            "student_name": s_name,
            "student_email": s_email,
            "question_number": clean_q,
            "student_text": stu_text,
            "examiner_score": score_val,
            "max_score": max_sc_val,
            "examiner_feedback": fb_val,
            "anchor_type": anchor_val
        })

    return parsed_rows


def import_graded_calibration_data(
    file_path: str,
    assignment_id: str,
    original_filename: str,
    db: Session
) -> Dict[str, Any]:
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise ValueError(f"Assignment '{assignment_id}' not found.")

    # Parse rows from file
    rows = parse_graded_file(file_path)
    if not rows:
        raise ValueError("The uploaded file contains no valid data rows.")

    # Match rubric max scores if available
    rubric_items = assign.rubric_data or []
    rubric_max_map = {}
    for item in rubric_items:
        q_k = str(item.get("question_number", "")).strip().upper()
        if q_k:
            val = float(item.get("max_score", item.get("maxMark", 10.0)))
            rubric_max_map[q_k] = val
            if q_k.startswith("Q") and q_k[1:].isdigit():
                rubric_max_map[q_k[1:]] = val
            elif q_k.isdigit():
                rubric_max_map[f"Q{q_k}"] = val

    for r in rows:
        q_k = r["question_number"]
        clean_num = q_k[1:] if (q_k.startswith("Q") and q_k[1:].isdigit()) else q_k
        matching_max = rubric_max_map.get(q_k) or rubric_max_map.get(clean_num)
        if matching_max:
            r["max_score"] = matching_max
            r["anchor_type"] = determine_anchor_type(r["examiner_score"], r["max_score"])

    # Group rows by student to create or update Submission records
    students_data: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        s_id = r["student_id"]
        if s_id not in students_data:
            students_data[s_id] = {
                "student_id": s_id,
                "student_name": r["student_name"],
                "student_email": r["student_email"],
                "questions": []
            }
        students_data[s_id]["questions"].append(r)

    batch_id = f"batch-cal-{uuid.uuid4().hex[:6]}"
    created_sub_ids: Dict[str, str] = {}

    for s_id, s_info in students_data.items():
        q_list = s_info["questions"]
        combined_text = "\n\n".join([
            f"Question {q['question_number']}:\n{q['student_text']}"
            for q in q_list
        ])

        breakdown = [
            {
                "question_number": q["question_number"],
                "score_awarded": q["examiner_score"],
                "score": q["examiner_score"],
                "max_score": q["max_score"],
                "reasoning": q["examiner_feedback"],
                "anchor_type": q["anchor_type"]
            }
            for q in q_list
        ]

        total_score = round(sum(q["examiner_score"] for q in q_list), 2)

        existing_sub = db.query(Submission).filter(
            Submission.assignment_id == assignment_id,
            (Submission.student_id == s_id) | (func.lower(Submission.student_id) == s_id.lower())
        ).first()

        if existing_sub:
            existing_sub.student_name = s_info["student_name"]
            existing_sub.student_email = s_info["student_email"]
            existing_sub.file_name = original_filename
            existing_sub.raw_text = combined_text
            existing_sub.score = total_score
            existing_sub.confidence_score = 1.0
            existing_sub.status = "graded"
            existing_sub.is_calibration_sample = True
            existing_sub.feedback = {
                "breakdown": breakdown,
                "summary": "Authoritative examiner calibration baseline imported from marking records.",
                "evaluator": "human_examiner"
            }
            created_sub_ids[s_id] = existing_sub.id
        else:
            sub_id = f"sub-{uuid.uuid4().hex[:6]}"
            new_sub = Submission(
                id=sub_id,
                assignment_id=assignment_id,
                batch_id=batch_id,
                student_id=s_id,
                student_name=s_info["student_name"],
                student_email=s_info["student_email"],
                file_name=original_filename,
                raw_text=combined_text,
                score=total_score,
                confidence_score=1.0,
                status="graded",
                is_calibration_sample=True,
                feedback={
                    "breakdown": breakdown,
                    "summary": "Authoritative examiner calibration baseline imported from marking records.",
                    "evaluator": "human_examiner"
                }
            )
            db.add(new_sub)
            created_sub_ids[s_id] = sub_id

    db.commit()

    # Create CalibrationExample records and increment CalibrationSet versions
    imported_examples_count = 0
    questions_updated = set()

    for r in rows:
        clean_q = r["question_number"]
        questions_updated.add(clean_q)
        sub_id = created_sub_ids.get(r["student_id"])

        cal_set = db.query(CalibrationSet).filter(
            CalibrationSet.assignment_id == assignment_id,
            CalibrationSet.question_number == clean_q
        ).first()

        if not cal_set:
            cal_set = CalibrationSet(
                assignment_id=assignment_id,
                question_number=clean_q,
                version=1,
                is_active=True
            )
            db.add(cal_set)
            db.commit()
            db.refresh(cal_set)
        else:
            cal_set.version += 1
            db.commit()
            db.refresh(cal_set)

        new_ex = CalibrationExample(
            assignment_id=assignment_id,
            calibration_set_id=cal_set.id,
            submission_id=sub_id,
            question_number=clean_q,
            student_text=r["student_text"],
            examiner_score=r["examiner_score"],
            max_score=r["max_score"],
            examiner_feedback=r["examiner_feedback"],
            anchor_type=r["anchor_type"],
            version=cal_set.version
        )
        db.add(new_ex)
        imported_examples_count += 1

    # Enable calibration on assignment if not already
    assign.calibration_enabled = True
    all_subs = db.query(Submission).filter(Submission.assignment_id == assignment_id).all()
    assign.total_submissions = len(all_subs)

    db.commit()

    return {
        "message": f"Successfully imported {imported_examples_count} calibration exemplars across {len(questions_updated)} questions from {len(students_data)} student submissions.",
        "imported_examples_count": imported_examples_count,
        "imported_students_count": len(students_data),
        "questions_updated": sorted(list(questions_updated)),
        "details": rows[:10]
    }
