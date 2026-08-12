import os
import re
from pathlib import Path
from typing import List, Dict, Any


def extract_text_from_file(file_path: str) -> str:
    """
    Extracts plain text from PDF, DOCX, XLSX, CSV, or TXT files.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    
    if ext == ".pdf":
        return _extract_pdf(file_path)
    elif ext in [".docx", ".doc"]:
        return _extract_docx(file_path)
    elif ext in [".xlsx", ".xls", ".csv"]:
        return _extract_excel(file_path)
    elif ext in [".txt", ".md"]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    else:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


def calculate_question_max_mark(prompt_text: str) -> float:
    """
    Precision extractor for question max marks from PDF & DOCX prompt text ONLY:
    1. Looks for "(Total: X marks)", "[Total X Marks]", "Total: X marks".
    2. Sums parenthesized sub-part marks e.g. "(5 marks)", "(2 marks)", "[5 pts]".
    3. Handles multiplier patterns like "(5 marks each)".
    4. Filters out sub-part labels like (1), (a).
    """
    if not prompt_text:
        return 10.0

    prompt_only = re.split(r'Marking\s+Rubric|Answer\s+Scheme|Model\s+Answer|Marking\s+Scheme|Rubric', prompt_text, flags=re.IGNORECASE)[0].strip()

    # 1. Total mark explicitly stated e.g. "(Total: 25 marks)", "[Total 20 Marks]", "Total: 10 marks"
    total_m = re.search(r'(?:total\s*:?\s*)(\d+)\s*(?:marks?|pts?|points?)?', prompt_only, re.IGNORECASE)
    if total_m:
        val = float(total_m.group(1))
        if val > 0: return val

    # 2. Sum parenthesized / bracketed sub-part marks e.g. "(5 marks)", "[2 pts]"
    part_marks = re.findall(r'[\(\[]\s*(\d+)\s*(?:marks?|pts?|points?)\s*[\)\]]', prompt_only, re.IGNORECASE)
    if part_marks:
        explicit_marks = [int(m) for m in part_marks if re.search(r'[\(\[]\s*' + m + r'\s*(?:marks?|pts?|points?)\s*[\)\]]', prompt_only, re.IGNORECASE)]
        if explicit_marks:
            return float(sum(explicit_marks))

    # 3. Multiplier patterns e.g. "(5 marks each)" or "5 marks each"
    each_m = re.search(r'(\d+)\s*marks?\s*each', prompt_only, re.IGNORECASE)
    if each_m:
        per_part = int(each_m.group(1))
        parts_count = len(re.findall(r'\([a-z0-9]+\)', prompt_only, re.IGNORECASE))
        if parts_count > 0:
            return float(per_part * parts_count)

    # 4. Trailing "X marks" pattern
    end_marks = re.findall(r'\b(\d+)\s*(?:marks?|pts?|points?)\b', prompt_only, re.IGNORECASE)
    if end_marks:
        total = sum(int(m) for m in end_marks)
        if total > 0: return float(total)

    return 10.0


def parse_excel_rubric(file_path: str) -> List[Dict[str, Any]]:
    """
    Parses an Excel (.xlsx/.csv) rubric table containing columns like:
    question_n/question_no, question, answer/rubric, max_mark/marks.
    """
    try:
        import pandas as pd
        ext = Path(file_path).suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)

        cols = [str(c).strip().lower() for c in df.columns]
        
        q_num_col = next((df.columns[i] for i, c in enumerate(cols) if any(k in c for k in ["question_n", "question_no", "q_num", "q_no", "num"])), None)
        q_text_col = next((df.columns[i] for i, c in enumerate(cols) if c in ["question", "prompt", "question_text", "criteria"] or ("question" in c and c != q_num_col)), None)
        ans_col = next((df.columns[i] for i, c in enumerate(cols) if any(k in c for k in ["answer", "rubric", "model_answer", "marking", "solution"])), None)
        mark_col = next((df.columns[i] for i, c in enumerate(cols) if any(k in c for k in ["max_mark", "mark", "score", "max_score", "points"])), None)

        questions = []
        for idx, row in df.iterrows():
            q_num_val = str(row[q_num_col]).strip() if q_num_col and pd.notna(row[q_num_col]) else str(idx + 1)
            if q_num_val.endswith('.0'):
                q_num_val = q_num_val[:-2]

            q_text_val = str(row[q_text_col]).strip() if q_text_col and pd.notna(row[q_text_col]) else f"Question {q_num_val}"
            ans_val = str(row[ans_col]).strip() if ans_col and pd.notna(row[ans_col]) else q_text_val
            
            try:
                max_mark_val = float(row[mark_col]) if mark_col and pd.notna(row[mark_col]) else 10.0
            except Exception:
                max_mark_val = 10.0

            q_label = q_num_val if q_num_val.lower().startswith("q") else f"Q{q_num_val}"

            questions.append({
                "id": idx + 1,
                "question_number": q_label,
                "text": q_text_val,
                "maxMark": max_mark_val if max_mark_val > 0 else 10.0,
                "modelAnswer": ans_val
            })

        return questions
    except Exception as e:
        print(f"[DocumentParser Error] Excel rubric parsing failed on {file_path}: {e}")
        return []


def parse_separate_question_and_rubric_docs(q_doc: str, r_doc: str) -> List[Dict[str, Any]]:
    """
    Pairs a Question Paper document with a separate Marking Rubric document for DOCX & PDF files.
    """
    q_matches = list(re.finditer(r"(?:^|\n|\s{2,})(?:Question|Q)?\s*(\d+)[\.\s]", q_doc, re.IGNORECASE))
    if not q_matches:
        q_matches = list(re.finditer(r"(?:Question|Q)\s*(\d+)", q_doc, re.IGNORECASE))
        
    parsed = []
    seen = set()

    for i in range(len(q_matches)):
        q_num = q_matches[i].group(1)
        if q_num in seen:
            continue
        seen.add(q_num)

        start = q_matches[i].start()
        next_start = len(q_doc)
        for j in range(i + 1, len(q_matches)):
            if q_matches[j].group(1) != q_num:
                next_start = q_matches[j].start()
                break

        prompt_text = q_doc[start:next_start].strip()

        # Find exact "Marking Rubric for Question X" section in r_doc
        m_rubric = re.search(r"Marking\s+(?:Rubric\s+)?for\s+(?:Question|Q)?\s*" + q_num, r_doc, re.IGNORECASE)
        if m_rubric:
            r_start = m_rubric.start()
            r_all = list(re.finditer(r"Marking\s+(?:Rubric\s+)?for\s+(?:Question|Q)?\s*\d+", r_doc, re.IGNORECASE))
            r_end = len(r_doc)
            for rm in r_all:
                if rm.start() > r_start:
                    r_end = rm.start()
                    break
            rubric_text = r_doc[r_start:r_end].strip()
        else:
            rubric_text = prompt_text

        total_marks = calculate_question_max_mark(prompt_text)

        parsed.append({
            "id": len(parsed) + 1,
            "question_number": f"Q{q_num}",
            "text": prompt_text,
            "maxMark": total_marks,
            "modelAnswer": rubric_text
        })

    return parsed


def smart_parse_rubric_text(raw_text: str) -> List[Dict[str, Any]]:
    """
    Intelligently splits raw PDF/Docx text into distinct Question blocks (e.g. Question 6, Question 8).
    """
    clean_text = re.sub(r'--- Page \d+ ---', '', raw_text)
    clean_text = re.sub(r'[\u2060\u200b\ufeff]', '', clean_text)
    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()

    q_num_keys = ["question_no", "question_n", "q_num", "q_no", "num"]
    q_text_keys = ["question_text", "question", "prompt", "criteria"] 
    ans_keys = ["model_answer", "answer", "rubric", "marking", "solution"]
    mark_keys = ["max_score", "max_mark", "mark", "score", "points"]

    def _build_pattern(keys):
        sorted_keys = sorted(keys, key=len, reverse=True)
        # format eg.(?:question_text|question|prompt|criteria)\s*:
        return r"(?:" + "|".join(sorted_keys) + r")\s*:"

    q_num_regex = _build_pattern(q_num_keys)
    q_text_regex = _build_pattern(q_text_keys)
    ans_regex = _build_pattern(ans_keys)
    mark_regex = _build_pattern(mark_keys)

    if re.search(q_num_regex, raw_text, re.IGNORECASE) and re.search(q_text_regex, raw_text, re.IGNORECASE):
        parsed = []
        
        blocks = re.split(q_num_regex, raw_text, flags=re.IGNORECASE)
        
        for block in blocks:
            if not block.strip():
                continue
            
            # 1. Extract the question number (when block starts with a number)
            q_num_match = re.search(r'(\d+)', block.strip())
            q_num = q_num_match.group(1) if q_num_match else str(len(parsed) + 1)
            
            # 2. Extract the question text (stop when encountering any answer label, mark label, or end of block)
            q_text = ""
            q_text_pattern = f"{q_text_regex}\\s*(.*?)(?={ans_regex}|{mark_regex}|$)"
            q_text_match = re.search(q_text_pattern, block, flags=re.IGNORECASE | re.DOTALL)
            if q_text_match:
                q_text = q_text_match.group(1).strip()
                
            # 3. Extract the model answer (stop when encountering any mark label or end of block)
            ans_text = ""
            ans_text_pattern = f"{ans_regex}\\s*(.*?)(?={mark_regex}|$)"
            ans_text_match = re.search(ans_text_pattern, block, flags=re.IGNORECASE | re.DOTALL)
            if ans_text_match:
                ans_text = ans_text_match.group(1).strip()
                
            # 4. Extract the max mark
            mark_val = 10.0
            mark_pattern = f"{mark_regex}\\s*(\\d+(\\.\\d+)?)"
            mark_match = re.search(mark_pattern, block, flags=re.IGNORECASE)
            if mark_match:
                mark_val = float(mark_match.group(1))
                
            # Exclude faulty parses caused by empty blocks at the beginning of the document
            if not q_text and not ans_text:
                continue
                
            parsed.append({
                "id": len(parsed) + 1,
                "question_number": f"Q{q_num}",
                "text": q_text,
                "maxMark": mark_val,
                "modelAnswer": ans_text
            })
        
        if parsed:
            return parsed


def parse_excel_rows(file_path: str) -> List[Dict[str, Any]]:
    """
    Parses an Excel (.xlsx/.csv) dataset file containing student responses.
    Supports columns: Student_ID / student_id, question_no / question_n, Response / response / answer.
    Groups responses by Student_ID so all answers for a student are combined into one submission record.
    """
    try:
        import pandas as pd
        ext = Path(file_path).suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)

        cols = [str(c).strip().lower() for c in df.columns]
        
        stu_col = next((df.columns[i] for i, c in enumerate(cols) if any(k in c for k in ["student_id", "student_no", "student", "stu_id", "id"])), df.columns[0])
        q_col = next((df.columns[i] for i, c in enumerate(cols) if any(k in c for k in ["question_no", "question_n", "question", "q_no", "q_num"])), None)
        resp_col = next((df.columns[i] for i, c in enumerate(cols) if any(k in c for k in ["response", "answer", "student_answer", "submission", "text"])), df.columns[-1])

        # Group by Student ID if question_no column exists
        if q_col:
            students = {}
            for idx, row in df.iterrows():
                s_id = str(row[stu_col]).strip() if pd.notna(row[stu_col]) else f"STU{1000 + idx}"
                if s_id.endswith(".0"): s_id = s_id[:-2]

                q_num = str(row[q_col]).strip() if pd.notna(row[q_col]) else f"Q{idx + 1}"
                if q_num.endswith(".0"): q_num = q_num[:-2]
                q_label = q_num if q_num.lower().startswith("q") else f"Q{q_num}"

                resp_text = str(row[resp_col]).strip() if pd.notna(row[resp_col]) else ""

                if s_id not in students:
                    students[s_id] = []
                students[s_id].append(f"Question {q_label}:\n{resp_text}")

            rows = []
            for s_id, resp_list in students.items():
                rows.append({
                    "student_id": s_id,
                    "student_name": f"Student {s_id}",
                    "text": "\n\n".join(resp_list)
                })
            return rows

        # Fallback for single-row per student format
        rows = []
        for idx, row in df.iterrows():
            row_dict = {str(k).strip().lower(): str(v) for k, v in row.items() if pd.notna(v)}
            
            student_id = next((str(row_dict[k]) for k in row_dict if "id" in k or "student" in k or "num" in k), f"STU{1000 + idx}")
            student_name = next((str(row_dict[k]) for k in row_dict if "name" in k or "student" in k), f"Student {idx + 1}")
            
            text_parts = [f"{k.capitalize()}: {v}" for k, v in row_dict.items() if k not in ["student_id", "id", "student_name", "name"]]
            full_text = "\n".join(text_parts) if text_parts else str(row.to_dict())

            rows.append({
                "student_id": student_id,
                "student_name": student_name,
                "text": full_text
            })
        return rows
    except Exception as e:
        print(f"[DocumentParser Error] Excel row parsing failed: {e}")
        return []


def _extract_pdf(file_path: str) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        extracted = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                text = re.sub(r'[\u2060\u200b\ufeff]', '', text)
                extracted.append(text)
        
        full = "\n\n".join(extracted)
        return re.sub(r'\n{3,}', '\n\n', full).strip()
    except Exception as e:
        print(f"[DocumentParser Error] PyPDF failed on {file_path}: {e}")
        return ""


def _extract_docx(file_path: str) -> str:
    try:
        import docx
        doc = docx.Document(file_path)
        extracted = []
        
        # Extract paragraph text
        for p in doc.paragraphs:
            if p.text.strip():
                extracted.append(p.text.strip())
                
        # Extract Word table cell text if present
        for table in doc.tables:
            for row in table.rows:
                row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_cells:
                    extracted.append(" | ".join(row_cells))

        full_txt = "\n".join(extracted)
        return re.sub(r'\n{3,}', '\n\n', full_txt).strip()
    except Exception as e:
        print(f"[DocumentParser Error] docx parsing failed on {file_path}: {e}")
        return ""


def _extract_excel(file_path: str) -> str:
    try:
        import pandas as pd
        ext = Path(file_path).suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
        return df.to_string()
    except Exception as e:
        print(f"[DocumentParser Error] excel parsing failed on {file_path}: {e}")
        return ""
