"""作业 / 分享码相关请求模型"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class AssignmentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    kind: Literal["homework", "exam"] = "homework"
    course_id: Optional[int] = None
    class_id: Optional[int] = None
    description: Optional[str] = None
    reference_answer: Optional[str] = None
    due_days: Optional[int] = Field(None, ge=1, le=365, description="从今天起的天数")
    due_at: Optional[datetime] = None
    allow_late: bool = False
    publish: bool = True


class SubmissionCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)
    attachment_url: Optional[str] = None
    draft: bool = False


class GradeConfirmRequest(BaseModel):
    score: int = Field(..., ge=0, le=100)
    feedback: Optional[str] = None


class CourseShareCreate(BaseModel):
    expires_days: int = Field(7, ge=1, le=365)
    max_uses: int = Field(1, ge=1, le=100)


class CourseImportRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=16)


class AssignmentBatchPublishRequest(BaseModel):
    assignment_ids: List[int] = Field(..., min_length=1)
    dry_run: bool = True


class AssignmentRemindRequest(BaseModel):
    dry_run: bool = True
    message: Optional[str] = None


class StudentFeedbackRequest(BaseModel):
    assignment_id: int
    score: int = Field(..., ge=0, le=100)
    feedback: Optional[str] = None


class CourseAnnouncementRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    class_id: Optional[int] = None
