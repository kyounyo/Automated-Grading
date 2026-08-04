import os
import uuid
from pathlib import Path
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
    file: UploadFile = File(...),
    assignment_id: str = Form(...),
    student_id: str = Form(default="AUTO"),
    student_name: str = Form(default="AUTO"),
    db: Session = Depends(get_db)
):
    """
    Uploads student submission file (.pdf, .docx, .xlsx, .csv, .txt).
    Generates a unique batch_id for the file upload batch and upserts student submission records in PostgreSQL.
    """
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail="Assignment not found")

    batch_id = f"batch-{uuid.uuid4().hex[:6]}"
    file_ext = Path(file.filename).suffix.lower()
    unique_filename = f"{assignment_id}_{uuid.uuid4().hex[:6]}{file_ext}"
    temp_path = TEMP_UPLOAD_DIR / unique_filename

    # Write uploaded file to temp disk
    try:
        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write uploaded file: {e}")

    # Upload main file to storage engine
    s3_key = f"submissions/{assignment_id}/{unique_filename}"
    storage_res = storage_service.upload_file(str(temp_path), s3_key)

    # Check if file is Excel dataset containing multiple student submissions
    if file_ext in [".xlsx", ".xls", ".csv"]:
        excel_rows = parse_excel_rows(str(temp_path))
        if len(excel_rows) > 0:
            created_ids = []
            for idx, item in enumerate(excel_rows):
                s_id = str(item.get("student_id", f"STU{100 + idx}")).strip()
                s_name = str(item.get("student_name", f"Student {s_id}")).strip()

                # Uniqueness Check: Upsert by (student_id, assignment_id)
                existing_sub = db.query(Submission).filter(
                    Submission.student_id == s_id,
                    Submission.assignment_id == assignment_id
                ).first()

                raw_text_content = item.get("text") or ""
                if existing_sub:
                    existing_sub.batch_id = batch_id
                    existing_sub.file_name = file.filename
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
                        file_name=file.filename,
                        file_s3_url=storage_res.get("file_s3_url"),
                        file_path=storage_res.get("file_path"),
                        raw_text=raw_text_content,
                        status="pending"
                    )
                    db.add(new_sub)
                    created_ids.append(sub_id)

            # Update assignment total submissions count
            db.commit()
            assign.total_submissions = db.query(Submission).filter(Submission.assignment_id == assignment_id).count()
            db.commit()

            # Clean up temp file
            if temp_path.exists():
                try: os.remove(temp_path)
                except Exception: pass

            return UploadResponse(
                message=f"Excel dataset parsed successfully! Processed {len(excel_rows)} student submission(s).",
                submission_id=created_ids[0] if created_ids else "sub-excel",
                batch_id=batch_id,
                file_name=file.filename,
                file_s3_url=storage_res.get("file_s3_url"),
                file_path=storage_res.get("file_path")
            )

    # Standard single PDF/DOCX file upload
    stu_name = student_name if student_name != "AUTO" else file.filename.split('.')[0].replace('_', ' ')
    stu_id = student_id if student_id != "AUTO" else f"STU{uuid.uuid4().hex[:4].upper()}"

    existing_sub = db.query(Submission).filter(
        Submission.student_id == stu_id,
        Submission.assignment_id == assignment_id
    ).first()

    if existing_sub:
        existing_sub.batch_id = batch_id
        existing_sub.file_name = file.filename
        existing_sub.file_s3_url = storage_res.get("file_s3_url")
        existing_sub.file_path = storage_res.get("file_path")
        existing_sub.status = "pending"
        existing_sub.score = None
        existing_sub.confidence_score = None
        existing_sub.feedback = None
        existing_sub.highlights = None
        target_sub = existing_sub
    else:
        submission_id = f"sub-{uuid.uuid4().hex[:6]}"
        target_sub = Submission(
            id=submission_id,
            assignment_id=assignment_id,
            batch_id=batch_id,
            student_id=stu_id,
            student_name=stu_name,
            file_name=file.filename,
            file_s3_url=storage_res.get("file_s3_url"),
            file_path=storage_res.get("file_path"),
            status="pending"
        )
        db.add(target_sub)

    db.commit()
    assign.total_submissions = db.query(Submission).filter(Submission.assignment_id == assignment_id).count()
    db.commit()

    # Clean up temp file
    if temp_path.exists():
        try: os.remove(temp_path)
        except Exception: pass

    return UploadResponse(
        message="Submission uploaded and registered successfully.",
        submission_id=target_sub.id,
        batch_id=batch_id,
        file_name=file.filename,
        file_s3_url=storage_res.get("file_s3_url"),
        file_path=storage_res.get("file_path")
    )
