"""教师端相关请求/响应模型"""
from pydantic import BaseModel, Field
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


class ClassAssignmentStat(BaseModel):
    assignment_id: int
    title: str
    due_at: Optional[datetime] = None
    submitted: int
    confirmed: int
    pending: int
    avg_score: Optional[float] = None


class ClassExamStat(BaseModel):
    exam_id: int
    title: str
    submitted: int
    pending_manual: int
    avg_score: Optional[float] = None


class ClassStatsOut(BaseModel):
    """班级维度学情与作业/考试统计(CL-05)"""
    class_id: int
    class_name: str
    course_id: Optional[int] = None
    course_name: Optional[str] = None
    student_count: int
    avg_progress: float
    weak_points: List[WeakPointItem] = []
    students: List[StudentBrief] = []
    assignments: List[ClassAssignmentStat] = []
    exams: List[ClassExamStat] = []


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
    duration_minutes: int = Field(30, ge=1, le=120)
