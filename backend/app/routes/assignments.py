import os
import uuid
import re
from typing import List, Optional
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Assignment, Submission
from ..schemas import AssignmentCreate, AssignmentResponse
from ..services.embedding import embedding_service
from ..services.document_parser import (
    extract_text_from_file, 
    parse_excel_rows, 
    smart_parse_rubric_text, 
    parse_excel_rubric,
    parse_separate_question_and_rubric_docs
)

router = APIRouter(prefix="/api/assignments", tags=["Assignments"])

TEMP_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


@router.get("", response_model=List[AssignmentResponse])
def get_assignments(db: Session = Depends(get_db)):
    """Fetch all active assignments with submission counts and average score."""
    assignments = db.query(Assignment).all()
    for assign in assignments:
        subs = db.query(Submission).filter(Submission.assignment_id == assign.id).all()
        assign.total_submissions = len(subs)
        scores = [s.score for s in subs if s.score is not None]
        assign.average_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    return assignments


@router.get("/{assignment_id}", response_model=AssignmentResponse)
def get_assignment_detail(assignment_id: str, db: Session = Depends(get_db)):
    """Fetch details for a specific assignment."""
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail="Assignment not found")
    subs = db.query(Submission).filter(Submission.assignment_id == assign.id).all()
    assign.total_submissions = len(subs)
    scores = [s.score for s in subs if s.score is not None]
    assign.average_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    return assign


@router.get("/qc-settings")
def get_qc_settings():
    """Retrieve current Quality Control Audit settings."""
    enable_qc = os.getenv("ENABLE_RANDOM_QC_AUDIT", "false").lower() in ["true", "1", "yes"]
    qc_rate = float(os.getenv("QC_AUDIT_RATE", "0.05"))
    return {
        "enable_random_qc": enable_qc,
        "qc_audit_rate": qc_rate
    }


@router.post("/qc-settings")
def update_qc_settings(data: dict):
    """Update Quality Control Audit settings (ON/OFF toggle & sampling percentage rate)."""
    enable_qc = bool(data.get("enable_random_qc", False))
    qc_rate = float(data.get("qc_audit_rate", 0.05))
    os.environ["ENABLE_RANDOM_QC_AUDIT"] = "true" if enable_qc else "false"
    os.environ["QC_AUDIT_RATE"] = str(qc_rate)
    return {
        "message": "Quality Control Audit settings updated successfully",
        "enable_random_qc": enable_qc,
        "qc_audit_rate": qc_rate
    }


@router.get("/{assignment_id}/vector-store")
def get_assignment_vector_store(assignment_id: str):
    """
    Visualizes ChromaDB vector embeddings and collection data for an assignment.
    """
    coll = embedding_service.get_assignment_collection(assignment_id)
    if not coll:
        return {
            "assignment_id": assignment_id,
            "status": "not_indexed",
            "message": f"No ChromaDB collection found for {assignment_id}",
            "vector_count": 0,
            "vectors": []
        }

    count = coll.count()
    if count == 0:
        return {
            "assignment_id": assignment_id,
            "status": "empty",
            "collection_name": coll.name,
            "vector_count": 0,
            "vectors": []
        }

    data = coll.get(include=["documents", "metadatas", "embeddings"])
    
    formatted_vectors = []
    docs = data.get("documents") or []
    ids = data.get("ids") or []
    metadatas = data.get("metadatas") or []
    raw_embeddings = data.get("embeddings")
    embeddings = list(raw_embeddings) if raw_embeddings is not None and len(raw_embeddings) > 0 else []

    for i in range(len(docs)):
        emb = embeddings[i] if i < len(embeddings) else []
        emb_list = [float(v) for v in emb] if hasattr(emb, "__iter__") else []
        
        formatted_vectors.append({
            "chunk_id": ids[i] if i < len(ids) else f"chunk_{i+1}",
            "metadata": metadatas[i] if i < len(metadatas) else {},
            "text_content": docs[i],
            "embedding_dimensions": len(emb_list),
            "vector_preview": [round(v, 4) for v in emb_list[:8]] + ["..."] if emb_list else []
        })

    return {
        "assignment_id": assignment_id,
        "collection_name": coll.name,
        "status": "indexed",
        "vector_count": count,
        "vectors": formatted_vectors
    }


