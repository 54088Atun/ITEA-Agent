"""班级与邀请码相关请求/响应模型"""
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class ClassCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    course_id: Optional[int] = None
    semester: Optional[str] = Field(None, max_length=20)
    description: Optional[str] = None
    invite_max_uses: int = Field(50, ge=1, le=1000)
    invite_days: int = Field(7, ge=1, le=365, description="邀请码有效天数")


class ClassUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    course_id: Optional[int] = None
    semester: Optional[str] = Field(None, max_length=20)
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|archived)$")


class ClassOut(BaseModel):
    id: int
    teacher_id: int
    teacher_name: Optional[str] = None
    course_id: Optional[int] = None
    course_name: Optional[str] = None
    name: str
    semester: Optional[str] = None
    description: Optional[str] = None
    status: str
    invite_code: str
    invite_expires_at: Optional[datetime] = None
    invite_max_uses: int
    invite_used: int
    member_count: int = 0
    created_at: Optional[datetime] = None


class ClassMemberOut(BaseModel):
    student_id: int
    name: str
    email: str
    joined_at: Optional[datetime] = None
    status: str


class ClassMembersOut(BaseModel):
    total: int
    items: List[ClassMemberOut]


class ClassInviteRequest(BaseModel):
    email: Optional[str] = None
    student_id: Optional[int] = None
    name: Optional[str] = None


class JoinClassRequest(BaseModel):
    invite_code: str = Field(..., min_length=4, max_length=16)


class JoinClassOut(BaseModel):
    class_id: int
    class_name: str
    course_id: Optional[int] = None
    joined: bool


class InviteResetOut(BaseModel):
    invite_code: str
    invite_expires_at: Optional[datetime] = None
    invite_max_uses: int
