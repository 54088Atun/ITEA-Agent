"""课程相关请求/响应模型"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CourseCreate(BaseModel):
    name: str
    code: str
    syllabus: Optional[str] = None
    semester: Optional[str] = None


class CourseOut(BaseModel):
    id: int
    teacher_id: int
    name: str
    code: str
    syllabus: Optional[str] = None
    semester: Optional[str] = None
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

    class Config:
        from_attributes = True