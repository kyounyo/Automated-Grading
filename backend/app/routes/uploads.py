import os
import uuid
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Submission, Assignment
from ..schemas import UploadResponse
from ..services.storage import storage_service
from ..services.document_parser import parse_excel_rows

router = APIRouter(prefix="/api/upload", tags=["Uploads"])

TEMP_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "temp"
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_submission_file(
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    assignment_id: str = Form(...),
    student_id: str = Form(default="AUTO"),
    student_name: str = Form(default="AUTO"),
    db: Session = Depends(get_db)
):
    """
    Uploads student submission file(s) (.pdf, .docx, .xlsx, .csv, .txt).
    Supports single file ('file') or batch multi-file ('files') uploads.
    Generates a unique batch_id for the file upload batch and upserts student submission records in PostgreSQL.
    """
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail=f"Assignment '{assignment_id}' not found. Please select an existing assignment.")

    # Gather all uploaded files from both 'file' and 'files' form fields
    upload_list: List[UploadFile] = []
    if files:
        upload_list.extend(files)
    if file and file not in upload_list:
        upload_list.append(file)

    if not upload_list:
        raise HTTPException(status_code=400, detail="No submission files provided in upload request.")

    batch_id = f"batch-{uuid.uuid4().hex[:6]}"
    created_ids = []
    total_processed_students = 0
    last_storage_res = {}
    last_filename = upload_list[0].filename

    for uploaded_file in upload_list:
        file_ext = Path(uploaded_file.filename).suffix.lower()
        unique_filename = f"{assignment_id}_{uuid.uuid4().hex[:6]}{file_ext}"
        temp_path = TEMP_UPLOAD_DIR / unique_filename
        last_filename = uploaded_file.filename

        # Write uploaded file to temp disk
        try:
            with open(temp_path, "wb") as buffer:
                content = await uploaded_file.read()
                buffer.write(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to write uploaded file '{uploaded_file.filename}': {e}")

        # Upload main file to storage engine
        s3_key = f"submissions/{assignment_id}/{unique_filename}"
        storage_res = storage_service.upload_file(str(temp_path), s3_key)
        last_storage_res = storage_res

        # Case 1: Excel / CSV dataset containing multiple student submissions
        if file_ext in [".xlsx", ".xls", ".csv"]:
            excel_rows = parse_excel_rows(str(temp_path))
            if len(excel_rows) > 0:
                for idx, item in enumerate(excel_rows):
                    s_id = str(item.get("student_id", f"STU{100 + idx}")).strip()
                    s_name = str(item.get("student_name", f"Student {s_id}")).strip() or f"Student {s_id}"
                    s_email = str(item.get("student_email", "N/A")).strip() or "N/A"
                    raw_text_content = item.get("text") or ""

                    # Uniqueness Check: Upsert by (student_id, assignment_id)
                    existing_sub = db.query(Submission).filter(
                        Submission.student_id == s_id,
                        Submission.assignment_id == assignment_id
                    ).first()

                    if existing_sub:
                        existing_sub.batch_id = batch_id
                        existing_sub.student_name = s_name
                        existing_sub.student_email = s_email
                        existing_sub.file_name = uploaded_file.filename
                        existing_sub.file_s3_url = storage_res.get("file_s3_url")
                        existing_sub.file_path = storage_res.get("file_path")
                        existing_sub.raw_text = raw_text_content
                        existing_sub.status = "pending"
                        existing_sub.score = None
                        existing_sub.confidence_score = None
                        existing_sub.feedback = None
                        existing_sub.highlights = None
                        created_ids.append(existing_sub.id)
                    else:
                        sub_id = f"sub-{uuid.uuid4().hex[:6]}"
                        new_sub = Submission(
                            id=sub_id,
                            assignment_id=assignment_id,
                            batch_id=batch_id,
                            student_id=s_id,
                            student_name=s_name,
                            student_email=s_email,
                            file_name=uploaded_file.filename,
                            file_s3_url=storage_res.get("file_s3_url"),
                            file_path=storage_res.get("file_path"),
                            raw_text=raw_text_content,
                            status="pending"
                        )
                        db.add(new_sub)
                        created_ids.append(sub_id)
                    total_processed_students += 1

            if temp_path.exists():
                try: os.remove(temp_path)
                except Exception: pass
            continue

        # Case 2: Individual student file (PDF, DOCX, TXT)
        from ..services.document_parser import extract_text_from_file
        extracted_doc_text = ""
        try:
            extracted_doc_text = extract_text_from_file(str(temp_path))
        except Exception:
            pass

        stu_name = student_name if student_name != "AUTO" else uploaded_file.filename.split('.')[0].replace('_', ' ')
        stu_id = student_id if student_id != "AUTO" else f"STU_{len(created_ids) + 1}"

        existing_sub = db.query(Submission).filter(
            Submission.student_id == stu_id,
            Submission.assignment_id == assignment_id
        ).first()

        if existing_sub:
            existing_sub.batch_id = batch_id
            existing_sub.student_name = stu_name
            existing_sub.file_name = uploaded_file.filename
            existing_sub.file_s3_url = storage_res.get("file_s3_url")
            existing_sub.file_path = storage_res.get("file_path")
            existing_sub.raw_text = extracted_doc_text
            existing_sub.status = "pending"
            existing_sub.score = None
            existing_sub.confidence_score = None
            existing_sub.feedback = None
            existing_sub.highlights = None
            created_ids.append(existing_sub.id)
        else:
            submission_id = f"sub-{uuid.uuid4().hex[:6]}"
            target_sub = Submission(
                id=submission_id,
                assignment_id=assignment_id,
                batch_id=batch_id,
                student_id=stu_id,
                student_name=stu_name,
                file_name=uploaded_file.filename,
                file_s3_url=storage_res.get("file_s3_url"),
                file_path=storage_res.get("file_path"),
                raw_text=extracted_doc_text,
                status="pending"
            )
            db.add(target_sub)
            created_ids.append(submission_id)
        total_processed_students += 1

        if temp_path.exists():
            try: os.remove(temp_path)
            except Exception: pass

    # Commit all created submissions and update assignment submission count
    db.commit()
    assign.total_submissions = db.query(Submission).filter(Submission.assignment_id == assignment_id).count()
    db.commit()

    return UploadResponse(
        message=f"Successfully processed and uploaded {total_processed_students} student submission(s).",
        submission_id=created_ids[0] if created_ids else "sub-bulk",
        batch_id=batch_id,
        file_name=last_filename,
        file_s3_url=last_storage_res.get("file_s3_url"),
        file_path=last_storage_res.get("file_path")
    )


@router.post("/preview-submissions")
async def preview_submissions(files: list[UploadFile] = File(...)):
    """
    Parses uploaded student submission files (.xlsx, .csv, .pdf, .docx) for client preview before finalizing upload.
    Returns preview metadata and response text for the extracted students.
    """
    all_extracted_students = []

    for file in files:
        file_ext = Path(file.filename).suffix.lower()
        temp_path = TEMP_UPLOAD_DIR / f"prev_{uuid.uuid4().hex[:6]}{file_ext}"

        try:
            with open(temp_path, "wb") as buffer:
                content = await file.read()
                buffer.write(content)

            if file_ext in [".xlsx", ".xls", ".csv"]:
                excel_rows = parse_excel_rows(str(temp_path))
                for idx, row in enumerate(excel_rows):
                    s_id = str(row.get("student_id", f"STU_{idx + 1}")).strip()
                    s_name = str(row.get("student_name", f"Student {s_id}")).strip() or f"Student {s_id}"
                    s_email = str(row.get("student_email", "N/A")).strip() or "N/A"
                    raw_text = str(row.get("text", "")).strip()

                    all_extracted_students.append({
                        "student_id": s_id,
                        "student_name": s_name,
                        "student_email": s_email,
                        "file_name": file.filename,
                        "text": raw_text
                    })
            else:
                from ..services.document_parser import extract_text_from_file
                txt = extract_text_from_file(str(temp_path))
                stu_name = file.filename.split('.')[0].replace('_', ' ')
                stu_id = f"STU_{len(all_extracted_students) + 1}"

                all_extracted_students.append({
                    "student_id": stu_id,
                    "student_name": stu_name,
                    "student_email": "N/A",
                    "file_name": file.filename,
                    "text": txt
                })

            if temp_path.exists():
                try: os.remove(temp_path)
                except Exception: pass
        except Exception as e:
            print(f"[Preview Submissions Error] {file.filename}: {e}")

    return {
        "total_students": len(all_extracted_students),
        "students": all_extracted_students,
        "first_three_students": all_extracted_students[:3]
    }

