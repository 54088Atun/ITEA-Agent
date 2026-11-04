"""题库 / 组卷 / 考试相关请求模型"""
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

QuestionType = Literal["single", "multiple", "judge", "short"]


class QuestionCreate(BaseModel):
    course_id: int
    kp_id: Optional[int] = None
    type: QuestionType
    stem: str = Field(..., min_length=1, max_length=5000)
    options: List[Dict[str, str]] = []
    answer: str = Field(..., min_length=1, max_length=2000)
    analysis: Optional[str] = None
    difficulty: int = Field(3, ge=1, le=5)


class DraftGenerateRequest(BaseModel):
    count: int = Field(5, ge=1, le=20)
    kp_ids: List[int] = []
    types: List[QuestionType] = ["single", "multiple", "judge"]


class DraftAdoptRequest(BaseModel):
    indices: List[int] = []
    adopt_all: bool = False


class ExamPlanGenerateRequest(BaseModel):
    """考试科目/考核项建议生成参数"""
    duration_minutes: int = Field(90, ge=5, le=300)
    total_score: int = Field(100, ge=10, le=500)


class ExamQuestionItem(BaseModel):
    question_id: int
    score: int = Field(5, ge=1, le=100)


class ExamCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    course_id: int
    class_id: Optional[int] = None
    description: Optional[str] = None
    duration_minutes: int = Field(60, ge=5, le=300)
    due_days: Optional[int] = Field(None, ge=1, le=365)
    start_at: Optional[datetime] = None
    questions: List[ExamQuestionItem]
    publish: bool = True


class ExamSubmit(BaseModel):
    answers: Dict[str, str] = Field(default_factory=dict)
    violations: int = Field(0, ge=0, le=1000, description="前端统计的切屏次数")
    client_id: Optional[str] = Field(None, max_length=128)
    copy_count: int = Field(0, ge=0, le=1000)
    paste_count: int = Field(0, ge=0, le=1000)


class ExamHeartbeat(BaseModel):
    violations: int = Field(0, ge=0, le=1000)
    client_id: Optional[str] = Field(None, max_length=128)
    copy_count: int = Field(0, ge=0, le=1000)
    paste_count: int = Field(0, ge=0, le=1000)


class ShortGradeConfirm(BaseModel):
    scores: Dict[str, int] = Field(default_factory=dict, description="{question_id: score}")
