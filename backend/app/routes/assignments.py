import os
import uuid
import re
from typing import List, Optional
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Assignment, Submission, CalibrationSet, CalibrationExample
from ..schemas import (
    AssignmentCreate, 
    AssignmentResponse, 
    AssignmentUpdate, 
    CalibrationExampleCreate, 
    CalibrationExampleResponse, 
    CalibrationStatusResponse, 
    CalibrationQuestionStatus
)
from ..services.embedding import embedding_service
from ..services.document_parser import (
    extract_text_from_file, 
    parse_excel_rows, 
    smart_parse_rubric_text, 
    parse_excel_rubric,
    parse_separate_question_and_rubric_docs
)
from ..services.calibration_importer import import_graded_calibration_data

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
    return assign


@router.patch("/{assignment_id}", response_model=AssignmentResponse)
def update_assignment(assignment_id: str, payload: AssignmentUpdate, db: Session = Depends(get_db)):
    """Renames or updates an assignment's title, course_code, due_date, or calibration settings."""
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail="Assignment not found")

    if payload.title is not None and payload.title.strip():
        assign.title = payload.title.strip()
    if payload.course_code is not None and payload.course_code.strip():
        assign.course_code = payload.course_code.strip()
    if payload.due_date is not None:
        assign.due_date = payload.due_date.strip()
    if payload.calibration_enabled is not None:
        assign.calibration_enabled = payload.calibration_enabled
    if payload.calibration_sample_size is not None:
        assign.calibration_sample_size = payload.calibration_sample_size
    if payload.calibration_settings is not None:
        assign.calibration_settings = payload.calibration_settings

    db.commit()
    db.refresh(assign)

    subs = db.query(Submission).filter(Submission.assignment_id == assign.id).all()
    assign.total_submissions = len(subs)
    scores = [s.score for s in subs if s.score is not None]
    assign.average_score = round(sum(scores) / len(scores), 1) if scores else 0.0

    return assign


@router.get("/qc-settings")
def get_qc_settings():
    """Retrieve current Quality Control Audit and Confidence Threshold settings."""
    enable_qc = os.getenv("ENABLE_RANDOM_QC_AUDIT", "false").lower() in ["true", "1", "yes"]
    qc_rate = float(os.getenv("QC_AUDIT_RATE", "0.05"))
    conf_thresh = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
    return {
        "enable_random_qc": enable_qc,
        "qc_audit_rate": qc_rate,
        "audit_percentage": int(round(qc_rate * 100)) if enable_qc else 0,
        "confidence_threshold": int(round(conf_thresh * 100)) if conf_thresh <= 1.0 else int(conf_thresh)
    }


