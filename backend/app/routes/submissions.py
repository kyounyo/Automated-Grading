import os
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Submission, Assignment, AuditLog, EvaluationLog
from ..schemas import SubmissionResponse, ScoreOverrideRequest, AuditLogResponse
from ..services.grading import run_grading_pipeline

router = APIRouter(tags=["Submissions"])


@router.get("/api/assignments/{assignment_id}/submissions", response_model=List[SubmissionResponse])
def list_submissions_for_assignment(assignment_id: str, db: Session = Depends(get_db)):
    """List all student submissions for a specific assignment."""
    submissions = db.query(Submission).filter(Submission.assignment_id == assignment_id).all()
    return submissions


@router.get("/api/submissions/{submission_id}", response_model=SubmissionResponse)
def get_submission_detail(submission_id: str, db: Session = Depends(get_db)):
    """Retrieve detailed submission view with AI reasoning, rubric breakdown, and highlights."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    return sub


@router.delete("/api/submissions/{submission_id}")
def delete_single_submission(submission_id: str, db: Session = Depends(get_db)):
    """Deletes a single student submission from database and deletes its file from local storage."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    assign_id = sub.assignment_id

    # Delete local file from disk if present
    if sub.file_path and os.path.exists(sub.file_path):
        try:
            os.remove(sub.file_path)
        except Exception as e:
            print(f"[File Delete Warning] Could not remove file {sub.file_path}: {e}")

    # Delete submission database record
    db.delete(sub)

    # Recalculate assignment total submissions and average score
    assign = db.query(Assignment).filter(Assignment.id == assign_id).first()
    if assign:
        remaining_subs = db.query(Submission).filter(Submission.assignment_id == assign_id).all()
        assign.total_submissions = len(remaining_subs)
        scores = [s.score for s in remaining_subs if s.score is not None]
        assign.average_score = round(sum(scores) / len(scores), 1) if scores else 0.0

    db.commit()
    return {"message": f"Submission {submission_id} deleted successfully.", "submission_id": submission_id}


@router.delete("/api/assignments/{assignment_id}/submissions")
def delete_all_submissions_for_assignment(assignment_id: str, db: Session = Depends(get_db)):
    """Deletes all student submissions for an assignment from database and local storage."""
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail="Assignment not found")

    subs = db.query(Submission).filter(Submission.assignment_id == assignment_id).all()
    deleted_count = len(subs)

    for sub in subs:
        if sub.file_path and os.path.exists(sub.file_path):
            try:
                os.remove(sub.file_path)
            except Exception as e:
                print(f"[File Delete Warning] Could not remove file {sub.file_path}: {e}")
        db.delete(sub)

    assign.total_submissions = 0
    assign.average_score = 0.0
    db.commit()

    return {
        "message": f"Successfully deleted all {deleted_count} student submission(s) for assignment {assignment_id}.",
        "assignment_id": assignment_id,
        "deleted_count": deleted_count
    }


@router.post("/api/submissions/{submission_id}/grade", response_model=SubmissionResponse)
def grade_single_submission(submission_id: str, db: Session = Depends(get_db)):
    """Triggers end-to-end AI grading for a single submission synchronously."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    updated_sub = run_grading_pipeline(db, submission_id)
    return updated_sub


def _batch_grade_task(assignment_id: str):
    """Background task runner for batch grading all pending submissions of an assignment."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        pending_subs = db.query(Submission).filter(
            Submission.assignment_id == assignment_id,
            Submission.status.in_(["pending", "uploaded", "extracting_answers", "retrieving_rubric", "flagged"])
        ).all()
        print(f"[Batch Grading] Started processing {len(pending_subs)} submission(s) for assignment {assignment_id}")
        for idx, sub in enumerate(pending_subs):
            try:
                print(f"[Batch Grading] ({idx+1}/{len(pending_subs)}) Grading submission {sub.id} ({sub.student_id})...")
                run_grading_pipeline(db, sub.id)
            except Exception as e:
                print(f"[Batch Grading Error] Failed for submission {sub.id}: {e}")
        print(f"[Batch Grading] Finished batch processing for assignment {assignment_id}")
    finally:
        db.close()



@router.post("/api/assignments/{assignment_id}/grade-all", status_code=status.HTTP_202_ACCEPTED)
def grade_all_submissions(assignment_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Spawns asynchronous FastAPI BackgroundTasks worker to grade all pending submissions for an assignment."""
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail="Assignment not found")

    pending_count = db.query(Submission).filter(
        Submission.assignment_id == assignment_id,
        Submission.status.in_(["pending", "flagged"])
    ).count()

    background_tasks.add_task(_batch_grade_task, assignment_id)

    return {
        "message": f"Asynchronous batch AI grading initiated for {pending_count} submissions.",
        "assignment_id": assignment_id,
        "status": "processing"
    }


@router.patch("/api/submissions/{submission_id}/override", response_model=SubmissionResponse)
def override_submission_score(submission_id: str, payload: ScoreOverrideRequest, db: Session = Depends(get_db)):
    """Lecturer manual score override API with audit log creation in PostgreSQL."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    old_score = sub.score
    
    if payload.updated_breakdown is not None:
        fb_dict = dict(sub.feedback) if isinstance(sub.feedback, dict) else {}
        fb_dict["breakdown"] = payload.updated_breakdown
        sub.feedback = fb_dict
        calc_sum = sum(float(item.get("score_awarded", 0.0)) for item in payload.updated_breakdown if isinstance(item, dict))
        sub.score = round(calc_sum, 1)
    else:
        sub.score = payload.new_score

    sub.status = "graded"  # Mark as finalized by lecturer override

    # Create Audit Log entry
    audit = AuditLog(
        submission_id=sub.id,
        lecturer_name=payload.lecturer_name or "Lecturer",
        action="manual_override",
        old_score=old_score,
        new_score=payload.new_score,
        comment=payload.comment
    )
    db.add(audit)

    # Create EvaluationLog entry for human vs AI delta benchmarking
    eval_log = db.query(EvaluationLog).filter(EvaluationLog.submission_id == sub.id).first()
    if eval_log:
        eval_log.lecturer_score = payload.new_score
        eval_log.score_difference = abs((eval_log.ai_score or 0.0) - payload.new_score)
    else:
        eval_log = EvaluationLog(
            submission_id=sub.id,
            lecturer_score=payload.new_score,
            ai_score=old_score,
            score_difference=abs((old_score or 0.0) - payload.new_score),
            prompt_version=sub.prompt_version,
            model_used=sub.model_used
        )
        db.add(eval_log)

    db.commit()
    db.refresh(sub)
    return sub
