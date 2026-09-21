import re
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Set
import pandas as pd
import numpy as np


# =====================================================================
# 1. CONTROLLED DOMAIN ALIASES DICTIONARY
# Categorized into High-Confidence vs Ambiguous Aliases
# =====================================================================

RUBRIC_ALIASES = {
    "question_number": {
        "high": [
            "question no", "question_no", "question_n", "q_no", "q_num", 
            "question number", "question label", "question_id", "q num", "q no"
        ],
        "ambiguous": ["question", "item", "task", "no", "num", "id"]
    },
    "text": {
        "high": [
            "question text", "prompt", "question prompt", "task description",
            "assessment criteria", "criteria description", "problem statement"
        ],
        "ambiguous": ["question", "criteria", "task", "description"]
    },
    "model_answer": {
        "high": [
            "model answer", "answer scheme", "marking scheme", "marking guide",
            "solution", "exemplar", "expected answer", "marking criteria", "rubric text"
        ],
        "ambiguous": ["answer", "rubric", "scheme", "guide"]
    },
    "max_mark": {
        "high": [
            "max mark", "max_mark", "maximum mark", "max score", "max_score",
            "marks", "total marks", "allocated marks", "points", "max points"
        ],
        "ambiguous": ["mark", "score", "weightage", "weight"]
    }
}

SUBMISSION_ALIASES = {
    "student_id": {
        "high": [
            "student id", "student_id", "student number", "student_no", 
            "matric no", "matric_no", "candidate id", "candidate index",
            "candidate number", "stu_id", "student_idx", "mat_no",
            "id number", "id_number", "id num", "id_num", "id no", "id_no",
            "id"
        ],
        "ambiguous": ["student", "num", "identifier"]
    },
    "student_name": {
        "high": [
            "student name", "student_name", "full name", "full_name", 
            "candidate name", "student_nam", "student nam", "fullname"
        ],
        "ambiguous": ["name", "student"]
    },
    "student_email": {
        "high": [
            "student email", "student_email", "email", "gmail", 
            "student_gmail", "student_gma", "student gma", "contact email", "mail"
        ],
        "ambiguous": ["contact", "address"]
    },
    "question_number": {
        "high": [
            "question no", "question_no", "question_n", "q_no", "q_num",
            "question number", "question label", "q num", "q no", "question_id"
        ],
        "ambiguous": ["question", "item", "task", "q"]
    },
    "student_response": {
        "high": [
            "student response", "student_response", "student answer", "student_answer",
            "student work", "submission text", "student submission", "response text",
            "response", "answer"
        ],
        "ambiguous": ["submission", "text", "body", "work"]
    }
}

CALIBRATION_ALIASES = {
    "student_id": SUBMISSION_ALIASES["student_id"],
    "student_name": SUBMISSION_ALIASES["student_name"],
    "student_email": SUBMISSION_ALIASES["student_email"],
    "question_number": SUBMISSION_ALIASES["question_number"],
    "student_response": SUBMISSION_ALIASES["student_response"],
    "examiner_score": {
        "high": [
            "score", "human score", "human_score", "human mark", "human grade",
            "human score dataset", "lecturer score", "lecturer_score",
            "examiner score", "examiner_score", "marks", "mark", "awarded score",
            "points", "grade"
        ],
        "ambiguous": ["result", "val", "value", "sc"]
    },
    "max_score": {
        "high": [
            "max score", "max_score", "max mark", "max_mark", "total marks",
            "max points", "out of", "maximum mark"
        ],
        "ambiguous": ["max", "total"]
    },
    "examiner_feedback": {
        "high": [
            "feedback", "examiner feedback", "examiner_feedback", "comment", "comments",
            "justification", "reasoning", "marker notes", "notes", "rubric rationale"
        ],
        "ambiguous": ["remark", "remarks", "rationale", "note"]
    },
    "anchor_type": {
        "high": [
            "anchor", "anchor type", "anchor_type", "classification", "anchor classification"
        ],
        "ambiguous": ["tier", "level", "category", "band"]
    }
}



# =====================================================================
# 2. STRING & HEADER NORMALIZATION
# =====================================================================

