import time
import os
import random
import datetime
from sqlalchemy.orm import Session
from ..models import Submission, Assignment, EvaluationLog
from .document_parser import extract_text_from_file
from .rag import retrieve_rubric_context
from .llm_service import call_llm_for_grading
from .confidence import evaluate_confidence_and_status

PROMPT_VERSION = os.getenv("PROMPT_VERSION", "v1.2-rubric-cot")
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-2.5-flash")


def is_blank_submission(text: str) -> bool:
    """
    Checks if a student response is blank, empty, dash ('-'), 'N/A', or contains no real content.
    """
    if not text:
        return True
    
    clean = text.strip()
    if clean in ["", "-", "N/A", "n/a", "none", "None", "nan"]:
        return True
        
    # Check if lines consist only of "Question QX:\n-"
    lines = [line.strip() for line in clean.split("\n") if line.strip()]
    content_lines = [l for l in lines if not l.startswith("Question Q") and not l.startswith("Question ") and l not in ["-", ":", ""]]
    return len(content_lines) == 0


def run_grading_pipeline(db: Session, submission_id: str) -> Submission:
    """
    Executes the full end-to-end AI grading pipeline for a submission:
    1. Retrieve submission & assignment from PostgreSQL
    2. Extract document text from PDF / DOCX / raw_text
    3. Calculate total assignment max score (sum of question max_score)
    4. If submission is blank, award 0.0 marks directly
    5. Query ChromaDB for top-k relevant rubric context
    6. Call Multi-Agent LLM for structured scoring & feedback
    7. Evaluate confidence score & determine status
    8. Save score, duration, model, & prompt_version into PostgreSQL
    9. Log evaluation metrics into EvaluationLog table
    """
    start_time = time.time()
    
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise ValueError(f"Submission {submission_id} not found in database.")

    assignment = db.query(Assignment).filter(Assignment.id == submission.assignment_id).first()
    if not assignment:
        raise ValueError(f"Assignment {submission.assignment_id} not found.")

    # Step 1: Extract Document Text from raw_text or file_path
    submission.status = "extracting_answers"
    db.commit()
    extracted_text = ""
    if submission.raw_text:
        extracted_text = submission.raw_text
    elif submission.file_path and os.path.exists(submission.file_path):
        extracted_text = extract_text_from_file(submission.file_path)

    # Calculate Total Assignment Max Score
    rubric_data = assignment.rubric_data or []
    if rubric_data:
        total_max_score = sum(float(item.get("max_score", item.get("maxMark", 10.0))) for item in rubric_data)
    else:
        total_max_score = 10.0

    # Step 2: Check for Blank / Missing Student Submission
    if is_blank_submission(extracted_text):
        duration = time.time() - start_time
        submission.score = 0.0
        submission.confidence_score = 1.0
        submission.status = "graded"
        submission.feedback = {
            "summary": "No response provided by student (Blank submission).",
            "breakdown": [
                {
                    "question_number": item.get("question_number", f"Q{idx+1}"),
                    "score_awarded": 0.0,
                    "max_score": float(item.get("max_score", item.get("maxMark", 10.0))),
                    "reasoning": "Student provided no response ('-'). 0 points awarded."
                } for idx, item in enumerate(rubric_data)
            ] if rubric_data else []
        }
        submission.highlights = []
        submission.grading_duration = round(duration, 2)
        submission.model_used = LLM_MODEL
        submission.prompt_version = PROMPT_VERSION
        submission.graded_at = datetime.datetime.utcnow()

        eval_log = EvaluationLog(
            submission_id=submission.id,
            ai_score=0.0,
            confidence_score=1.0,
            latency_seconds=round(duration, 2),
            cost_estimate=0.0,
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

        try:
            from .icc_tracker import record_and_evaluate_submission
            record_and_evaluate_submission(submission)
        except Exception as e:
            print(f"[ICC Tracker Warning] Error updating ICC tracker for blank submission {submission.id}: {e}")

        return submission

    # Step 3: Query ChromaDB for RAG context
    submission.status = "retrieving_rubric"
    db.commit()
    rag_context = retrieve_rubric_context(assignment.id, extracted_text)

    # Step 4: Execute Multi-Agent LLM Grading Prompt
    submission.status = "grading"
    db.commit()
    llm_result = call_llm_for_grading(
        student_text=extracted_text,
        rubric_json=rubric_data,
        model_answer=assignment.model_answer or "",
        rag_context=rag_context,
        total_max_score=total_max_score
    )

    # Step 5: Save Record to PostgreSQL
    duration = time.time() - start_time
    raw_overall_score = float(llm_result.get("overall_score", 0.0))
    # Cap score between 0.0 and total_max_score
    submission.score = round(max(0.0, min(total_max_score, raw_overall_score)), 1)
    submission.confidence_score = float(llm_result.get("confidence_score", 0.85))
    submission.status = str(llm_result.get("status", "graded"))

    feedback_dict = llm_result.get("feedback", {})
    if not isinstance(feedback_dict, dict):
        feedback_dict = {"summary": str(feedback_dict), "breakdown": []}

    flag_list = list(llm_result.get("flag_reasons", []))

    # Operational Quality Control Sampling (Configurable: Disabled by default, enabled via toggle)
    enable_qc_audit = os.getenv("ENABLE_RANDOM_QC_AUDIT", "false").lower() in ["true", "1", "yes"]
    qc_audit_rate = float(os.getenv("QC_AUDIT_RATE", "0.05"))

    if enable_qc_audit and qc_audit_rate > 0:
        submission_count = db.query(Submission).filter(Submission.assignment_id == assignment.id).count()
        qc_prob = max(qc_audit_rate, 1.0 / max(1, submission_count)) if submission_count <= 20 else qc_audit_rate

        if random.random() < qc_prob:
            if "🎲 Random Quality Control Audit Sample" not in flag_list:
                flag_list.append("🎲 Random Quality Control Audit Sample")
                submission.status = "flagged"

    if flag_list:
        feedback_dict["flag_reasons"] = flag_list
    if llm_result.get("confidence_components"):
        feedback_dict["confidence_components"] = llm_result["confidence_components"]

    submission.feedback = feedback_dict
    submission.highlights = llm_result.get("highlights", [])
    submission.grading_duration = round(duration, 2)
    submission.model_used = LLM_MODEL
    submission.prompt_version = PROMPT_VERSION
    submission.graded_at = datetime.datetime.utcnow()

    # Step 7: Create EvaluationLog Entry
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

    try:
        from .icc_tracker import record_and_evaluate_submission
        record_and_evaluate_submission(submission)
    except Exception as e:
        print(f"[ICC Tracker Warning] Error updating ICC tracker for submission {submission.id}: {e}")

    return submission