@router.post("/qc-settings")
def update_qc_settings(data: dict):
    """Update Quality Control Audit settings and Low Confidence Threshold."""
    if not isinstance(data, dict):
        data = {}

    # Support audit_percentage (0-100), enable_random_qc (bool), and qc_audit_rate (0.0-1.0)
    if "audit_percentage" in data:
        audit_pct = float(data["audit_percentage"])
        enable_qc = audit_pct > 0
        qc_rate = audit_pct / 100.0
    elif "qc_audit_rate" in data:
        qc_rate = float(data.get("qc_audit_rate", 0.05))
        enable_qc = bool(data.get("enable_random_qc", qc_rate > 0))
    else:
        enable_qc = bool(data.get("enable_random_qc", False))
        qc_rate = float(data.get("qc_audit_rate", 0.05))

    conf_thresh_raw = float(data.get("confidence_threshold", 75))
    conf_thresh = conf_thresh_raw / 100.0 if conf_thresh_raw > 1.0 else conf_thresh_raw

    os.environ["ENABLE_RANDOM_QC_AUDIT"] = "true" if enable_qc else "false"
    os.environ["QC_AUDIT_RATE"] = str(qc_rate)
    os.environ["CONFIDENCE_THRESHOLD"] = str(conf_thresh)

    return {
        "message": "Quality Control Audit & Confidence settings updated successfully",
        "enable_random_qc": enable_qc,
        "qc_audit_rate": qc_rate,
        "audit_percentage": int(round(qc_rate * 100)) if enable_qc else 0,
        "confidence_threshold": int(round(conf_thresh * 100))
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
        average_score=0.0,
        calibration_enabled=payload.calibration_enabled or False,
        calibration_sample_size=payload.calibration_sample_size or 3,
        calibration_settings=payload.calibration_settings
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


# =====================================================================
# QUESTION-LEVEL CALIBRATION & FEW-SHOT EXEMPLAR ENDPOINTS
# =====================================================================

@router.get("/{assignment_id}/calibration", response_model=CalibrationStatusResponse)
def get_assignment_calibration_status(assignment_id: str, db: Session = Depends(get_db)):
    """
    Returns question-level calibration status, versioning, exemplar lists, and designated calibration sample submissions.
    """
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail="Assignment not found")

    # Determine question keys from rubric_data
    rubric_items = assign.rubric_data or []
    question_keys = []
    for idx, item in enumerate(rubric_items):
        q_num = item.get("question_number") or f"Q{idx + 1}"
        question_keys.append(q_num.strip().upper())

    # Fallback if no rubric items yet: extract distinct from calibration examples
    all_examples = db.query(CalibrationExample).filter(
        CalibrationExample.assignment_id == assignment_id
    ).order_by(CalibrationExample.created_at.asc()).all()

    for ex in all_examples:
        q_k = ex.question_number.strip().upper()
        if q_k not in question_keys:
            question_keys.append(q_k)

    target_size = assign.calibration_sample_size or 3
    cal_sets = {
        cs.question_number.strip().upper(): cs 
        for cs in db.query(CalibrationSet).filter(CalibrationSet.assignment_id == assignment_id).all()
    }

    questions_status = []
    for q_no in question_keys:
        q_examples = [ex for ex in all_examples if ex.question_number.strip().upper() == q_no]
        count = len(q_examples)
        c_set = cal_sets.get(q_no)
        c_version = c_set.version if c_set else 1

        if count == 0:
            status_label = "zero_shot"
        elif count < target_size:
            status_label = "few_shot_available"
        else:
            status_label = "calibrated"

        questions_status.append(CalibrationQuestionStatus(
            question_number=q_no,
            sample_count=count,
            target_count=target_size,
            status=status_label,
            version=c_version,
            examples=q_examples
        ))

    # Retrieve all submissions tagged as calibration samples
    cal_sub_ids = [
        s.id for s in db.query(Submission).filter(
            Submission.assignment_id == assignment_id,
            Submission.is_calibration_sample == True
        ).all()
    ]

    return CalibrationStatusResponse(
        assignment_id=assignment_id,
        calibration_enabled=bool(assign.calibration_enabled),
        calibration_sample_size=target_size,
        total_calibrated_examples=len(all_examples),
        questions=questions_status,
        calibration_sample_submission_ids=cal_sub_ids
    )


@router.post("/{assignment_id}/calibration/settings")
def update_assignment_calibration_settings(assignment_id: str, payload: dict, db: Session = Depends(get_db)):
    """Update calibration settings (enable/disable, target sample size)."""
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail="Assignment not found")

    if "calibration_enabled" in payload:
        assign.calibration_enabled = bool(payload["calibration_enabled"])
    if "calibration_sample_size" in payload:
        assign.calibration_sample_size = max(1, min(10, int(payload["calibration_sample_size"])))
    if "calibration_settings" in payload:
        assign.calibration_settings = payload["calibration_settings"]

    db.commit()
    return {
        "message": "Calibration settings updated successfully",
        "assignment_id": assignment_id,
        "calibration_enabled": assign.calibration_enabled,
        "calibration_sample_size": assign.calibration_sample_size
    }


@router.post("/{assignment_id}/calibration/examples", response_model=CalibrationExampleResponse)
def save_calibration_example(assignment_id: str, payload: CalibrationExampleCreate, db: Session = Depends(get_db)):
    """
    Saves an examiner-marked response as an official calibration example for a specific question.
    Updates the question-level CalibrationSet version for strict audit reproducibility.
    """
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail="Assignment not found")

    clean_q_no = payload.question_number.strip().upper()

    # Find or initialize question-level CalibrationSet
    cal_set = db.query(CalibrationSet).filter(
        CalibrationSet.assignment_id == assignment_id,
        CalibrationSet.question_number == clean_q_no
    ).first()

    if not cal_set:
        cal_set = CalibrationSet(
            assignment_id=assignment_id,
            question_number=clean_q_no,
            version=1,
            is_active=True
        )
        db.add(cal_set)
        db.commit()
        db.refresh(cal_set)
    else:
        # Increment version whenever a new example is added
        cal_set.version += 1
        db.commit()
        db.refresh(cal_set)

    new_example = CalibrationExample(
        assignment_id=assignment_id,
        calibration_set_id=cal_set.id,
        submission_id=payload.submission_id,
        question_number=clean_q_no,
        student_text=payload.student_text.strip(),
        examiner_score=round(float(payload.examiner_score), 2),
        max_score=round(float(payload.max_score), 2),
        examiner_feedback=(payload.examiner_feedback or "").strip(),
        anchor_type=(payload.anchor_type or "borderline").lower(),
        version=cal_set.version
    )
    db.add(new_example)
    db.commit()
    db.refresh(new_example)

    return new_example