def normalize_header(header: Any) -> str:
    """Normalizes header string: lowercase, strips punctuation and extra whitespace."""
    if header is None or pd.isna(header):
        return ""
    text = str(header).strip().lower()
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'[_\-\.:]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def compute_string_similarity(a: str, b: str) -> float:
    """Computes basic normalized string similarity (token overlap / containment)."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        shorter, longer = (a, b) if len(a) < len(b) else (b, a)
        return len(shorter) / len(longer)
    
    # Token set overlap (Jaccard similarity on word tokens)
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = a_tokens.intersection(b_tokens)
    union = a_tokens.union(b_tokens)
    return len(intersection) / len(union)


# =====================================================================
# 3. HEADER ROW DETECTION
# =====================================================================

def detect_header_row(file_path: str, max_scan_rows: int = 15) -> int:
    """
    Scans the top N rows of an Excel/CSV file to identify the true table header row.
    Skips title banners, metadata blocks, and empty rows.
    Returns 0-indexed row number.
    """
    try:
        import csv
        ext = Path(file_path).suffix.lower()
        raw_rows = []

        if ext == ".csv":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if i >= max_scan_rows:
                        break
                    raw_rows.append(row)
        else:
            df_raw = pd.read_excel(file_path, header=None, nrows=max_scan_rows)
            raw_rows = df_raw.values.tolist()

        if not raw_rows:
            return 0

        best_row_idx = 0
        best_score = -1.0

        all_known_keywords = set()
        for field_dict in list(RUBRIC_ALIASES.values()) + list(SUBMISSION_ALIASES.values()):
            for alias in field_dict["high"] + field_dict["ambiguous"]:
                all_known_keywords.update(alias.split())

        max_cols_found = max(len(r) for r in raw_rows) if raw_rows else 1

        for row_idx, row in enumerate(raw_rows):
            cells = [str(c).strip() for c in row if pd.notna(c) and str(c).strip() != "" and str(c).strip().lower() != "nan"]
            if not cells:
                continue

            non_empty_count = len(cells)
            density = non_empty_count / max(max_cols_found, 1)

            # Check if values look like string header labels (not long sentences, not purely numbers)
            string_count = sum(1 for c in cells if not re.match(r'^\d+(\.\d+)?$', c) and len(c) < 50)
            string_ratio = string_count / non_empty_count if non_empty_count > 0 else 0

            # Match against known keywords
            keyword_matches = 0
            for c in cells:
                norm_c = normalize_header(c)
                tokens = set(norm_c.split())
                if tokens.intersection(all_known_keywords):
                    keyword_matches += 1

            # Header Score: Combines keyword matches, string ratio, and column density
            score = (keyword_matches * 4.0) + (string_ratio * 2.0) + (density * 2.5)

            # Single cell across the row usually indicates a title/banner row (e.g. "Monash University")
            if non_empty_count == 1 and max_cols_found > 1 and keyword_matches == 0:
                score = 0.05

            if score > best_score:
                best_score = score
                best_row_idx = row_idx

        return int(best_row_idx)
    except Exception as e:
        print(f"[FlexibleExcelParser] Header row detection fallback on {file_path}: {e}")
        return 0


# =====================================================================
# 4. CONTENT-BASED EVIDENCE & PROFILING
# =====================================================================

def evaluate_content_evidence(field_name: str, samples: List[Any]) -> float:
    """
    Analyzes cell value samples to compute a content compatibility score [0.0, 1.0].
    """
    clean_samples = [str(s).strip() for s in samples if pd.notna(s) and str(s).strip() != "" and str(s).strip().lower() != "nan"]
    if not clean_samples:
        return 0.3  # Neutral score if empty

    n = len(clean_samples)

    if field_name == "student_id":
        # Actively reject if values look like Question numbers (e.g. Q1, Q2, Question 3)
        if any(re.match(r'^[Qq]\d+$', s) or re.match(r'^[Qq]uestion\s*\d+', s) for s in clean_samples):
            return 0.0

        # Short alphanumeric (e.g. 23001234, STU101, A0123456X, len <= 20)
        id_matches = sum(1 for s in clean_samples if re.match(r'^(?:[A-Za-z0-9_\-]{3,20})$', s) and not re.match(r'^[Qq]\d+$', s))
        avg_len = sum(len(s) for s in clean_samples) / n
        if avg_len <= 20 and (id_matches / n) >= 0.7:
            return 0.95
        elif avg_len <= 25:
            return 0.50
        return 0.10

    elif field_name == "student_name":
        # Multi-character names, mostly alphabetic, usually 2-40 chars, no special symbols/emails
        name_matches = sum(1 for s in clean_samples if re.match(r'^[A-Za-z\s\.\,\'\-]{2,50}$', s) and "@" not in s)
        avg_len = sum(len(s) for s in clean_samples) / n
        if 2 <= avg_len <= 45 and (name_matches / n) >= 0.7:
            return 0.95
        return 0.40

    elif field_name == "student_email":
        email_matches = sum(1 for s in clean_samples if re.search(r'[\w\.-]+@[\w\.-]+\.\w+', s))
        return 1.0 if (email_matches / n) >= 0.7 else (0.5 if email_matches > 0 else 0.0)

    elif field_name == "question_number":
        # Q1, 1, 1.1, Question 2, Part A (short string <= 12 chars)
        q_matches = sum(1 for s in clean_samples if re.match(r'^(?:[Qq]?\d+(\.\d+)?|[Qq]uestion\s*\d+|[Pp]art\s*[A-Za-z0-9])$', s.strip()))
        avg_len = sum(len(s) for s in clean_samples) / n
        if (q_matches / n) >= 0.6 and avg_len <= 15:
            return 0.95
        elif avg_len <= 10:
            return 0.65
        return 0.10

    elif field_name == "max_mark":
        # Pure positive numbers typically in range 0.5 to 100. Reject percentages (%) or long text
        valid_marks = 0
        has_percentage = any("%" in s for s in clean_samples)
        for s in clean_samples:
            try:
                val = float(re.sub(r'[^\d\.]', '', s))
                if 0.5 <= val <= 200.0 and not has_percentage:
                    valid_marks += 1
            except Exception:
                pass
        if (valid_marks / n) >= 0.7 and not has_percentage:
            return 0.95
        elif has_percentage:
            # Indicates weightage percentage rather than absolute max marks
            return 0.20
        return 0.10

    elif field_name in ["question_text", "model_answer", "student_response"]:
        # Substantial text: multi-word sentences, average length > 25 characters
        avg_len = sum(len(s) for s in clean_samples) / n
        multi_word = sum(1 for s in clean_samples if len(s.split()) >= 3)
        if avg_len >= 30 and (multi_word / n) >= 0.6:
            return 0.95
        elif avg_len >= 15:
            return 0.70
        return 0.30

    elif field_name == "examiner_score":
        valid_scores = 0
        for s in clean_samples:
            try:
                val = float(re.sub(r'[^\d\.]', '', s))
                if 0.0 <= val <= 200.0:
                    valid_scores += 1
            except Exception:
                pass
        return 0.95 if (valid_scores / n) >= 0.7 else 0.30

    return 0.50


# =====================================================================
# 5. COLUMN CONFIDENCE & SCHEMA RESOLUTION
# =====================================================================

def compute_column_confidence(header_raw: str, samples: List[Any], target_field: str, schema_dict: Dict[str, Any]) -> float:
    """
    Computes weighted column confidence:
    Confidence = 0.60 * Header_Score + 0.40 * Content_Score
    """
    norm_h = normalize_header(header_raw)
    field_rules = schema_dict.get(target_field, {"high": [], "ambiguous": []})

    # Header Evidence Score (0.0 - 1.0)
    header_score = 0.0
    if norm_h in field_rules["high"]:
        header_score = 1.0
    elif any(compute_string_similarity(norm_h, alias) >= 0.85 for alias in field_rules["high"]):
        header_score = 0.90
    elif norm_h in field_rules["ambiguous"]:
        header_score = 0.60
    elif any(compute_string_similarity(norm_h, alias) >= 0.75 for alias in field_rules["ambiguous"]):
        header_score = 0.50
    else:
        # Partial token overlap
        max_sim = max([compute_string_similarity(norm_h, a) for a in field_rules["high"] + field_rules["ambiguous"]] or [0.0])
        header_score = max_sim * 0.5

    # Content Evidence Score (0.0 - 1.0)
    content_score = evaluate_content_evidence(target_field, samples)

    # Weighted combination
    confidence = (0.60 * header_score) + (0.40 * content_score)
    return round(float(confidence), 3)


def resolve_schema_mapping(df: pd.DataFrame, schema_type: str = "rubric") -> Tuple[Dict[str, Optional[str]], float, bool]:
    """
    Resolves optimal column mappings and calculates overall schema confidence.
    Enforces structural validity invariants:
    - Mandatory fields mapped
    - No two fields mapped to the exact same column (unless safely shared)
    - Rejects invalid/noisy schemas

    Returns:
        (mapping_dict, overall_confidence, is_valid)
    """
    if schema_type == "rubric":
        schema_dict = RUBRIC_ALIASES
    elif schema_type == "calibration":
        schema_dict = CALIBRATION_ALIASES
    else:
        schema_dict = SUBMISSION_ALIASES
    target_fields = list(schema_dict.keys())
    cols = list(df.columns)

    if not cols:
        return {}, 0.0, False

    # Compute confidence matrix: target_field -> {col: score}
    score_matrix: Dict[str, Dict[str, float]] = {field: {} for field in target_fields}

    for field in target_fields:
        for col in cols:
            samples = df[col].dropna().head(10).tolist()
            conf = compute_column_confidence(str(col), samples, field, schema_dict)
            score_matrix[field][str(col)] = conf

    # Greedy optimal assignment prioritizing highest confidence matches
    resolved_mapping: Dict[str, Optional[str]] = {field: None for field in target_fields}
    assigned_cols: Set[str] = set()

    # Flatten matches into sorted list of (score, field, col)
    all_candidate_matches = []
    for field in target_fields:
        for col, score in score_matrix[field].items():
            all_candidate_matches.append((score, field, col))
    all_candidate_matches.sort(key=lambda x: x[0], reverse=True)

    field_confidences = {}
    for score, field, col in all_candidate_matches:
        if resolved_mapping[field] is None and col not in assigned_cols and score >= 0.40:
            resolved_mapping[field] = col
            assigned_cols.add(col)
            field_confidences[field] = score

    # Fallback assignment for single-column text or standard positional formats if unassigned
    if schema_type == "rubric":
        # Mandatory: question_number and (text or model_answer)
        if not resolved_mapping["question_number"] and len(cols) >= 1:
            first_col = str(cols[0])
            if first_col not in assigned_cols:
                resolved_mapping["question_number"] = first_col
                field_confidences["question_number"] = 0.50

        if not resolved_mapping["text"] and not resolved_mapping["model_answer"]:
            # Pick longest text column
            unassigned = [c for c in cols if c not in assigned_cols]
            if unassigned:
                chosen = str(unassigned[0])
                resolved_mapping["text"] = chosen
                field_confidences["text"] = 0.50

        is_valid = bool(
            resolved_mapping.get("question_number") and 
            (resolved_mapping.get("text") or resolved_mapping.get("model_answer"))
        )

    elif schema_type == "calibration":
        # Mandatory: student_id, student_response, examiner_score
        if not resolved_mapping.get("student_id") and len(cols) >= 1:
            first_col = str(cols[0])
            if first_col not in assigned_cols:
                resolved_mapping["student_id"] = first_col
                field_confidences["student_id"] = 0.50

        if not resolved_mapping.get("student_response"):
            unassigned = [c for c in cols if c not in assigned_cols and c != resolved_mapping.get("examiner_score")]
            if unassigned:
                resolved_mapping["student_response"] = str(unassigned[-1])
                field_confidences["student_response"] = 0.50

        is_valid = bool(
            resolved_mapping.get("student_response") and 
            resolved_mapping.get("examiner_score")
        )

    else:  # submission
        # Mandatory: student_id and (student_response or any text column)
        if not resolved_mapping["student_id"] and len(cols) >= 1:
            first_col = str(cols[0])
            if first_col not in assigned_cols:
                resolved_mapping["student_id"] = first_col
                field_confidences["student_id"] = 0.50

        if not resolved_mapping["student_response"]:
            unassigned = [c for c in cols if c not in assigned_cols]
            if unassigned:
                resolved_mapping["student_response"] = str(unassigned[-1])
                field_confidences["student_response"] = 0.50

        is_valid = bool(
            resolved_mapping.get("student_id") and 
            resolved_mapping.get("student_response")
        )

    # Calculate overall schema confidence
    if field_confidences:
        overall_conf = round(float(sum(field_confidences.values()) / len(field_confidences)), 3)
    else:
        overall_conf = 0.0

    return resolved_mapping, overall_conf, is_valid


# =====================================================================
# 6. HIGH-LEVEL TEMPLATE-TOLERANT PARSERS
# =====================================================================

def parse_flexible_rubric(file_path: str) -> List[Dict[str, Any]]:
    """
    Template-tolerant parser for Excel/CSV Rubric schemes.
    1. Detects true header row index (skipping titles/banners).
    2. Maps columns via Header + Content confidence scoring.
    3. Returns standardized List[Dict] format for downstream grading.
    """
    try:
        header_row = detect_header_row(file_path)
        ext = Path(file_path).suffix.lower()

        if ext == ".csv":
            df = pd.read_csv(file_path, skiprows=header_row)
        else:
            df = pd.read_excel(file_path, skiprows=header_row)

        df = df.dropna(how="all")
        if df.empty:
            return []

        mapping, overall_conf, is_valid = resolve_schema_mapping(df, schema_type="rubric")
        print(f"[FlexibleExcelParser] Rubric Schema Resolution: {mapping} (Confidence: {overall_conf * 100:.1f}%)")

        q_num_col = mapping.get("question_number")
        q_text_col = mapping.get("text")
        ans_col = mapping.get("model_answer")
        mark_col = mapping.get("max_mark")

        questions = []
        for idx, row in df.iterrows():
            # Question Number
            q_num_val = str(row[q_num_col]).strip() if q_num_col and pd.notna(row.get(q_num_col)) else str(idx + 1)
            if q_num_val.endswith(".0"):
                q_num_val = q_num_val[:-2]
            q_label = q_num_val if q_num_val.lower().startswith("q") else f"Q{q_num_val}"

            # Question Text & Model Answer
            q_text_val = str(row[q_text_col]).strip() if q_text_col and pd.notna(row.get(q_text_col)) else ""
            ans_val = str(row[ans_col]).strip() if ans_col and pd.notna(row.get(ans_col)) else ""

            if not q_text_val and not ans_val:
                continue

            if not q_text_val:
                q_text_val = f"Question {q_label}"
            if not ans_val:
                ans_val = q_text_val

            # Max Mark
            try:
                if mark_col and pd.notna(row.get(mark_col)):
                    cleaned_m = re.sub(r'[^\d\.]', '', str(row[mark_col]))
                    max_mark_val = float(cleaned_m) if cleaned_m else 10.0
                else:
                    max_mark_val = 10.0
            except Exception:
                max_mark_val = 10.0

            questions.append({
                "id": len(questions) + 1,
                "question_number": q_label,
                "text": q_text_val,
                "maxMark": max_mark_val if max_mark_val > 0 else 10.0,
                "modelAnswer": ans_val
            })

        return questions
    except Exception as e:
        print(f"[FlexibleExcelParser Error] Rubric parsing failed on {file_path}: {e}")
        return []


def parse_flexible_submissions(file_path: str) -> List[Dict[str, Any]]:
    """
    Template-tolerant parser for Excel/CSV Student Submission datasets.
    Supports:
    1. Long Format: Multiple rows per student with Question and Response columns.
    2. Wide Format (Matrix): One row per student with questions as columns (e.g. Q1, Q2, Q3, Question 1, 6, 8).
    3. Single Column Format: One row per student with a single Response/Submission column.
    """
    try:
        header_row = detect_header_row(file_path)
        ext = Path(file_path).suffix.lower()

        if ext == ".csv":
            df = pd.read_csv(file_path, skiprows=header_row)
        else:
            df = pd.read_excel(file_path, skiprows=header_row)

        df = df.dropna(how="all")
        if df.empty:
            return []

        # Use intelligent Schema Resolver with Header + Content Scoring
        mapping, overall_conf, is_valid = resolve_schema_mapping(df, schema_type="submission")
        print(f"[FlexibleExcelParser] Submissions Schema Resolution: {mapping} (Confidence: {overall_conf * 100:.1f}%)")

        stu_col = mapping.get("student_id")
        name_col = mapping.get("student_name")
        email_col = mapping.get("student_email")
        q_col = mapping.get("question_number")
        resp_col = mapping.get("student_response")

        cols_lower = [str(c).strip().lower() for c in df.columns]

        # Fallback if mapping missed any columns
        if not stu_col and len(df.columns) > 0:
            stu_col = df.columns[0]

        if not email_col:
            email_col = next((df.columns[i] for i, c in enumerate(cols_lower) if any(k == c or k in c for k in [
                "student_email", "student email", "gmail", "student_gmail", "email", "mail", "contact"
            ])), None)

        if not name_col:
            name_col = next((df.columns[i] for i, c in enumerate(cols_lower) if (not email_col or c != str(email_col).lower()) and (not stu_col or c != str(stu_col).lower()) and any(k == c or k in c for k in [
                "student_name", "student name", "candidate name", "full_name", "full name", "name"
            ])), None)

        # Mode A: Long Format (Row per question)
        if q_col and resp_col and q_col != resp_col:
            students = {}
            for idx, row in df.iterrows():
                s_id = str(row[stu_col]).strip() if pd.notna(row.get(stu_col)) else f"STU{1000 + idx}"
                if s_id.endswith(".0"):
                    s_id = s_id[:-2]

                s_name = str(row[name_col]).strip() if (name_col and pd.notna(row.get(name_col)) and str(row.get(name_col)).strip() and str(row.get(name_col)).strip() != "nan") else f"Student {s_id}"
                s_email = str(row[email_col]).strip() if (email_col and pd.notna(row.get(email_col)) and str(row.get(email_col)).strip() and str(row.get(email_col)).strip() != "nan") else "N/A"

                q_num = str(row[q_col]).strip() if pd.notna(row.get(q_col)) else f"Q{idx + 1}"
                if q_num.endswith(".0"):
                    q_num = q_num[:-2]
                q_label = q_num if q_num.lower().startswith("q") else f"Q{q_num}"

                resp_text = str(row[resp_col]).strip() if pd.notna(row.get(resp_col)) else ""

                if s_id not in students:
                    students[s_id] = {
                        "name": s_name,
                        "email": s_email,
                        "responses": []
                    }
                else:
                    if students[s_id]["name"].startswith("Student ") and not s_name.startswith("Student "):
                        students[s_id]["name"] = s_name
                    if students[s_id]["email"] == "N/A" and s_email != "N/A":
                        students[s_id]["email"] = s_email

                if resp_text and resp_text.lower() != "nan":
                    students[s_id]["responses"].append(f"Question {q_label}:\n{resp_text}")

            rows = []
            for s_id, s_data in students.items():
                rows.append({
                    "student_id": s_id,
                    "student_name": s_data["name"],
                    "student_email": s_data["email"],
                    "text": "\n\n".join(s_data["responses"])
                })
            return rows

        # Mode B: Wide Format (Matrix Table - each question is a separate column, e.g. Q1, Q2, Q3 or 6, 8)
        meta_cols = {str(c) for c in [stu_col, name_col, email_col] if c is not None}
        question_cols = [c for c in df.columns if str(c) not in meta_cols]

        if len(question_cols) > 0:
            rows = []
            for idx, row in df.iterrows():
                s_id = str(row[stu_col]).strip() if pd.notna(row.get(stu_col)) else f"STU{1000 + idx}"
                if s_id.endswith(".0"):
                    s_id = s_id[:-2]

                s_name = str(row[name_col]).strip() if (name_col and pd.notna(row.get(name_col)) and str(row.get(name_col)).strip() and str(row.get(name_col)).strip() != "nan") else f"Student {s_id}"
                s_email = str(row[email_col]).strip() if (email_col and pd.notna(row.get(email_col)) and str(row.get(email_col)).strip() and str(row.get(email_col)).strip() != "nan") else "N/A"

                responses = []
                for q_c in question_cols:
                    ans_val = str(row[q_c]).strip() if pd.notna(row.get(q_c)) else ""
                    if ans_val and ans_val.lower() != "nan" and ans_val != "-":
                        q_tag = str(q_c).strip()
                        if q_tag.endswith(".0"):
                            q_tag = q_tag[:-2]
                        if re.match(r'^\d+$', q_tag):
                            q_label = f"Question Q{q_tag}"
                        elif q_tag.lower().startswith('q') and re.match(r'^q\d+', q_tag.lower()):
                            q_label = f"Question {q_tag.upper()}"
                        elif q_tag.lower().startswith('question'):
                            q_label = q_tag
                        else:
                            q_label = f"Question {q_tag}"
                        responses.append(f"{q_label}:\n{ans_val}")

                compiled_text = "\n\n".join(responses) if responses else (str(row[question_cols[0]]).strip() if pd.notna(row.get(question_cols[0])) else "")

                rows.append({
                    "student_id": s_id,
                    "student_name": s_name,
                    "student_email": s_email,
                    "text": compiled_text
                })
            return rows

        return []
    except Exception as e:
        print(f"[FlexibleExcelParser Error] Submissions parsing failed on {file_path}: {e}")
        return []


def determine_anchor_type(score: float, max_score: float, explicit_anchor: Optional[str] = None) -> str:
    """Classifies a score into an anchor type: high, borderline, or low."""
    if explicit_anchor:
        clean = str(explicit_anchor).strip().lower()
        if clean in ["high", "borderline", "low", "other"]:
            return clean
        if "high" in clean: return "high"
        if "low" in clean: return "low"
        if "border" in clean or "mid" in clean: return "borderline"

    if max_score <= 0:
        return "borderline"

    ratio = score / max_score
    if ratio >= 0.8:
        return "high"
    elif ratio <= 0.4:
        return "low"
    return "borderline"


def parse_flexible_calibration(file_path: str) -> List[Dict[str, Any]]:
    """
    Template-tolerant parser for Excel/CSV Graded Calibration datasets.
    Supports identical column formats and header tolerances as ungraded submissions:
    - Long Format: Multiple rows per student with Question, Response, and Score columns.
      (e.g., ID Number | student_gma | student_nam | question_no | Response | Score)
    - Wide / General Format with Student, Question/Text, and Score.
    """
    try:
        header_row = detect_header_row(file_path)
        ext = Path(file_path).suffix.lower()

        if ext == ".csv":
            df = pd.read_csv(file_path, skiprows=header_row)
        else:
            df = pd.read_excel(file_path, skiprows=header_row)

        df = df.dropna(how="all")
        if df.empty:
            return []

        # Resolve Schema with intelligent Header + Content Scoring
        mapping, overall_conf, is_valid = resolve_schema_mapping(df, schema_type="calibration")
        print(f"[FlexibleExcelParser] Calibration Schema Resolution: {mapping} (Confidence: {overall_conf * 100:.1f}%)")

        stu_col = mapping.get("student_id")
        name_col = mapping.get("student_name")
        email_col = mapping.get("student_email")
        q_col = mapping.get("question_number")
        resp_col = mapping.get("student_response")
        score_col = mapping.get("examiner_score")
        max_sc_col = mapping.get("max_score")
        fb_col = mapping.get("examiner_feedback")
        anchor_col = mapping.get("anchor_type")

        cols_lower = [str(c).strip().lower() for c in df.columns]

        # Positional and alias fallbacks matching ungraded submissions
        if not stu_col and len(df.columns) > 0:
            stu_col = next((df.columns[i] for i, c in enumerate(cols_lower) if any(k in c for k in [
                "id number", "id_number", "id num", "id_num", "id no", "id_no",
                "student_id", "student id", "student_no", "matric", "id"
            ])), df.columns[0])

        if not email_col:
            email_col = next((df.columns[i] for i, c in enumerate(cols_lower) if any(k == c or k in c for k in [
                "student_email", "student email", "gmail", "student_gmail", "student_gma", "student gma", "email", "mail", "contact"
            ])), None)

        if not name_col:
            name_col = next((df.columns[i] for i, c in enumerate(cols_lower) if (not email_col or c != str(email_col).lower()) and (not stu_col or c != str(stu_col).lower()) and any(k == c or k in c for k in [
                "student_name", "student name", "student_nam", "student nam", "candidate name", "full_name", "full name", "name"
            ])), None)

        if not q_col:
            q_col = next((df.columns[i] for i, c in enumerate(cols_lower) if any(k in c for k in [
                "question_no", "question_n", "question no", "question", "q_no", "q_num"
            ])), None)

        if not resp_col:
            resp_col = next((df.columns[i] for i, c in enumerate(cols_lower) if (not score_col or c != str(score_col).lower()) and any(k in c for k in [
                "response", "answer", "student_answer", "student_response", "submission", "text", "work"
            ])), None)

        if not score_col:
            score_col = next((df.columns[i] for i, c in enumerate(cols_lower) if any(k in c for k in [
                "score", "human_score", "human score", "lecturer_score", "lecturer score",
                "examiner_score", "examiner score", "marks", "mark", "grade", "points"
            ])), None)

        if not resp_col or not score_col:
            print(f"[FlexibleExcelParser] Missing required columns in {file_path}: resp_col={resp_col}, score_col={score_col}")
            return []

        rows = []
        for idx, row in df.iterrows():
            # 1. Student ID
            raw_id = row.get(stu_col)
            s_id = str(raw_id).strip() if pd.notna(raw_id) else f"STU_{1001 + idx}"
            if s_id.endswith(".0"):
                s_id = s_id[:-2]
            if not s_id or s_id.lower() == "nan":
                s_id = f"STU_{1001 + idx}"

            # 2. Student Name
            raw_name = row.get(name_col) if name_col else None
            s_name = str(raw_name).strip() if pd.notna(raw_name) and str(raw_name).strip() and str(raw_name).strip().lower() != "nan" else f"Student {s_id}"

            # 3. Student Email
            raw_email = row.get(email_col) if email_col else None
            s_email = str(raw_email).strip() if pd.notna(raw_email) and str(raw_email).strip() and str(raw_email).strip().lower() != "nan" else "N/A"

            # 4. Question Number (normalized e.g. 6 -> Q6, Q8 -> Q8)
            raw_q = str(row.get(q_col)).strip() if q_col and pd.notna(row.get(q_col)) else f"Q{idx + 1}"
            if raw_q.endswith(".0"):
                raw_q = raw_q[:-2]
            clean_q = raw_q.upper()
            if not clean_q.startswith("Q") and clean_q.isdigit():
                clean_q = f"Q{clean_q}"

            # 5. Response Text
            raw_resp = row.get(resp_col)
            stu_text = str(raw_resp).strip() if pd.notna(raw_resp) else ""
            if stu_text.lower() == "nan":
                stu_text = ""

            # 6. Score
            raw_sc = row.get(score_col)
            try:
                score_val = round(float(raw_sc), 2)
            except (ValueError, TypeError):
                score_val = 0.0

            # 7. Max Score
            raw_max = row.get(max_sc_col) if max_sc_col else None
            if pd.notna(raw_max):
                try:
                    max_sc_val = round(float(raw_max), 2)
                except (ValueError, TypeError):
                    max_sc_val = 10.0
            else:
                max_sc_val = 10.0

            # 8. Feedback
            raw_fb = str(row.get(fb_col)).strip() if fb_col and pd.notna(row.get(fb_col)) else ""
            if raw_fb.lower() == "nan":
                raw_fb = ""
            if not raw_fb:
                raw_fb = f"Examiner baseline standard for {clean_q}. Awarded {score_val}/{max_sc_val} marks."

            # 9. Anchor Type
            explicit_anchor = str(row.get(anchor_col)).strip() if anchor_col and pd.notna(row.get(anchor_col)) else None
            anchor_val = determine_anchor_type(score_val, max_sc_val, explicit_anchor)

            rows.append({
                "student_id": s_id,
                "student_name": s_name,
                "student_email": s_email,
                "question_number": clean_q,
                "student_text": stu_text,
                "examiner_score": score_val,
                "max_score": max_sc_val,
                "examiner_feedback": raw_fb,
                "anchor_type": anchor_val
            })

        return rows
    except Exception as e:
        print(f"[FlexibleExcelParser Error] Calibration parsing failed on {file_path}: {e}")
        return []


