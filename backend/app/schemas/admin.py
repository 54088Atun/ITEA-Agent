"""管理端相关请求/响应模型"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime

from app.schemas.course import CourseCreate, MaterialOut


# ---------- 请求 ----------

class UserCreate(BaseModel):
    role: str = Field(..., pattern="^(teacher|student|admin)$")
    admin_level: Optional[str] = Field(None, pattern="^(super|normal|observer)$")
    name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class UserUpdate(BaseModel):
    role: Optional[str] = Field(None, pattern="^(teacher|student|admin)$")
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    email: Optional[EmailStr] = None


class AdminLevelUpdate(BaseModel):
    admin_level: str = Field(..., pattern="^(super|normal|observer)$")


class UserStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(active|disabled)$")


class PasswordReset(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


class CourseAuditRequest(BaseModel):
    audit_status: str = Field(..., pattern="^(pending|approved|rejected)$")


class AdminCourseCreate(CourseCreate):
    teacher_id: Optional[int] = None  # 缺省归当前管理员


class ConfigItemUpdate(BaseModel):
    config_key: str
    config_value: Optional[str] = None


class ConfigUpdate(BaseModel):
    items: List[ConfigItemUpdate]


# ---------- 响应 ----------

class UserAdminOut(BaseModel):
    id: int
    role: str
    admin_level: Optional[str] = None
    name: str
    email: str
    status: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AdminCourseOut(BaseModel):
    id: int
    teacher_id: int
    teacher_name: Optional[str] = None
    name: str
    code: str
    syllabus: Optional[str] = None
    semester: Optional[str] = None
    audit_status: str
    created_at: datetime


class RiskLogOut(BaseModel):
    id: int
    user_id: int
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    request_content: str
    risk_type: str
    action_taken: str
    created_at: datetime


class InteractionLogOut(BaseModel):
    id: int
    user_id: int
    user_name: Optional[str] = None
    session_id: str
    role: Optional[str] = None
    branch: Optional[str] = None
    content: Optional[str] = None
    created_at: datetime


class OperationLogOut(BaseModel):
    id: int
    admin_id: int
    admin_name: Optional[str] = None
    action: str
    target_type: str
    target_id: Optional[int] = None
    detail: Optional[str] = None
    ip: Optional[str] = None
    created_at: datetime


class ConfigItemOut(BaseModel):
    id: int
    config_key: str
    config_value: Optional[str] = None
    description: Optional[str] = None
    updated_by: Optional[int] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- 分页 ----------

class UserPage(BaseModel):
    total: int
    items: List[UserAdminOut]


class CoursePage(BaseModel):
    total: int
    items: List[AdminCourseOut]


class MaterialPage(BaseModel):
    total: int
    items: List[MaterialOut]


class RiskLogPage(BaseModel):
    total: int
    items: List[RiskLogOut]


class InteractionLogPage(BaseModel):
    total: int
    items: List[InteractionLogOut]


class OperationLogPage(BaseModel):
    total: int
    items: List[OperationLogOut]


class ConfigListOut(BaseModel):
    items: List[ConfigItemOut]
