import datetime
from sqlalchemy import Column, Integer, String, Float, Text, JSON, DateTime, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
from .database import Base


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    course_code = Column(String, nullable=False, index=True)
    due_date = Column(String, nullable=True, default="")
    status = Column(String, default="active")  # active, completed, archived
    total_submissions = Column(Integer, default=0)
    average_score = Column(Float, default=0.0)
    rubric_data = Column(JSON, nullable=True)  # JSON structure of rubric criteria & weightage
    model_answer = Column(Text, nullable=True)  # Text or model answer reference
    calibration_enabled = Column(Boolean, default=False)
    calibration_sample_size = Column(Integer, default=3)
    calibration_settings = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    submissions = relationship("Submission", back_populates="assignment", cascade="all, delete-orphan")
    calibration_sets = relationship("CalibrationSet", back_populates="assignment", cascade="all, delete-orphan")
    calibration_examples = relationship("CalibrationExample", back_populates="assignment", cascade="all, delete-orphan")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("student_id", "assignment_id", name="uq_student_assignment"),
    )

    id = Column(String, primary_key=True, index=True)
    assignment_id = Column(String, ForeignKey("assignments.id"), nullable=False, index=True)
    batch_id = Column(String, nullable=True, index=True)  # Trace upload batch origin (e.g. batch-a123)
    student_id = Column(String, nullable=False, index=True)
    student_name = Column(String, nullable=True, default="N/A")
    student_email = Column(String, nullable=True)
    file_name = Column(String, nullable=False)
    file_s3_url = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)  # Extracted student submission response text
    score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    status = Column(String, default="pending")  # pending, processing, graded, flagged
    feedback = Column(JSON, nullable=True)  # Detailed breakdown per question/criterion (pure academic feedback)
    highlights = Column(JSON, nullable=True)  # Targeted text highlights and reasoning
    is_calibration_sample = Column(Boolean, default=False)  # Sample set aside for examiner baseline
    
    # Evaluation metadata fields
    grading_duration = Column(Float, nullable=True)  # Execution duration in seconds
    model_used = Column(String, nullable=True)  # Model name e.g. google/gemini-2.5-flash
    prompt_version = Column(String, nullable=True)  # Prompt strategy version
    graded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    assignment = relationship("Assignment", back_populates="submissions")
    audit_logs = relationship("AuditLog", back_populates="submission", cascade="all, delete-orphan")
    evaluation_logs = relationship("EvaluationLog", back_populates="submission", cascade="all, delete-orphan")


class CalibrationSet(Base):
    __tablename__ = "calibration_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(String, ForeignKey("assignments.id"), nullable=False, index=True)
    question_number = Column(String, nullable=False, index=True)  # e.g. "Q6", "Q8"
    version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    assignment = relationship("Assignment", back_populates="calibration_sets")
    examples = relationship("CalibrationExample", back_populates="calibration_set", cascade="all, delete-orphan")


class CalibrationExample(Base):
    __tablename__ = "calibration_examples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(String, ForeignKey("assignments.id"), nullable=False, index=True)
    calibration_set_id = Column(Integer, ForeignKey("calibration_sets.id"), nullable=True, index=True)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=True, index=True)
    question_number = Column(String, nullable=False, index=True)  # e.g. "Q6", "Q8"
    student_text = Column(Text, nullable=False)
    examiner_score = Column(Float, nullable=False)
    max_score = Column(Float, nullable=False)
    examiner_feedback = Column(Text, nullable=True)
    anchor_type = Column(String, default="borderline")  # "high", "borderline", "low", "other"
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    assignment = relationship("Assignment", back_populates="calibration_examples")
    calibration_set = relationship("CalibrationSet", back_populates="examples")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False, index=True)
    lecturer_name = Column(String, default="Lecturer")
    action = Column(String, nullable=False)  # manual_override, status_change
    old_score = Column(Float, nullable=True)
    new_score = Column(Float, nullable=False)
    comment = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    submission = relationship("Submission", back_populates="audit_logs")


class EvaluationLog(Base):
    __tablename__ = "evaluation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False, index=True)
    assignment_id = Column(String, nullable=True, index=True)
    question_number = Column(String, nullable=True)
    grading_mode = Column(String, nullable=True)  # "zero_shot", "few_shot"
    calibration_version = Column(Integer, nullable=True)
    calibration_examples_count = Column(Integer, nullable=True)
    lecturer_score = Column(Float, nullable=True)
    ai_score = Column(Float, nullable=True)
    score_difference = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    latency_seconds = Column(Float, nullable=True)
    cost_estimate = Column(Float, default=0.0)
    prompt_version = Column(String, nullable=True)
    model_used = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    submission = relationship("Submission", back_populates="evaluation_logs")
