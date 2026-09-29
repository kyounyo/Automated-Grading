import os
import datetime
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from ..database import get_db
from ..models import Submission, Assignment, AuditLog, EvaluationLog
from ..schemas import SubmissionResponse, ScoreOverrideRequest, AuditLogResponse
from ..services.grading import run_grading_pipeline

router = APIRouter(tags=["Submissions"])

ACTIVE_GRADING_ASSIGNMENTS = set()

IN_PROGRESS_STATUSES = ["processing", "extracting_answers", "retrieving_rubric", "grading"]


def heal_orphaned_submissions(db: Session, assignment_id: str):
    """
    Self-healing sync: Restores submissions to their true state.
    - If a submission already has a completed score and breakdown, ensure its status is 'flagged' or 'graded'.
    - If an assignment is NOT actively running batch grading, reset any incomplete in-progress submissions to 'pending'.
    """
    is_actively_grading = assignment_id in ACTIVE_GRADING_ASSIGNMENTS
    in_progress = db.query(Submission).filter(
        Submission.assignment_id == assignment_id,
        Submission.status.in_(IN_PROGRESS_STATUSES)
    ).all()
    if in_progress:
        changed = False
        for s in in_progress:
            if s.score is not None and s.feedback and isinstance(s.feedback, dict) and s.feedback.get("breakdown"):
                s.status = "flagged" if s.feedback.get("flag_reasons") else "graded"
                changed = True
            elif not is_actively_grading:
                s.status = "pending"
                changed = True
        if changed:
            db.commit()


@router.get("/api/assignments/{assignment_id}/submissions", response_model=List[SubmissionResponse])
def list_submissions_for_assignment(assignment_id: str, db: Session = Depends(get_db)):
    """List all student submissions for a specific assignment with self-healing sync."""
    heal_orphaned_submissions(db, assignment_id)
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
def delete_submission(submission_id: str, db: Session = Depends(get_db)):
    """Delete a student submission and recalculate assignment stats."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    assignment_id = sub.assignment_id
    db.delete(sub)
    db.commit()

    # Recalculate Assignment stats
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if assignment:
        remaining_subs = db.query(Submission).filter(Submission.assignment_id == assignment_id).all()
        assignment.total_submissions = len(remaining_subs)
        scores = [s.score for s in remaining_subs if s.score is not None]
        assignment.average_score = round(sum(scores) / len(scores), 1) if scores else 0.0
        db.commit()

    return {"message": "Submission deleted successfully", "id": submission_id}


@router.post("/api/submissions/{submission_id}/grade", response_model=SubmissionResponse)
def grade_single_submission(submission_id: str, db: Session = Depends(get_db)):
    """Triggers end-to-end AI grading for a single submission synchronously."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    assignment_id = sub.assignment_id
    ACTIVE_GRADING_ASSIGNMENTS.add(assignment_id)
    try:
        updated_sub = run_grading_pipeline(db, submission_id)
        return updated_sub
    finally:
        ACTIVE_GRADING_ASSIGNMENTS.discard(assignment_id)


def _batch_grade_task(assignment_id: str):
    """Background task runner for batch grading all pending submissions of an assignment."""
    from ..database import SessionLocal
    ACTIVE_GRADING_ASSIGNMENTS.add(assignment_id)
    db = SessionLocal()
    try:
        heal_orphaned_submissions(db, assignment_id)
        pending_subs = db.query(Submission).filter(
            Submission.assignment_id == assignment_id,
            Submission.score.is_(None)
        ).all()
        total_batch = len(pending_subs)
        if total_batch == 0:
            return

        print(f"\n{'='*75}", flush=True)
        print(f" [AI BATCH GRADING INITIATED] Assignment ID: {assignment_id}", flush=True)
        print(f" [Queue] {total_batch} submission(s) queued for evaluation", flush=True)
        print(f"{'='*75}\n", flush=True)

        for idx, sub in enumerate(pending_subs):
            try:
                # Mark ONLY the currently active submission as processing
                sub.status = "processing"
                db.commit()

                print(f"\n┌{'─'*73}┐", flush=True)
                print(f"│ [QUEUE PROGRESS] Paper {idx+1}/{total_batch} ({(idx)/total_batch*100:.0f}% Completed)", flush=True)
                print(f"│ Student: {sub.student_name} (ID: {sub.student_id})", flush=True)
                print(f"│ File: {sub.file_name or 'N/A'}", flush=True)
                print(f"└{'─'*73}┘", flush=True)

                run_grading_pipeline(db, sub.id)
            except Exception as e:
                print(f" [Batch Grading Error] Failed for submission {sub.id}: {e}", flush=True)
                import traceback
                traceback.print_exc()
                sub.status = "pending"
                db.commit()

        # Update assignment stats upon completion
        assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if assign:
            all_subs = db.query(Submission).filter(Submission.assignment_id == assignment_id).all()
            scored = [s.score for s in all_subs if s.score is not None]
            if scored:
                assign.average_score = round(sum(scored) / len(scored), 2)
                assign.total_submissions = len(all_subs)
                db.commit()

        print(f"\n{'='*75}", flush=True)
        print(f" [AI BATCH GRADING COMPLETE] Finished all {total_batch} submission(s)!", flush=True)
        print(f"{'='*75}\n", flush=True)
    finally:
        ACTIVE_GRADING_ASSIGNMENTS.discard(assignment_id)
        db.close()


