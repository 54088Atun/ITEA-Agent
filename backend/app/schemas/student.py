"""学生端相关请求/响应模型"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


class WrongQuestionOut(BaseModel):
    id: int
    kp_id: Optional[int] = None
    question_content: str
    error_type: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ReviewPlanOut(BaseModel):
    id: int
    wrong_question_id: int
    next_review_at: datetime
    review_count: int
    interval_days: int
    status: str

    class Config:
        from_attributes = True


class MasteryItem(BaseModel):
    kp_id: int
    kp_name: str
    mastery_level: int


class ProgressOut(BaseModel):
    course_id: int
    overall_progress: float
    mastery: List[MasteryItem] = []


class InterviewStartRequest(BaseModel):
    course_id: int
    focus_kp_ids: List[int] = []  # 定向补强知识点,为空则自动从薄弱点选取


class InterviewRecordOut(BaseModel):
    id: int
    round: int
    question: str
    answer: Optional[str] = None
    score: Optional[int] = None
    feedback: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class EnrollOut(BaseModel):
    course_id: int
    profile_id: int
    joined: bool = True


class PracticeSubmitRequest(BaseModel):
    course_id: int
    kp_id: Optional[int] = None
    type: Literal["in_class", "variant", "code"]
    content: str = Field(..., min_length=1)
    is_correct: Optional[bool] = None


class PracticeGenerateRequest(BaseModel):
    course_id: int
    count: int = 3


class WrongQuestionCreate(BaseModel):
    course_id: int
    question_content: str
    kp_name: Optional[str] = None
    error_type: Optional[str] = "概念不清"


class NotificationPreferenceUpdate(BaseModel):
    assignment_enabled: bool = True
    exam_enabled: bool = True
    interview_enabled: bool = True
    review_enabled: bool = True
    quiet_start: Optional[str] = Field(
        None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )
    quiet_end: Optional[str] = Field(
        None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )
