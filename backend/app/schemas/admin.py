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


class SiteContentUpdate(BaseModel):
    """站点内容:首页与联系页,整体以 JSON 结构保存,缺省表示不修改"""
    home: Optional[dict] = None
    contact: Optional[dict] = None


class AdminActionPreviewRequest(BaseModel):
    """管理动作预览:先看影响范围,不写库"""
    action: str
    params: dict = Field(default_factory=dict)


class AdminActionExecuteRequest(AdminActionPreviewRequest):
    """确认执行:必须携带预览返回的令牌与幂等键"""
    confirmation_token: str
    idempotency_key: str


class UserBatchStatusRequest(BaseModel):
    """批量启用/禁用账号:dry_run 为真时只预演不写库"""
    user_ids: List[int] = Field(..., min_length=1)
    status: str = Field(..., pattern="^(active|disabled)$")
    dry_run: bool = True


class CourseBatchAuditRequest(BaseModel):
    """批量课程审核:dry_run 为真时只预演不写库"""
    course_ids: List[int] = Field(..., min_length=1)
    audit_status: str = Field(..., pattern="^(pending|approved|rejected)$")
    dry_run: bool = True


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
    # 开关类配置的实际生效值:DB 开关为 on 但依赖服务未配置时为 off
    effective_value: Optional[str] = None
    effective_note: Optional[str] = None

    class Config:
        from_attributes = True


class BatchItemError(BaseModel):
    """批量操作中未生效的单项及原因"""
    id: int
    reason: str


class BatchResult(BaseModel):
    """批量操作结果:生效 / 跳过 / 失败 三分类明细"""
    affected: List[int] = []
    skipped: List[BatchItemError] = []
    failed: List[BatchItemError] = []
    dry_run: bool = True


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