@router.get("/api/assignments/{assignment_id}/grading-status")
def get_grading_status(assignment_id: str, db: Session = Depends(get_db)):
    """Returns real-time background grading status for the given assignment with self-healing."""
    heal_orphaned_submissions(db, assignment_id)
    is_active = assignment_id in ACTIVE_GRADING_ASSIGNMENTS

    completed_count = db.query(Submission).filter(
        Submission.assignment_id == assignment_id,
        Submission.status.in_(["graded", "flagged", "approved"])
    ).count()
    total_count = db.query(Submission).filter(Submission.assignment_id == assignment_id).count()

    return {
        "assignment_id": assignment_id,
        "is_grading": is_active,
        "active_count": 1 if is_active else 0,
        "completed_count": completed_count,
        "total_count": total_count
    }


@router.post("/api/assignments/{assignment_id}/grade-all", status_code=status.HTTP_202_ACCEPTED)
def grade_all_submissions(assignment_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Spawns asynchronous FastAPI BackgroundTasks worker to grade all pending submissions for an assignment."""
    assign = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail="Assignment not found")

    if not assign.grading_started_at:
        assign.grading_started_at = datetime.datetime.utcnow()
        db.commit()

    heal_orphaned_submissions(db, assignment_id)
    pending_count = db.query(Submission).filter(
        Submission.assignment_id == assignment_id,
        Submission.score.is_(None)
    ).count()

    if pending_count == 0:
        return {
            "message": "All submissions are already graded for this assignment.",
            "assignment_id": assignment_id,
            "status": "idle"
        }

    if assignment_id in ACTIVE_GRADING_ASSIGNMENTS:
        print(f" [Notice] Batch grading is already active for {assignment_id}. Skipping duplicate trigger.", flush=True)
        return {
            "message": f"Batch grading is already actively running for assignment {assignment_id}.",
            "assignment_id": assignment_id,
            "status": "processing"
        }

    ACTIVE_GRADING_ASSIGNMENTS.add(assignment_id)
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
    final_score = float(payload.new_score) if payload.new_score is not None else 0.0

    fb_dict = dict(sub.feedback) if isinstance(sub.feedback, dict) else {}
    if payload.updated_breakdown is not None:
        fb_dict["breakdown"] = payload.updated_breakdown
    fb_dict["flag_reasons"] = []
    sub.feedback = fb_dict
    flag_modified(sub, "feedback")

    sub.score = round(final_score, 1)
    sub.status = "graded"

    # Create Audit Log entry
    audit = AuditLog(
        submission_id=sub.id,
        lecturer_name=payload.lecturer_name or "Lecturer",
        action="manual_override",
        old_score=old_score,
        new_score=final_score,
        comment=payload.comment
    )
    db.add(audit)

    # Create EvaluationLog entry for human vs AI delta benchmarking
    eval_log = db.query(EvaluationLog).filter(EvaluationLog.submission_id == sub.id).first()
    if eval_log:
        eval_log.lecturer_score = final_score
        eval_log.score_difference = abs((eval_log.ai_score or 0.0) - final_score)
    else:
        eval_log = EvaluationLog(
            submission_id=sub.id,
            lecturer_score=final_score,
            ai_score=old_score,
            score_difference=abs((old_score or 0.0) - final_score),
            prompt_version=sub.prompt_version,
            model_used=sub.model_used
        )
        db.add(eval_log)

    # Update assignment average score in database
    assignment = db.query(Assignment).filter(Assignment.id == sub.assignment_id).first()
    if assignment:
        graded_subs = db.query(Submission).filter(Submission.assignment_id == assignment.id, Submission.score.isnot(None)).all()
        if graded_subs:
            all_scores = [s.score for s in graded_subs if s.id != sub.id] + [final_score]
            assignment.average_score = round(sum(all_scores) / len(all_scores), 2)

    db.commit()
    db.refresh(sub)

    try:
        from ..services.icc_tracker import record_and_evaluate_submission
        record_and_evaluate_submission(sub)
    except Exception as e:
        print(f"[ICC Tracker Warning] Error updating ICC tracker for override on {sub.id}: {e}")

    return sub