@router.post("", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
def create_assignment(payload: AssignmentCreate, db: Session = Depends(get_db)):
    """Create a new assignment and index its rubric & model answers into ChromaDB."""
    assign_id = f"assign-{uuid.uuid4().hex[:6]}"

    # Normalize rubric_data: generate stable question_id and per-question prompt & model_answer
    normalized_rubric_data = []
    if payload.rubric_data:
        for idx, item in enumerate(payload.rubric_data):
            q_num = item.get("question_number") or f"Q{idx + 1}"
            q_num_clean = q_num.lower().replace(" ", "")
            question_id = item.get("question_id") or f"{assign_id}-{q_num_clean}"
            max_score = float(item.get("max_score", 10.0))
            prompt = item.get("prompt") or item.get("text") or (item.get("criteria", [{}])[0].get("description") if item.get("criteria") else "")
            model_ans = item.get("model_answer") or (item.get("criteria", [{}])[0].get("model_answer") if item.get("criteria") else "")
            
            q_data = {
                "question_id": question_id,
                "question_number": q_num,
                "max_score": max_score,
                "prompt": prompt,
                "model_answer": model_ans
            }
            if item.get("criteria") and len(item.get("criteria")) > 1:
                q_data["criteria"] = item["criteria"]
                
            normalized_rubric_data.append(q_data)

    new_assign = Assignment(
        id=assign_id,
        title=payload.title,
        course_code=payload.course_code,
        due_date=payload.due_date or "",
        rubric_data=normalized_rubric_data,
        model_answer="",
        status="active",
        total_submissions=0,
        average_score=0.0
    )
    db.add(new_assign)
    db.commit()
    db.refresh(new_assign)

    # Index Rubric Criteria & Model Answers into ChromaDB Vector Database
    embedding_service.index_assignment_reference(
        assignment_id=new_assign.id,
        rubric_data=new_assign.rubric_data
    )

    return new_assign


@router.post("/parse-rubric-file")
async def parse_rubric_file(files: List[UploadFile] = File(...)):
    """
    Parses 1 to 3 uploaded rubric files (.pdf, .docx, .xlsx, .csv).
    Intelligently handles separate Question and Rubric file uploads.
    """
    extracted_items = []
    file_names = []
    excel_questions = []

    for file in files:
        file_ext = Path(file.filename).suffix.lower()
        temp_path = TEMP_DIR / f"rubric_{uuid.uuid4().hex[:6]}{file_ext}"

        try:
            with open(temp_path, "wb") as buffer:
                content = await file.read()
                buffer.write(content)
            
            if file_ext in [".xlsx", ".xls", ".csv"]:
                eqs = parse_excel_rubric(str(temp_path))
                if eqs:
                    excel_questions.extend(eqs)
            
            txt = extract_text_from_file(str(temp_path))
            is_rubric_doc = bool(re.search(r'Marking\s+Rubric|Rubric|Answer\s+Scheme|Model\s+Answer', txt, re.IGNORECASE))
            
            extracted_items.append({
                "file_name": file.filename,
                "text": txt,
                "is_rubric": is_rubric_doc
            })
            file_names.append(file.filename)
            
            if temp_path.exists():
                try: os.remove(temp_path)
                except Exception: pass
        except Exception as e:
            print(f"[Rubric Parse Error] {file.filename}: {e}")

    if excel_questions:
        parsed_questions = excel_questions
        full_text = "\n\n".join([f"{q['question_number']}: {q['text']}\nAnswer: {q['modelAnswer']}" for q in excel_questions])
    else:
        question_docs = [item["text"] for item in extracted_items if not item["is_rubric"]]
        rubric_docs = [item["text"] for item in extracted_items if item["is_rubric"]]

        if question_docs and rubric_docs:
            q_text = "\n\n".join(question_docs)
            r_text = "\n\n".join(rubric_docs)
            parsed_questions = parse_separate_question_and_rubric_docs(q_text, r_text)
            full_text = f"{q_text}\n\n{r_text}"
        else:
            full_text = "\n\n".join([item["text"] for item in extracted_items])
            parsed_questions = smart_parse_rubric_text(full_text)

    # Check if marking rubric / answer scheme is present
    rubric_keywords = [r"rubric", r"marking", r"model answer", r"answer scheme", r"solution", r"criteria", r"one mark", r"advantages", r"answer"]
    has_rubric = any(re.search(kw, full_text, re.IGNORECASE) for kw in rubric_keywords)

    rubric_warning = None
    if not has_rubric:
        rubric_warning = "⚠️ Warning: No marking rubric or answer scheme was detected in the uploaded file(s). Please review and add model answer criteria for AI grading."

    return {
        "file_names": file_names,
        "extracted_text": full_text,
        "parsed_questions": parsed_questions,
        "has_rubric": has_rubric,
        "rubric_warning": rubric_warning,
        "message": f"Parsed {len(files)} file(s). Extracted {len(parsed_questions)} questions."
    }


@router.get("/{assignment_id}/export-csv")
def export_assignment_csv(assignment_id: str, db: Session = Depends(get_db)):
    """
    Exports all student grades for an assignment as a structured CSV file matching academic marking sheets.
    Dynamically includes columns for every question/sub-part in the rubric.
    """
    import io
    import csv
    from fastapi.responses import StreamingResponse

    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    submissions = db.query(Submission).filter(Submission.assignment_id == assignment_id).all()

    # Collect all unique question numbers from rubric and submission breakdowns
    question_keys = []
    rubric_data = assignment.rubric_data or []
    for item in rubric_data:
        q_num = item.get("question_number") or item.get("questionNumber")
        if q_num and q_num not in question_keys:
            question_keys.append(q_num)

    for sub in submissions:
        fb = sub.feedback if isinstance(sub.feedback, dict) else {}
        bd = fb.get("breakdown", [])
        for item in bd:
            if isinstance(item, dict):
                q_num = item.get("question_number")
                if q_num and q_num not in question_keys:
                    question_keys.append(q_num)

    # Build CSV Header
    header = [
        "Student ID",
        "Student Name",
        "Student Email",
        "Submission File",
        "Total Score",
        "Max Score",
        "Percentage (%)",
        "Status",
        "AI Confidence",
    ]
    # Add per-question columns
    for qk in question_keys:
        header.append(f"{qk} Score")

    header.extend([
        "AI Evaluation Summary",
        "Audit Flag Reasons",
        "Graded Timestamp"
    ])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)

    # Compute Total Rubric Max
    total_rubric_max = sum(float(item.get("max_score", item.get("maxMark", 10.0))) for item in rubric_data) if rubric_data else 20.0

    for sub in submissions:
        score_val = sub.score if sub.score is not None else 0.0
        pct = f"{round((score_val / total_rubric_max) * 100, 1)}%" if total_rubric_max > 0 else "0.0%"
        conf = f"{int(sub.confidence_score * 100)}%" if sub.confidence_score is not None else "N/A"
        
        fb = sub.feedback if isinstance(sub.feedback, dict) else {}
        summary = fb.get("summary", "")
        flag_reasons = "; ".join(fb.get("flag_reasons", []))
        
        # Build score dictionary for per-question columns
        q_scores = {}
        for item in fb.get("breakdown", []):
            if isinstance(item, dict):
                qk = item.get("question_number")
                if qk:
                    q_scores[qk] = item.get("score_awarded", 0.0)

        row = [
            sub.student_id,
            sub.student_name or "N/A",
            getattr(sub, "student_email", None) or "N/A",
            sub.file_name,
            score_val,
            total_rubric_max,
            pct,
            sub.status,
            conf,
        ]
        # Append per-question scores
        for qk in question_keys:
            row.append(q_scores.get(qk, 0.0))

        row.extend([
            summary,
            flag_reasons,
            sub.graded_at.strftime("%Y-%m-%d %H:%M:%S") if sub.graded_at else "Unassessed"
        ])
        writer.writerow(row)

    output.seek(0)
    clean_code = re.sub(r'[^a-zA-Z0-9_-]', '', assignment.course_code or 'Assignment')
    filename = f"{clean_code}_Grades.csv"
    headers = {
        'Content-Disposition': f'attachment; filename="{filename}"'
    }
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)
