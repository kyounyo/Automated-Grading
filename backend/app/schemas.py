from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import datetime


class RubricCriterion(BaseModel):
    id: str
    description: str
    max_marks: float


class RubricItem(BaseModel):
    question_number: str
    max_score: float
    criteria: Optional[List[RubricCriterion]] = []


class AssignmentCreate(BaseModel):
    title: str
    course_code: str
    due_date: str
    rubric_data: Optional[List[Dict[str, Any]]] = []
    model_answer: Optional[str] = ""


class AssignmentResponse(BaseModel):
    id: str
    title: str
    course_code: str
    due_date: str
    status: str
    total_submissions: int
    average_score: float
    rubric_data: Optional[List[Dict[str, Any]]] = None
    model_answer: Optional[str] = Field(default=None, exclude=True)
    created_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class ScoreOverrideRequest(BaseModel):
    new_score: float
    comment: Optional[str] = "Manual grade adjustment by lecturer"
    lecturer_name: Optional[str] = "Lecturer"


class SubmissionResponse(BaseModel):
    id: str
    assignment_id: str
    batch_id: Optional[str] = None
    student_id: str
    student_name: str
    file_name: str
    file_s3_url: Optional[str] = None
    file_path: Optional[str] = None
    raw_text: Optional[str] = None
    score: Optional[float] = None
    confidence_score: Optional[float] = None
    status: str
    feedback: Optional[Dict[str, Any]] = None
    highlights: Optional[List[Dict[str, Any]]] = None
    grading_duration: Optional[float] = None
    model_used: Optional[str] = None
    prompt_version: Optional[str] = None
    graded_at: Optional[datetime.datetime] = None
    created_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class AuditLogResponse(BaseModel):
    id: int
    submission_id: str
    lecturer_name: str
    action: str
    old_score: Optional[float] = None
    new_score: float
    comment: Optional[str] = None
    timestamp: datetime.datetime

    class Config:
        from_attributes = True


class UploadResponse(BaseModel):
    message: str
    submission_id: str
    batch_id: Optional[str] = None
    file_name: str
    file_s3_url: Optional[str] = None
    file_path: str
