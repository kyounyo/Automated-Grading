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
    due_date: Optional[str] = ""
    rubric_data: Optional[List[Dict[str, Any]]] = []
    model_answer: Optional[str] = ""
    calibration_enabled: Optional[bool] = False
    calibration_sample_size: Optional[int] = 3
    calibration_settings: Optional[Dict[str, Any]] = None


class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    course_code: Optional[str] = None
    due_date: Optional[str] = None
    calibration_enabled: Optional[bool] = None
    calibration_sample_size: Optional[int] = None
    calibration_settings: Optional[Dict[str, Any]] = None


class AssignmentResponse(BaseModel):
    id: str
    title: str
    course_code: str
    due_date: Optional[str] = ""
    status: str
    total_submissions: int
    average_score: float
    rubric_data: Optional[List[Dict[str, Any]]] = None
    model_answer: Optional[str] = Field(default=None, exclude=True)
    calibration_enabled: Optional[bool] = False
    calibration_sample_size: Optional[int] = 3
    calibration_settings: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class ScoreOverrideRequest(BaseModel):
    new_score: float
    comment: Optional[str] = "Manual grade adjustment by lecturer"
    lecturer_name: Optional[str] = "Lecturer"
    updated_breakdown: Optional[List[Dict[str, Any]]] = None


class SubmissionResponse(BaseModel):
    id: str
    assignment_id: str
    batch_id: Optional[str] = None
    student_id: str
    student_name: Optional[str] = None
    student_email: Optional[str] = None
    file_name: str
    file_s3_url: Optional[str] = None
    file_path: Optional[str] = None
    raw_text: Optional[str] = None
    score: Optional[float] = None
    confidence_score: Optional[float] = None
    status: str
    feedback: Optional[Dict[str, Any]] = None
    highlights: Optional[List[Dict[str, Any]]] = None
    is_calibration_sample: Optional[bool] = False
    grading_duration: Optional[float] = None
    model_used: Optional[str] = None
    prompt_version: Optional[str] = None
    graded_at: Optional[datetime.datetime] = None
    created_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class CalibrationExampleCreate(BaseModel):
    question_number: str
    student_text: str
    examiner_score: float
    max_score: float
    examiner_feedback: Optional[str] = ""
    anchor_type: Optional[str] = "borderline"  # "high", "borderline", "low", "other"
    submission_id: Optional[str] = None


class CalibrationExampleResponse(BaseModel):
    id: int
    assignment_id: str
    calibration_set_id: Optional[int] = None
    submission_id: Optional[str] = None
    question_number: str
    student_text: str
    examiner_score: float
    max_score: float
    examiner_feedback: Optional[str] = None
    anchor_type: str
    version: int
    created_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class CalibrationQuestionStatus(BaseModel):
    question_number: str
    sample_count: int
    target_count: int
    status: str  # "zero_shot", "few_shot_available", "calibrated"
    version: int
    examples: Optional[List[CalibrationExampleResponse]] = []


class CalibrationStatusResponse(BaseModel):
    assignment_id: str
    calibration_enabled: bool
    calibration_sample_size: int
    total_calibrated_examples: int
    questions: List[CalibrationQuestionStatus] = []
    calibration_sample_submission_ids: List[str] = []


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

