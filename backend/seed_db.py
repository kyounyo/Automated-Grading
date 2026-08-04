import os
import datetime
from app.database import engine, Base, SessionLocal
from app.models import Assignment, Submission, AuditLog, EvaluationLog
from app.services.embedding import embedding_service

print("[Seeding Database] Initializing tables and seeding initial dataset...")

# Create tables
Base.metadata.create_all(bind=engine)

db = SessionLocal()

try:
    # Clear existing seed data if present
    db.query(AuditLog).delete()
    db.query(EvaluationLog).delete()
    db.query(Submission).delete()
    db.query(Assignment).delete()
    db.commit()

    # 1. Seed Assignment
    assign1 = Assignment(
        id="assign-101",
        title="CS401: Midterm System Design & RAG Architecture",
        course_code="CS401",
        due_date="2026-08-15",
        status="active",
        total_submissions=3,
        average_score=82.5,
        rubric_data=[
            {
                "question_number": "Q1",
                "max_score": 50,
                "criteria": [
                    {"id": "c1", "description": "Correct identification of microservice boundaries and API gateway integration", "max_marks": 25},
                    {"id": "c2", "description": "Clear explanation of RAG vector retrieval pipeline and top-k context matching", "max_marks": 25}
                ]
            },
            {
                "question_number": "Q2",
                "max_score": 50,
                "criteria": [
                    {"id": "c3", "description": "Database schema design with proper primary/foreign keys and audit logging", "max_marks": 25},
                    {"id": "c4", "description": "Fault tolerance, confidence calculation heuristics, and fallback mechanisms", "max_marks": 25}
                ]
            }
        ],
        model_answer="A complete RAG architecture requires decoupling document ingestion from vector retrieval. Student must explain vector embedding generation (e.g. ChromaDB), top-k similarity search, context injection into LLM prompts, and PostgreSQL schema for audit logging."
    )
    db.add(assign1)
    db.commit()

    # Index Rubric into ChromaDB
    embedding_service.index_assignment_reference(
        assignment_id=assign1.id,
        rubric_data=assign1.rubric_data,
        model_answer=assign1.model_answer
    )

    # 2. Seed Submissions
    sub1 = Submission(
        id="sub-001",
        assignment_id="assign-101",
        student_id="STU8901",
        student_name="Alice Smith",
        file_name="Alice_Smith_CS401_Midterm.pdf",
        file_s3_url="https://autograde-submissions.s3.amazonaws.com/submissions/assign-101/Alice_Smith_CS401_Midterm.pdf",
        file_path="uploads/Alice_Smith_CS401_Midterm.pdf",
        score=88.5,
        confidence_score=0.92,
        status="graded",
        feedback={
            "summary": "Excellent understanding of microservice boundaries and RAG vector retrieval pipeline.",
            "breakdown": [
                {
                    "question_number": "Q1",
                    "score_awarded": 46.0,
                    "max_score": 50.0,
                    "reasoning": "Clear description of vector embeddings and top-k retrieval."
                },
                {
                    "question_number": "Q2",
                    "score_awarded": 42.5,
                    "max_score": 50.0,
                    "reasoning": "Solid database schema with foreign keys. Minor ambiguity in audit logging."
                }
            ]
        },
        highlights=[
            {
                "text": "Decoupling vector indexing from online retrieval ensures high throughput.",
                "type": "strength",
                "comment": "Accurate architectural insight."
            }
        ],
        grading_duration=1.84,
        model_used="google/gemini-2.5-flash",
        prompt_version="v1.2-rubric-cot",
        graded_at=datetime.datetime.utcnow()
    )

    sub2 = Submission(
        id="sub-002",
        assignment_id="assign-101",
        student_id="STU8902",
        student_name="Bob Jones",
        file_name="Bob_Jones_CS401_Midterm.pdf",
        file_s3_url="https://autograde-submissions.s3.amazonaws.com/submissions/assign-101/Bob_Jones_CS401_Midterm.pdf",
        file_path="uploads/Bob_Jones_CS401_Midterm.pdf",
        score=52.0,
        confidence_score=0.64,
        status="flagged",
        feedback={
            "summary": "Borderline grade requiring lecturer audit. Explanation of RAG vector search is incomplete.",
            "breakdown": [
                {
                    "question_number": "Q1",
                    "score_awarded": 26.0,
                    "max_score": 50.0,
                    "reasoning": "Missed vector embeddings and similarity search details."
                },
                {
                    "question_number": "Q2",
                    "score_awarded": 26.0,
                    "max_score": 50.0,
                    "reasoning": "Basic database tables without foreign key constraints."
                }
            ]
        },
        highlights=[
            {
                "text": "Vector search uses simple string matching.",
                "type": "weakness",
                "comment": "Incorrect definition of vector search."
            }
        ],
        grading_duration=2.10,
        model_used="google/gemini-2.5-flash",
        prompt_version="v1.2-rubric-cot",
        graded_at=datetime.datetime.utcnow()
    )

    sub3 = Submission(
        id="sub-003",
        assignment_id="assign-101",
        student_id="STU8903",
        student_name="Charlie Brown",
        file_name="Charlie_Brown_CS401_Midterm.pdf",
        file_s3_url="https://autograde-submissions.s3.amazonaws.com/submissions/assign-101/Charlie_Brown_CS401_Midterm.pdf",
        file_path="uploads/Charlie_Brown_CS401_Midterm.pdf",
        score=None,
        confidence_score=None,
        status="pending",
        feedback=None,
        highlights=None,
        grading_duration=None,
        model_used=None,
        prompt_version=None,
        graded_at=None
    )

    db.add_all([sub1, sub2, sub3])
    db.commit()

    # Seed EvaluationLog
    eval1 = EvaluationLog(
        submission_id=sub1.id,
        ai_score=88.5,
        confidence_score=0.92,
        latency_seconds=1.84,
        cost_estimate=0.002,
        prompt_version="v1.2-rubric-cot",
        model_used="google/gemini-2.5-flash"
    )
    db.add(eval1)
    db.commit()

    print("[Seeding Success] Database populated with initial assignments and submissions!")
finally:
    db.close()
