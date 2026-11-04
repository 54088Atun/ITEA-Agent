"""课程相关请求/响应模型"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CourseCreate(BaseModel):
    name: str
    code: str
    syllabus: Optional[str] = None
    semester: Optional[str] = None


class CourseCollaboratorAdd(BaseModel):
    teacher_id: int


class CourseDuplicateRequest(BaseModel):
    """复制课程结构时的可选覆盖项;留空则沿用源课程/自动生成"""
    name: Optional[str] = Field(None, max_length=100)
    code: Optional[str] = Field(None, max_length=20)
    semester: Optional[str] = Field(None, max_length=20)


class CourseOut(BaseModel):
    id: int
    teacher_id: int
    name: str
    code: str
    syllabus: Optional[str] = None
    semester: Optional[str] = None
    audit_status: str = "approved"
    archived_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class MaterialOut(BaseModel):
    id: int
    course_id: int
    type: str
    title: str
    file_path: str
    chunk_count: int
    uploaded_at: datetime
    moderation_status: str = "approved"
    parse_status: Optional[str] = None
    parse_progress: int = 0
    parse_error: Optional[str] = None
    parse_attempts: int = 0

    class Config:
        from_attributes = True