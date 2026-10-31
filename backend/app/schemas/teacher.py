"""教师端相关请求/响应模型"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class LessonPlanRequest(BaseModel):
    course_id: int
    chapter: Optional[str] = None  # 指定章节,为空则按大纲整体规划
    hours: Optional[int] = None    # 课时数


class DraftAdoptRequest(BaseModel):
    """知识点草稿采纳:paths 为节点路径(如 "0"、"0-1"),adopt_all 时全部采纳"""
    paths: List[str] = []
    adopt_all: bool = False
    apply_syllabus: bool = False
    syllabus: Optional[str] = None  # 教师可在预览里编辑后覆盖


class WeakPointItem(BaseModel):
    kp_id: int
    kp_name: str
    avg_mastery: float
    wrong_count: int


class StudentBrief(BaseModel):
    user_id: int
    name: str
    overall_progress: float
    weak_count: int


class ClassReportOut(BaseModel):
    course_id: int
    course_name: str
    student_count: int
    avg_progress: float
    weak_points: List[WeakPointItem] = []
    students: List[StudentBrief] = []


class ExportRequest(BaseModel):
    type: str  # lesson_plan / preview_sheet / report
    course_id: int
    data: dict = {}
class InterviewAssignmentCreate(BaseModel):
    title: str
    class_id: Optional[int] = None
    course_id: Optional[int] = None
    description: Optional[str] = None
    due_days: Optional[int] = None