@router.delete("/{assignment_id}/calibration/examples/{example_id}")
def delete_calibration_example(assignment_id: str, example_id: int, db: Session = Depends(get_db)):
    """
    Deletes a calibration example and increments question-level calibration version.
    """
    ex = db.query(CalibrationExample).filter(
        CalibrationExample.id == example_id,
        CalibrationExample.assignment_id == assignment_id
    ).first()

    if not ex:
        raise HTTPException(status_code=404, detail="Calibration example not found")

    clean_q_no = ex.question_number.strip().upper()
    cal_set = db.query(CalibrationSet).filter(
        CalibrationSet.assignment_id == assignment_id,
        CalibrationSet.question_number == clean_q_no
    ).first()

    if cal_set:
        cal_set.version += 1

    db.delete(ex)
    db.commit()

    return {
        "message": f"Calibration example {example_id} deleted successfully",
        "question_number": clean_q_no,
        "new_version": cal_set.version if cal_set else 1
    }


@router.post("/{assignment_id}/calibration/import-graded")
async def import_graded_submissions(
    assignment_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Imports already-graded student submissions from Excel (.xlsx/.xls) or CSV (.csv).
    Automatically registers submissions as calibration samples,
    and creates authoritative CalibrationExample records for few-shot prompt injection.
    """
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail=f"Assignment '{assignment_id}' not found")

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in [".xlsx", ".xls", ".csv"]:
        raise HTTPException(status_code=400, detail="Invalid file format. Please upload an Excel (.xlsx/.xls) or CSV (.csv) file.")

    temp_filename = f"cal_import_{uuid.uuid4().hex[:6]}_{file.filename}"
    temp_path = TEMP_DIR / temp_filename
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        result = import_graded_calibration_data(
            file_path=str(temp_path),
            assignment_id=assignment_id,
            original_filename=file.filename,
            db=db
        )
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import graded submissions: {str(e)}")
    finally:
        if temp_path.exists():
            try: os.remove(temp_path)
            except Exception: pass


@router.get("/{assignment_id}/calibration/template")
def get_calibration_template(assignment_id: str, db: Session = Depends(get_db)):
    """
    Generates a pre-formatted downloadable CSV calibration template matching the assignment's rubric questions.
    """
    from fastapi.responses import Response
    import io
    import csv

    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail="Assignment not found")

    rubric_data = assign.rubric_data or []
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "Student ID", "Student Name", "Student Email",
        "Question", "Student Response", "Lecturer Score",
        "Max Score", "Feedback", "Anchor Type"
    ])

    if rubric_data:
        for idx, item in enumerate(rubric_data):
            q_num = item.get("question_number", f"Q{idx + 1}")
            max_sc = item.get("max_score", item.get("maxMark", 10.0))
            # Sample rows for this question
            writer.writerow([
                f"STU_{1001 + idx}",
                f"Student {1001 + idx}",
                f"student{1001 + idx}@university.edu",
                q_num,
                f"Sample response explaining key concepts for {q_num}...",
                round(float(max_sc) * 0.85, 1),
                max_sc,
                f"Well-explained answer adhering to {q_num} criteria.",
                "high"
            ])
            writer.writerow([
                f"STU_{1002 + idx}",
                f"Student {1002 + idx}",
                f"student{1002 + idx}@university.edu",
                q_num,
                f"Partial response addressing part of {q_num}...",
                round(float(max_sc) * 0.55, 1),
                max_sc,
                f"Identified core mechanism but omitted technical derivation.",
                "borderline"
            ])
            writer.writerow([
                f"STU_{1003 + idx}",
                f"Student {1003 + idx}",
                f"student{1003 + idx}@university.edu",
                q_num,
                f"Brief response with misconceptions for {q_num}...",
                round(float(max_sc) * 0.2, 1),
                max_sc,
                f"Incorrect assumptions and missing primary steps.",
                "low"
            ])
    else:
        # Default sample rows
        writer.writerow([
            "STU_1001", "Alice Smith", "alice@university.edu",
            "Q1", "Virtual memory allows the execution of processes not completely in memory.",
            9.0, 10.0, "Clear and accurate definition with core mechanism.", "high"
        ])
        writer.writerow([
            "STU_1002", "Bob Jones", "bob@university.edu",
            "Q1", "Virtual memory swaps pages to disk when RAM is full.",
            6.0, 10.0, "Identified paging mechanism but omitted address translation.", "borderline"
        ])
        writer.writerow([
            "STU_1003", "Charlie Brown", "charlie@university.edu",
            "Q1", "It makes the computer run faster by adding more RAM.",
            2.0, 10.0, "Common misconception confusing RAM with virtual memory.", "low"
        ])

    csv_content = output.getvalue()
    clean_course = (assign.course_code or 'assignment').replace(' ', '_')
    filename = f"calibration_template_{clean_course}_{assignment_id[:6]}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/{assignment_id}/calibration/swap-sample")
def swap_calibration_sample(assignment_id: str, payload: dict, db: Session = Depends(get_db)):
    """
    Allows the examiner to manually replace a calibration sample submission with a chosen alternative.
    """
    remove_id = payload.get("remove_submission_id")
    add_id = payload.get("add_submission_id")

    if not remove_id or not add_id:
        raise HTTPException(status_code=400, detail="Both 'remove_submission_id' and 'add_submission_id' are required")

    sub_remove = db.query(Submission).filter(Submission.id == remove_id, Submission.assignment_id == assignment_id).first()
    sub_add = db.query(Submission).filter(Submission.id == add_id, Submission.assignment_id == assignment_id).first()

    if not sub_remove or not sub_add:
        raise HTTPException(status_code=404, detail="One or both submissions not found in assignment")

    sub_remove.is_calibration_sample = False
    sub_add.is_calibration_sample = True
    db.commit()

    return {
        "message": "Calibration sample replaced successfully",
        "removed_submission_id": remove_id,
        "added_submission_id": add_id
    }


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
        "extracted_questions": parsed_questions,
        "has_rubric": has_rubric,
        "rubric_warning": rubric_warning,
        "message": f"Parsed {len(files)} file(s). Extracted {len(parsed_questions)} questions."
    }


@router.get("/{assignment_id}/export-csv")
def export_assignment_csv(assignment_id: str, db: Session = Depends(get_db)):
    """
    Exports student grades for an assignment as a simplified CSV file containing:
    Student ID, Student Name, Submission File, Student Response, Total Score, Status, AI Evaluation Summary
    """
    import io
    import csv
    from fastapi.responses import StreamingResponse

    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    submissions = db.query(Submission).filter(Submission.assignment_id == assignment_id).all()

    # Build CSV Header
    header = [
        "Student ID",
        "Student Name",
        "Submission File",
        "Student Response",
        "Total Score",
        "Status",
        "AI Evaluation Summary"
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)

    for sub in submissions:
        fb = sub.feedback if isinstance(sub.feedback, dict) else {}
        summary = fb.get("summary", "")
        score_val = sub.score if sub.score is not None else ""

        row = [
            sub.student_id,
            sub.student_name or "N/A",
            sub.file_name,
            sub.raw_text or "",
            score_val,
            sub.status,
            summary
        ]
        writer.writerow(row)

    output.seek(0)
    clean_code = re.sub(r'[^a-zA-Z0-9_-]', '', assignment.course_code or 'Assignment')
    filename = f"{clean_code}_Grades.csv"
    headers = {
        'Content-Disposition': f'attachment; filename="{filename}"'
    }
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)


@router.delete("/{assignment_id}")
def delete_assignment(assignment_id: str, db: Session = Depends(get_db)):
    """
    Deletes a specific assignment, all its student submissions, audit logs,
    and associated ChromaDB vector store collection while preserving all other assignments.
    """
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    title = assignment.title
    course_code = assignment.course_code

    # Clean up ChromaDB collection if exists
    try:
        if hasattr(embedding_service, "chroma_client") and embedding_service.chroma_client:
            coll_name = f"rubric_{assignment_id.replace('-', '_')}"
            try:
                embedding_service.chroma_client.delete_collection(coll_name)
            except Exception:
                pass
    except Exception:
        pass

    db.delete(assignment)
    db.commit()

    return {
        "message": f"Assignment '{title}' ({course_code}) and all related submissions were deleted successfully.",
        "deleted_assignment_id": assignment_id
    }

