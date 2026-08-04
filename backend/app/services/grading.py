import time
import os
import datetime
from sqlalchemy.orm import Session
from ..models import Submission, Assignment, EvaluationLog
from .document_parser import extract_text_from_file
from .rag import retrieve_rubric_context
from .llm_service import call_llm_for_grading
from .confidence import evaluate_confidence_and_status

PROMPT_VERSION = os.getenv("PROMPT_VERSION", "v1.2-rubric-cot")
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-2.5-flash")


def run_grading_pipeline(db: Session, submission_id: str) -> Submission:
    """
    Executes the full end-to-end AI grading pipeline for a submission:
    1. Retrieve submission & assignment from PostgreSQL
    2. Extract document text from PDF / DOCX
    3. Query ChromaDB for top-k relevant rubric context
    4. Call LLM for structured scoring & feedback
    5. Evaluate confidence score & determine status
    6. Save score, duration, model, & prompt_version into PostgreSQL
    7. Log evaluation metrics into EvaluationLog table
    """
    start_time = time.time()
    
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise ValueError(f"Submission {submission_id} not found in database.")

    assignment = db.query(Assignment).filter(Assignment.id == submission.assignment_id).first()
    if not assignment:
        raise ValueError(f"Assignment {submission.assignment_id} not found.")

    # Step 1: Extract Document Text
    submission.status = "extracting_answers"
    db.commit()
    extracted_text = ""
    if submission.file_path and os.path.exists(submission.file_path):
        extracted_text = extract_text_from_file(submission.file_path)

    if not extracted_text:
        extracted_text = f"Student response submission document for {submission.student_name}."

    # Step 2: Query ChromaDB for RAG context
    submission.status = "retrieving_rubric"
    db.commit()
    rag_context = retrieve_rubric_context(assignment.id, extracted_text)

    # Step 3: Execute LLM Grading Prompt
    submission.status = "grading"
    db.commit()
    llm_result = call_llm_for_grading(
        student_text=extracted_text,
        rubric_json=assignment.rubric_data or [],
        model_answer=assignment.model_answer or "",
        rag_context=rag_context
    )

    # Step 4: Confidence Score & Flagging Check
    conf_eval = evaluate_confidence_and_status(llm_result, extracted_text)

    # Step 5: Save Record to PostgreSQL
    duration = time.time() - start_time
    submission.score = llm_result.get("overall_score", 0.0)
    submission.confidence_score = conf_eval["confidence_score"]
    submission.status = conf_eval["status"]
    submission.feedback = llm_result.get("feedback", {})
    submission.highlights = llm_result.get("highlights", [])
    submission.grading_duration = round(duration, 2)
    submission.model_used = LLM_MODEL
    submission.prompt_version = PROMPT_VERSION
    submission.graded_at = datetime.datetime.utcnow()

    # Step 6: Create EvaluationLog Entry
    eval_log = EvaluationLog(
        submission_id=submission.id,
        ai_score=submission.score,
        confidence_score=submission.confidence_score,
        latency_seconds=round(duration, 2),
        cost_estimate=0.002,  # Nominal LLM token cost estimate
        prompt_version=PROMPT_VERSION,
        model_used=LLM_MODEL
    )
    db.add(eval_log)

    # Update Assignment stats
    all_submissions = db.query(Submission).filter(Submission.assignment_id == assignment.id).all()
    graded_scores = [s.score for s in all_submissions if s.score is not None]
    if graded_scores:
        assignment.average_score = round(sum(graded_scores) / len(graded_scores), 1)
        assignment.total_submissions = len(all_submissions)

    db.commit()
    db.refresh(submission)
    return submission
