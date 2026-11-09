"""管理端路由:用户 / 课程审核 / 素材 / 风控 / 日志 / 配置 / 统计 / 前台镜像"""
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, HTTPException, Query, Request, Response,
    UploadFile, File, Form,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.core.deps import (
    require_admin, require_admin_write, require_super_admin, admin_level_of,
)
from app.core.security import hash_password
from app.models.user import User
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.profile import StudentProfile, MasteryRecord, WrongQuestion, ReviewPlan
from app.models.interview import InterviewRecord
from app.models.classroom import Classroom, ClassMember, CourseEnrollment
from app.models.log import (
    InteractionLog, RiskLog, OperationLog, SystemConfig, AgentRun, WriteAuditLog,
)
from app.schemas.course import CourseCreate, CourseOut, MaterialOut
from app.schemas.student import (
    ProgressOut, MasteryItem, WrongQuestionOut, ReviewPlanOut,
    InterviewRecordOut, InterviewStartRequest,
)
from app.schemas.teacher import LessonPlanRequest, ClassReportOut, ExportRequest
from app.schemas.agent import ChatRequest
from app.schemas.admin import (
    UserCreate, UserUpdate, UserStatusUpdate, PasswordReset, AdminLevelUpdate,
    CourseAuditRequest, AdminCourseCreate, ConfigUpdate, SiteContentUpdate,
    AdminActionPreviewRequest, AdminActionExecuteRequest,
    UserAdminOut, AdminCourseOut, RiskLogOut, InteractionLogOut,
    OperationLogOut, ConfigItemOut, UserPage, CoursePage, MaterialPage,
    RiskLogPage, InteractionLogPage, OperationLogPage, ConfigListOut,
    UserBatchStatusRequest, CourseBatchAuditRequest, BatchItemError, BatchResult,
)
from app.api.site import (
    load_site_content, HOME_KEY, CONTACT_KEY,
)
from app.services.audit_service import write_operation_log
from app.services.asr import asr_enabled
from app.services.feature_flags import is_enabled
from app.services.vision import vision_enabled
from app.services.runtime_metrics import runtime_metrics_snapshot
from app.services.storage_cleanup import cleanup_uploads_task
from app.api.chat import stream_agent_response, SSE_HEADERS
from app.api.student import _ensure_profile, _build_progress
from app.api.teacher import build_class_report, save_material
from app.agent.tools.doc_generator import doc_generator
from app.services.admin_actions import (
    action_catalog, preview_action, execute_previewed_action,
)
from app.services.agent_runs import (
    list_runs as list_agent_runs, get_run as get_agent_run, run_stats as agent_run_stats,
)
from app.services.agent_trace import list_spans

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["管理端"])


# ---------- 工具函数 ----------

def _client_ip(request: Request) -> Optional[str]:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


# 开关类配置依赖的外部能力:DB 开关打开但服务未配置时,实际不生效
_EFFECTIVE_CHECKS = {
    "feature_asr": (asr_enabled, "语音识别服务未配置"),
    "feature_image_vision": (vision_enabled, "识图服务未配置"),
}


def _config_items(db: Session, rows) -> List[ConfigItemOut]:
    """配置列表:附带开关类配置的实际生效值,避免管理端误判能力可用"""
    items = []
    for cfg in rows:
        item = ConfigItemOut.model_validate(cfg)
        check = _EFFECTIVE_CHECKS.get(cfg.config_key)
        if check:
            probe, note = check
            switched_on = is_enabled(db, cfg.config_key)
            ready = bool(probe())
            item.effective_value = "on" if switched_on and ready else "off"
            if switched_on and not ready:
                item.effective_note = note
        items.append(item)
    return items


def _audit(db: Session, admin: User, request: Request, action: str,
           target_type: str, target_id: Optional[int] = None,
           detail: Optional[str] = None, commit: bool = True):
    return write_operation_log(
        db, admin, action, target_type, target_id, detail, _client_ip(request), commit,
    )


def _commit_with_audit(db: Session, admin: User, request: Request, action: str,
                       target_type: str, target_id: Optional[int] = None,
                       detail: Optional[str] = None):
    try:
        log = _audit(
            db, admin, request, action, target_type, target_id, detail, commit=False,
        )
        if log is None:
            raise HTTPException(status_code=500, detail="操作审计写入失败")
        db.commit()
    except Exception:
        db.rollback()
        raise


def _get_course_or_404(db: Session, course_id: int) -> Course:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


def _ensure_super_survives(db: Session, target: User):
    """按固定顺序锁定管理员，串行化降级或停用超管前的检查。"""
    if target.role != "admin" or admin_level_of(target) != "super":
        return
    admins = (
        db.query(User)
        .filter(User.role == "admin")
        .order_by(User.id)
        .with_for_update()
        .all()
    )
    locked_target = next((user for user in admins if user.id == target.id), None)
    if locked_target is None or admin_level_of(locked_target) != "super":
        return
    if not any(
        user.id != target.id
        and user.status == "active"
        and admin_level_of(user) == "super"
        for user in admins
    ):
        raise HTTPException(status_code=400, detail="系统至少保留一个启用状态的超级管理员")


def _aggregate_progress(db: Session, course_id: int) -> ProgressOut:
    """课程整体学情(未指定学生时按全班聚合)"""
    profiles = db.query(StudentProfile).filter(StudentProfile.course_id == course_id).all()
    if not profiles:
        return ProgressOut(course_id=course_id, overall_progress=0, mastery=[])

    profile_ids = [p.id for p in profiles]
    avg_progress = sum(float(p.overall_progress or 0) for p in profiles) / len(profiles)
    rows = (
        db.query(
            KnowledgePoint.id, KnowledgePoint.name,
            func.avg(MasteryRecord.mastery_level).label("avg_m"),
        )
        .join(MasteryRecord, MasteryRecord.kp_id == KnowledgePoint.id)
        .filter(MasteryRecord.profile_id.in_(profile_ids))
        .group_by(KnowledgePoint.id, KnowledgePoint.name)
        .all()
    )
    mastery = [
        MasteryItem(kp_id=kp_id, kp_name=name, mastery_level=int(round(float(avg_m or 0))))
        for kp_id, name, avg_m in rows
    ]
    return ProgressOut(course_id=course_id, overall_progress=round(avg_progress, 1), mastery=mastery)


# ==================== 管理助手 ====================

@router.get("/metrics")
def get_runtime_metrics(admin: User = Depends(require_admin)):
    return {"operations": runtime_metrics_snapshot()}


@router.get("/actions")
def list_admin_actions(admin: User = Depends(require_admin)):
    """管理动作目录:助手与前端共用"""
    return {"actions": action_catalog()}


@router.post("/actions/preview")
def preview_admin_action(
    req: AdminActionPreviewRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """预览批量动作影响范围,返回确认令牌,不写库"""
    return preview_action(db, admin, req.action, req.params)


@router.post("/actions/execute")
def execute_admin_action(
    req: AdminActionExecuteRequest,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """凭预览令牌执行动作;同一幂等键只执行一次"""
    return execute_previewed_action(
        db, admin, req.action, req.params,
        req.confirmation_token, req.idempotency_key,
    )


@router.get("/agent/runs")
def admin_agent_runs(
    status: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    branch: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Agent 运行列表:按状态、用户、分支筛选"""
    return list_agent_runs(
        db, status=status, user_id=user_id, branch=branch,
        page=page, page_size=page_size,
    )


@router.get("/agent/runs/{run_id}")
def admin_agent_run_detail(
    run_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Agent 运行详情:route、tool、reflect 与耗时"""
    run = get_agent_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run


@router.get("/agent/runs/{run_id}/trace")
def admin_agent_run_trace(
    run_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Agent 运行步骤回放:逐条 span 的入参、结果、token 与耗时"""
    run = get_agent_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return {"run_id": run_id, "spans": list_spans(db, run_id)}


@router.get("/agent/stats")
def admin_agent_stats(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Agent 运行概览:状态分布与平均耗时"""
    return agent_run_stats(db)


@router.post("/chat/stream")
async def admin_chat_stream(
    req: ChatRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理助手(SSE):可读取平台数据,也可执行已登记的管理任务。"""
    return StreamingResponse(
        stream_agent_response(req, admin, db, force_branch="admin", request=request),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ==================== 用户管理 ====================

@router.get("/users", response_model=UserPage)
def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    role: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户列表(分页 + 角色/状态/关键词筛选)"""
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if status_:
        query = query.filter(User.status == status_)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(User.name.like(like), User.email.like(like)))

    total = query.count()
    items = query.order_by(User.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [UserAdminOut.model_validate(u) for u in items]}


@router.post("/users", response_model=UserAdminOut)
def create_user(
    req: UserCreate,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """创建账号；管理员账号仅超管可创建。"""
    if req.role == "admin" and admin_level_of(admin) != "super":
        raise HTTPException(status_code=403, detail="仅超级管理员可创建管理员")
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    user = User(
        role=req.role, name=req.name, email=req.email,
        admin_level=(req.admin_level or "normal") if req.role == "admin" else None,
        password_hash=hash_password(req.password), status="active",
        # 管理员开通视为已核验邮箱,不受登录验证拦截
        email_verified_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()
    _commit_with_audit(
        db, admin, request, "create", "user", user.id,
        json.dumps({"email": user.email, "role": user.role}, ensure_ascii=False),
    )
    db.refresh(user)
    return UserAdminOut.model_validate(user)


@router.get("/users/{user_id}", response_model=UserAdminOut)
def get_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserAdminOut.model_validate(user)


@router.get("/users/{user_id}/overview")
def get_user_overview(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户概览:基础信息 + 关联课程 + 最近操作 + 风控命中

    管理助手回答“这个用户什么情况”时一次取齐,不用跨多个接口拼装。
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    courses = []
    if user.role == "teacher":
        rows = (
            db.query(Course)
            .filter(Course.teacher_id == user_id)
            .order_by(Course.id.desc())
            .limit(20)
            .all()
        )
        courses = [
            {
                "id": row.id, "name": row.name, "code": row.code,
                "audit_status": row.audit_status, "relation": "owner",
            }
            for row in rows
        ]
    elif user.role == "student":
        rows = (
            db.query(Course, User.name)
            .join(CourseEnrollment, CourseEnrollment.course_id == Course.id)
            .outerjoin(User, Course.teacher_id == User.id)
            .filter(CourseEnrollment.student_id == user_id)
            .order_by(Course.id.desc())
            .limit(20)
            .all()
        )
        courses = [
            {
                "id": row.id, "name": row.name, "code": row.code,
                "audit_status": row.audit_status, "relation": "enrolled",
                "teacher_name": teacher_name,
            }
            for row, teacher_name in rows
        ]

    recent_actions = []
    for log in (
        db.query(OperationLog).filter(OperationLog.admin_id == user_id)
        .order_by(OperationLog.id.desc()).limit(10).all()
    ):
        recent_actions.append({
            "source": "operation",
            "action": log.action,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "detail": log.detail,
            "created_at": log.created_at,
        })
    for log in (
        db.query(WriteAuditLog).filter(WriteAuditLog.user_id == user_id)
        .order_by(WriteAuditLog.id.desc()).limit(10).all()
    ):
        recent_actions.append({
            "source": "write_audit",
            "action": log.action,
            "action_label": log.action_label,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "detail": log.detail,
            "status": log.status,
            "created_at": log.created_at,
        })
    recent_actions.sort(
        key=lambda item: item["created_at"] or datetime.min, reverse=True,
    )

    risk_total = (
        db.query(func.count(RiskLog.id)).filter(RiskLog.user_id == user_id).scalar()
        or 0
    )
    risk_rows = (
        db.query(RiskLog).filter(RiskLog.user_id == user_id)
        .order_by(RiskLog.id.desc()).limit(5).all()
    )
    return {
        "user": {
            "id": user.id, "name": user.name, "email": user.email,
            "role": user.role, "admin_level": user.admin_level,
            "status": user.status, "created_at": user.created_at,
        },
        "courses": courses,
        "recent_actions": recent_actions[:10],
        "risk_hits": {
            "total": int(risk_total),
            "recent": [
                {
                    "id": row.id,
                    "risk_type": row.risk_type,
                    "action_taken": row.action_taken,
                    "request_content": (row.request_content or "")[:200],
                    "created_at": row.created_at,
                }
                for row in risk_rows
            ],
        },
    }


@router.put("/users/{user_id}", response_model=UserAdminOut)
def update_user(
    user_id: int,
    req: UserUpdate,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """编辑用户；涉及管理员角色时仅超管可操作。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if (user.role == "admin" or req.role == "admin") and admin_level_of(admin) != "super":
        raise HTTPException(status_code=403, detail="仅超级管理员可管理管理员账号")
    if user.id == admin.id and req.role is not None and req.role != user.role:
        raise HTTPException(status_code=400, detail="不能修改当前登录账号的角色")

    if req.email and req.email != user.email:
        if db.query(User).filter(User.email == req.email, User.id != user_id).first():
            raise HTTPException(status_code=400, detail="该邮箱已被占用")

    before = {"role": user.role, "admin_level": user.admin_level,
              "name": user.name, "email": user.email}
    if req.role is not None and req.role != user.role:
        if user.role == "admin" and req.role != "admin":
            _ensure_super_survives(db, user)
        if req.role == "admin":
            user.admin_level = "normal"
        else:
            user.admin_level = None
        user.role = req.role
    if req.name is not None:
        user.name = req.name
    if req.email is not None:
        user.email = req.email
    after = {"role": user.role, "admin_level": user.admin_level,
             "name": user.name, "email": user.email}
    _commit_with_audit(
        db, admin, request, "update", "user", user.id,
        json.dumps({"before": before, "after": after}, ensure_ascii=False),
    )
    db.refresh(user)
    return UserAdminOut.model_validate(user)


@router.patch("/users/{user_id}/status", response_model=UserAdminOut)
def update_user_status(
    user_id: int,
    req: UserStatusUpdate,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """启用/禁用账号；管理员账号仅超管可操作。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin" and admin_level_of(admin) != "super":
        raise HTTPException(status_code=403, detail="仅超级管理员可管理管理员账号")
    if user.id == admin.id and req.status == "disabled":
        raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
    if req.status == "disabled":
        _ensure_super_survives(db, user)

    user.status = req.status
    if req.status == "disabled":
        # 禁用后立即吊销已签发令牌,无需等待过期
        user.token_version = int(user.token_version or 0) + 1
    action = "enable" if req.status == "active" else "disable"
    _commit_with_audit(
        db, admin, request, action, "user", user.id,
        json.dumps({"status": req.status}, ensure_ascii=False),
    )
    db.refresh(user)
    return UserAdminOut.model_validate(user)


@router.patch("/users/batch-status", response_model=BatchResult)
def batch_update_user_status(
    req: UserBatchStatusRequest,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """批量启用/禁用账号:dry_run 时只预演;管理员账号仅超管可操作"""
    ids = list(dict.fromkeys(req.user_ids))
    result = BatchResult(dry_run=req.dry_run)
    found = {user.id: user for user in db.query(User).filter(User.id.in_(ids)).all()}

    # 禁用批次需先锁定管理员集合,避免同批把最后一个超管一并下线
    active_supers = set()
    if req.status == "disabled":
        query = db.query(User).filter(User.role == "admin").order_by(User.id)
        if not req.dry_run:
            query = query.with_for_update()
        active_supers = {
            user.id for user in query.all()
            if user.status == "active" and admin_level_of(user) == "super"
        }

    changed = []
    for user_id in ids:
        user = found.get(user_id)
        if user is None:
            result.failed.append(BatchItemError(id=user_id, reason="用户不存在"))
            continue
        if user.role == "admin" and admin_level_of(admin) != "super":
            result.skipped.append(BatchItemError(id=user_id, reason="仅超级管理员可管理管理员账号"))
            continue
        if user.id == admin.id and req.status == "disabled":
            result.skipped.append(BatchItemError(id=user_id, reason="不能禁用当前登录账号"))
            continue
        if user.status == req.status:
            result.skipped.append(BatchItemError(id=user_id, reason="状态未变化"))
            continue
        if req.status == "disabled" and user.id in active_supers:
            remaining = active_supers - {user.id}
            if not remaining:
                result.skipped.append(
                    BatchItemError(id=user_id, reason="系统至少保留一个启用状态的超级管理员"),
                )
                continue
            active_supers = remaining
        changed.append(user)

    result.affected = [user.id for user in changed]
    if req.dry_run or not changed:
        return result

    for user in changed:
        user.status = req.status
        if req.status == "disabled":
            # 禁用后立即吊销已签发令牌,无需等待过期
            user.token_version = int(user.token_version or 0) + 1
    action = "batch_enable" if req.status == "active" else "batch_disable"
    _commit_with_audit(
        db, admin, request, action, "user", None,
        json.dumps({"status": req.status, "user_ids": result.affected}, ensure_ascii=False),
    )
    return result


@router.patch("/users/{user_id}/reset-password", response_model=UserAdminOut)
def reset_password(
    user_id: int,
    req: PasswordReset,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """重置密码；管理员账号仅超管可操作。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin" and admin_level_of(admin) != "super":
        raise HTTPException(status_code=403, detail="仅超级管理员可管理管理员账号")

    user.password_hash = hash_password(req.new_password)
    # 管理员重置密码后,该用户旧令牌立即失效
    user.token_version = int(user.token_version or 0) + 1
    _commit_with_audit(db, admin, request, "update", "user", user.id, "password_reset")
    db.refresh(user)
    return UserAdminOut.model_validate(user)


@router.patch("/users/{user_id}/admin-level", response_model=UserAdminOut)
def update_admin_level(
    user_id: int,
    req: AdminLevelUpdate,
    request: Request,
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """分配管理员级别；仅超管可操作，且不能降低自己的权限。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role != "admin":
        raise HTTPException(status_code=400, detail="目标用户不是管理员")
    if user.id == admin.id and req.admin_level != admin_level_of(admin):
        raise HTTPException(status_code=400, detail="不能降低当前登录账号的管理员级别")
    if admin_level_of(user) == "super" and req.admin_level != "super":
        _ensure_super_survives(db, user)

    before = user.admin_level
    user.admin_level = req.admin_level
    _commit_with_audit(
        db, admin, request, "update_admin_level", "user", user.id,
        json.dumps({"before": before, "after": user.admin_level}, ensure_ascii=False),
    )
    db.refresh(user)
    return UserAdminOut.model_validate(user)


# ==================== 课程管理 ====================

@router.get("/courses", response_model=CoursePage)
def list_courses(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    audit_status: Optional[str] = Query(None),
    semester: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """全部课程(分页 + 审核状态/学期/关键词筛选)"""
    query = db.query(Course, User.name).outerjoin(User, Course.teacher_id == User.id)
    if audit_status:
        query = query.filter(Course.audit_status == audit_status)
    if semester:
        query = query.filter(Course.semester == semester)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(Course.name.like(like), Course.code.like(like)))

    total = query.count()
    rows = query.order_by(Course.id.desc()).offset((page - 1) * size).limit(size).all()
    items = [
        AdminCourseOut(
            id=c.id, teacher_id=c.teacher_id, teacher_name=tname,
            name=c.name, code=c.code, syllabus=c.syllabus, semester=c.semester,
            audit_status=c.audit_status, created_at=c.created_at,
        )
        for c, tname in rows
    ]
    return {"total": total, "items": items}


@router.get("/courses/{course_id}/overview")
def get_course_overview(
    course_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """课程概览:课程、教师、素材、知识点、学生数与审核历史一次返回"""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    teacher = db.query(User).filter(User.id == course.teacher_id).first()

    material_rows = (
        db.query(CourseMaterial.type, func.count(CourseMaterial.id))
        .filter(CourseMaterial.course_id == course_id)
        .group_by(CourseMaterial.type)
        .all()
    )
    materials_by_type = {str(kind): int(count) for kind, count in material_rows}

    class_ids = [
        cid for (cid,) in db.query(Classroom.id)
        .filter(Classroom.course_id == course_id).all()
    ]
    student_total = 0
    if class_ids:
        student_total = int(
            db.query(func.count(func.distinct(ClassMember.student_id)))
            .filter(
                ClassMember.class_id.in_(class_ids),
                ClassMember.status == "active",
                ClassMember.role != "teacher",
            )
            .scalar()
            or 0
        )
    enrollment_total = int(
        db.query(func.count(CourseEnrollment.id))
        .filter(CourseEnrollment.course_id == course_id)
        .scalar()
        or 0
    )
    kp_total = int(
        db.query(func.count(KnowledgePoint.id))
        .filter(KnowledgePoint.course_id == course_id)
        .scalar()
        or 0
    )

    audit_rows = (
        db.query(OperationLog, User.name)
        .outerjoin(User, OperationLog.admin_id == User.id)
        .filter(
            OperationLog.target_type == "course",
            OperationLog.target_id == course_id,
        )
        .order_by(OperationLog.id.desc())
        .limit(10)
        .all()
    )
    return {
        "course": {
            "id": course.id, "name": course.name, "code": course.code,
            "semester": course.semester, "audit_status": course.audit_status,
            "archived": course.archived_at is not None,
            "deleted": course.deleted_at is not None,
            "created_at": course.created_at,
        },
        "teacher": {
            "id": teacher.id if teacher else None,
            "name": teacher.name if teacher else None,
            "email": teacher.email if teacher else None,
            "status": teacher.status if teacher else None,
        },
        "materials": {
            "total": sum(materials_by_type.values()),
            "by_type": materials_by_type,
        },
        "knowledge_points": kp_total,
        "classes": {
            "total": len(class_ids),
            "students": student_total,
            "enrollments": enrollment_total,
        },
        "audit_history": [
            {
                "id": log.id,
                "admin_id": log.admin_id,
                "admin_name": name,
                "action": log.action,
                "detail": log.detail,
                "created_at": log.created_at,
            }
            for log, name in audit_rows
        ],
    }


@router.patch("/courses/{course_id}/audit", response_model=AdminCourseOut)
def audit_course(
    course_id: int,
    req: CourseAuditRequest,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """课程审核(通过/驳回)"""
    course = _get_course_or_404(db, course_id)
    old = course.audit_status
    course.audit_status = req.audit_status
    db.commit()
    db.refresh(course)

    action = {"approved": "approve", "rejected": "reject"}.get(req.audit_status, "update")
    _audit(db, admin, request, action, "course", course.id,
           json.dumps({"before": old, "after": req.audit_status}, ensure_ascii=False))

    teacher_name = db.query(User.name).filter(User.id == course.teacher_id).scalar()
    return AdminCourseOut(
        id=course.id, teacher_id=course.teacher_id, teacher_name=teacher_name,
        name=course.name, code=course.code, syllabus=course.syllabus,
        semester=course.semester, audit_status=course.audit_status,
        created_at=course.created_at,
    )


@router.patch("/courses/batch-audit", response_model=BatchResult)
def batch_audit_courses(
    req: CourseBatchAuditRequest,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """批量课程审核:dry_run 时只预演,执行时写一条汇总审计"""
    ids = list(dict.fromkeys(req.course_ids))
    result = BatchResult(dry_run=req.dry_run)
    found = {course.id: course for course in db.query(Course).filter(Course.id.in_(ids)).all()}

    changed = []
    for course_id in ids:
        course = found.get(course_id)
        if course is None:
            result.failed.append(BatchItemError(id=course_id, reason="课程不存在"))
            continue
        if course.audit_status == req.audit_status:
            result.skipped.append(BatchItemError(id=course_id, reason="审核状态未变化"))
            continue
        changed.append(course)

    result.affected = [course.id for course in changed]
    if req.dry_run or not changed:
        return result

    before = {course.id: course.audit_status for course in changed}
    for course in changed:
        course.audit_status = req.audit_status
    action = {"approved": "approve", "rejected": "reject"}.get(req.audit_status, "update")
    _commit_with_audit(
        db, admin, request, f"batch_{action}", "course", None,
        json.dumps({"after": req.audit_status, "before": before}, ensure_ascii=False),
    )
    return result


# ==================== 素材管理 ====================

@router.get("/materials", response_model=MaterialPage)
def list_materials(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    course_id: Optional[int] = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """素材列表(可按课程筛选)"""
    query = db.query(CourseMaterial)
    if course_id:
        query = query.filter(CourseMaterial.course_id == course_id)
    total = query.count()
    items = query.order_by(CourseMaterial.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [MaterialOut.model_validate(m) for m in items]}


@router.delete("/materials/{material_id}")
def delete_material(
    material_id: int,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """删除素材(同步清理磁盘文件,并重建课程检索索引)"""
    import os
    material = db.query(CourseMaterial).filter(CourseMaterial.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="素材不存在")
    course_id = material.course_id

    try:
        if material.file_path and os.path.exists(material.file_path):
            os.remove(material.file_path)
    except Exception as e:
        logger.warning("素材文件删除失败: %s", e)

    detail = json.dumps({"title": material.title, "course_id": course_id},
                        ensure_ascii=False)
    db.delete(material)
    db.commit()
    try:
        from app.agent.tools.rag_search import rebuild_course_index

        rebuild_course_index(db, course_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("课程索引重建失败 course=%s: %s", course_id, e)
    _audit(db, admin, request, "delete", "material", material_id, detail)
    return {"id": material_id, "deleted": True}


# ==================== 风控日志 ====================

@router.get("/risk-logs/stats")
def risk_log_stats(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """风控命中统计:按类型/处置/日期分布"""
    total = db.query(func.count(RiskLog.id)).scalar() or 0
    by_type = dict(db.query(RiskLog.risk_type, func.count(RiskLog.id))
                   .group_by(RiskLog.risk_type).all())
    by_action = dict(db.query(RiskLog.action_taken, func.count(RiskLog.id))
                     .group_by(RiskLog.action_taken).all())
    daily_rows = (
        db.query(func.date(RiskLog.created_at), func.count(RiskLog.id))
        .group_by(func.date(RiskLog.created_at))
        .order_by(func.date(RiskLog.created_at).asc())
        .all()
    )
    daily = [{"date": str(d), "count": c} for d, c in daily_rows]
    return {"total": total, "by_type": by_type, "by_action": by_action, "daily": daily}


@router.get("/risk-logs", response_model=RiskLogPage)
def list_risk_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    risk_type: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """风控日志(分页 + 类型/用户筛选)"""
    query = db.query(RiskLog, User.name, User.email).outerjoin(User, RiskLog.user_id == User.id)
    if risk_type:
        query = query.filter(RiskLog.risk_type == risk_type)
    if user_id:
        query = query.filter(RiskLog.user_id == user_id)

    total = query.count()
    rows = query.order_by(RiskLog.id.desc()).offset((page - 1) * size).limit(size).all()
    items = [
        RiskLogOut(
            id=r.id, user_id=r.user_id, user_name=name, user_email=email,
            request_content=r.request_content, risk_type=r.risk_type,
            action_taken=r.action_taken, created_at=r.created_at,
        )
        for r, name, email in rows
    ]
    return {"total": total, "items": items}


@router.get("/risk-logs/{risk_log_id}/context")
def get_risk_log_context(
    risk_log_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """风险事件上下文:前后 30 分钟交互 + 管理员处置记录

    风险列表只有单条命中记录,这里补齐“发生了什么、谁处理过”。
    """
    risk = db.query(RiskLog).filter(RiskLog.id == risk_log_id).first()
    if not risk:
        raise HTTPException(status_code=404, detail="风险记录不存在")

    before, after = [], []
    if risk.created_at:
        window_start = risk.created_at - timedelta(minutes=30)
        window_end = risk.created_at + timedelta(minutes=30)
        before = list(reversed(
            db.query(InteractionLog)
            .filter(
                InteractionLog.user_id == risk.user_id,
                InteractionLog.created_at >= window_start,
                InteractionLog.created_at <= risk.created_at,
            )
            .order_by(InteractionLog.id.desc())
            .limit(10)
            .all()
        ))
        after = (
            db.query(InteractionLog)
            .filter(
                InteractionLog.user_id == risk.user_id,
                InteractionLog.created_at > risk.created_at,
                InteractionLog.created_at <= window_end,
            )
            .order_by(InteractionLog.id.asc())
            .limit(10)
            .all()
        )

    def _interaction(log: InteractionLog) -> dict:
        return {
            "id": log.id,
            "session_id": log.session_id,
            "role": log.role,
            "branch": log.branch,
            "content": log.content,
            "security_level": log.security_level,
            "created_at": log.created_at,
        }

    handling_rows = (
        db.query(OperationLog, User.name)
        .outerjoin(User, OperationLog.admin_id == User.id)
        .filter(
            OperationLog.target_type == "risk_log",
            OperationLog.target_id == risk.id,
        )
        .order_by(OperationLog.id.desc())
        .limit(10)
        .all()
    )
    user = db.query(User).filter(User.id == risk.user_id).first()
    return {
        "risk_log": {
            "id": risk.id,
            "user_id": risk.user_id,
            "request_content": risk.request_content,
            "risk_type": risk.risk_type,
            "action_taken": risk.action_taken,
            "created_at": risk.created_at,
        },
        "user": {
            "id": user.id, "name": user.name, "email": user.email,
            "role": user.role, "status": user.status,
        } if user else None,
        "interaction_context": {
            "before": [_interaction(log) for log in before],
            "after": [_interaction(log) for log in after],
        },
        "handling": [
            {
                "id": log.id,
                "admin_id": log.admin_id,
                "admin_name": name,
                "action": log.action,
                "detail": log.detail,
                "created_at": log.created_at,
            }
            for log, name in handling_rows
        ],
    }


# ==================== 交互日志 ====================

@router.get("/interaction-logs", response_model=InteractionLogPage)
def list_interaction_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = Query(None),
    branch: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """对话日志(分页 + 用户/分支/会话筛选)"""
    query = db.query(InteractionLog, User.name).outerjoin(User, InteractionLog.user_id == User.id)
    if user_id:
        query = query.filter(InteractionLog.user_id == user_id)
    if branch:
        query = query.filter(InteractionLog.branch == branch)
    if session_id:
        query = query.filter(InteractionLog.session_id == session_id)

    total = query.count()
    rows = query.order_by(InteractionLog.id.desc()).offset((page - 1) * size).limit(size).all()
    items = [
        InteractionLogOut(
            id=log.id, user_id=log.user_id, user_name=name,
            session_id=log.session_id, role=log.role, branch=log.branch,
            content=log.content, created_at=log.created_at,
        )
        for log, name in rows
    ]
    return {"total": total, "items": items}


# ==================== 操作日志 ====================

@router.get("/operation-logs", response_model=OperationLogPage)
def list_operation_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    admin_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """操作审计日志(分页 + 操作人/动作/对象筛选)"""
    query = db.query(OperationLog, User.name).outerjoin(User, OperationLog.admin_id == User.id)
    if admin_id:
        query = query.filter(OperationLog.admin_id == admin_id)
    if action:
        query = query.filter(OperationLog.action == action)
    if target_type:
        query = query.filter(OperationLog.target_type == target_type)

    total = query.count()
    rows = query.order_by(OperationLog.id.desc()).offset((page - 1) * size).limit(size).all()
    items = [
        OperationLogOut(
            id=log.id, admin_id=log.admin_id, admin_name=name,
            action=log.action, target_type=log.target_type, target_id=log.target_id,
            detail=log.detail, ip=log.ip, created_at=log.created_at,
        )
        for log, name in rows
    ]
    return {"total": total, "items": items}


# ==================== 系统配置 ====================

@router.get("/config", response_model=ConfigListOut)
def get_config(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """读取全部系统配置"""
    items = db.query(SystemConfig).order_by(SystemConfig.id.asc()).all()
    return {"items": _config_items(db, items)}


@router.put("/config", response_model=ConfigListOut)
def update_config(
    req: ConfigUpdate,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """更新系统配置(风控开关/反思轮次/RAG top_k 等),缺失项自动创建"""
    changes = {}
    for item in req.items:
        cfg = db.query(SystemConfig).filter(SystemConfig.config_key == item.config_key).first()
        if not cfg:
            cfg = SystemConfig(config_key=item.config_key, description="管理端创建")
            db.add(cfg)
        changes[item.config_key] = {"before": cfg.config_value, "after": item.config_value}
        cfg.config_value = item.config_value
        cfg.updated_by = admin.id
    db.commit()

    _audit(db, admin, request, "config", "config", None,
           json.dumps(changes, ensure_ascii=False))

    items = db.query(SystemConfig).order_by(SystemConfig.id.asc()).all()
    return {"items": _config_items(db, items)}


# ==================== 站点内容 ====================

@router.get("/site-content")
def get_site_content(
    response: Response,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """读取首页与联系页内容(未配置时返回 null,前端回落到内置文案)"""
    response.headers["Cache-Control"] = "no-store"
    return load_site_content(db)


@router.put("/site-content")
def update_site_content(
    req: SiteContentUpdate,
    request: Request,
    response: Response,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """保存首页与联系页内容;整体覆盖对应配置项"""
    response.headers["Cache-Control"] = "no-store"
    changes = {}
    for key, value in ((HOME_KEY, req.home), (CONTACT_KEY, req.contact)):
        if value is None:
            continue
        raw = json.dumps(value, ensure_ascii=False)
        if len(raw) > 200_000:
            raise HTTPException(status_code=400, detail="内容过大,请精简后再保存")
        cfg = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
        if not cfg:
            cfg = SystemConfig(config_key=key, description="站点内容")
            db.add(cfg)
        changes[key] = {"bytes": len(raw)}
        cfg.config_value = raw
        cfg.updated_by = admin.id
    db.commit()

    _audit(db, admin, request, "config", "site_content", None,
           json.dumps(changes, ensure_ascii=False))
    return load_site_content(db)


SITE_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
SITE_IMAGE_MAX_BYTES = 5 * 1024 * 1024


@router.post("/site-image")
async def upload_site_image(
    request: Request,
    file: UploadFile = File(...),
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """上传首页展示图,保存到 static/site/home 并返回可访问地址"""
    content_type = (file.content_type or "").lower()
    ext = SITE_IMAGE_TYPES.get(content_type)
    if not ext:
        raise HTTPException(status_code=400, detail="仅支持 PNG、JPG、WEBP 图片")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="图片内容为空")
    if len(data) > SITE_IMAGE_MAX_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 5MB")

    folder = settings.static_path / "site" / "home"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    (folder / filename).write_bytes(data)

    url = f"/static/site/home/{filename}"
    _audit(db, admin, request, "upload", "site_image", None,
           json.dumps({"url": url, "bytes": len(data)}, ensure_ascii=False))
    return {"url": url, "bytes": len(data)}


# ==================== 统计看板 ====================

@router.get("/stats/overview")
def stats_overview(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """总览:用户/课程/对话/风控核心指标"""
    role_counts = dict(db.query(User.role, func.count(User.id)).group_by(User.role).all())
    total_users = sum(role_counts.values())
    active_users = db.query(func.count(User.id)).filter(User.status == "active").scalar() or 0
    total_courses = db.query(func.count(Course.id)).scalar() or 0
    course_status = dict(
        db.query(Course.audit_status, func.count(Course.id))
        .group_by(Course.audit_status)
        .all()
    )
    pending_courses = course_status.get("pending", 0)
    status_counts = dict(
        db.query(User.status, func.count(User.id)).group_by(User.status).all()
    )
    total_messages = db.query(func.count(InteractionLog.id)).scalar() or 0
    total_sessions = db.query(func.count(func.distinct(InteractionLog.session_id))).scalar() or 0
    risk_hits = db.query(func.count(RiskLog.id)).scalar() or 0

    return {
        "users": {
            "total": total_users,
            "teacher": role_counts.get("teacher", 0),
            "student": role_counts.get("student", 0),
            "admin": role_counts.get("admin", 0),
            "active": active_users,
            "by_status": status_counts,
        },
        "courses": {
            "total": total_courses,
            "pending": pending_courses,
            "by_status": course_status,
        },
        "interactions": {"messages": total_messages, "sessions": total_sessions},
        "risk": {"total": risk_hits},
    }


@router.get("/stats/users")
def stats_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户增长 / 角色分布"""
    role_counts = dict(db.query(User.role, func.count(User.id)).group_by(User.role).all())
    growth_rows = (
        db.query(func.date(User.created_at), func.count(User.id))
        .group_by(func.date(User.created_at))
        .order_by(func.date(User.created_at).asc())
        .all()
    )
    status_counts = dict(
        db.query(User.status, func.count(User.id)).group_by(User.status).all()
    )
    return {
        "total": sum(role_counts.values()),
        "roles": role_counts,
        "status": status_counts,
        "growth": [{"date": str(d), "count": c} for d, c in growth_rows],
    }


@router.get("/stats/courses")
def stats_courses(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """课程覆盖与学情分布"""
    courses = db.query(Course).all()
    course_items = []
    for c in courses:
        profiles = db.query(StudentProfile).filter(StudentProfile.course_id == c.id).all()
        avg = (
            sum(float(p.overall_progress or 0) for p in profiles) / len(profiles)
            if profiles else 0
        )
        course_items.append({
            "course_id": c.id, "name": c.name, "code": c.code,
            "audit_status": c.audit_status,
            "student_count": len(profiles), "avg_progress": round(avg, 1),
        })

    # 掌握度分布(按学生平均掌握度分档)
    rows = (
        db.query(StudentProfile.id, func.avg(MasteryRecord.mastery_level))
        .outerjoin(MasteryRecord, MasteryRecord.profile_id == StudentProfile.id)
        .group_by(StudentProfile.id)
        .all()
    )
    buckets = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
    for _, avg_m in rows:
        value = float(avg_m or 0)
        if value < 20:
            buckets["0-20"] += 1
        elif value < 40:
            buckets["20-40"] += 1
        elif value < 60:
            buckets["40-60"] += 1
        elif value < 80:
            buckets["60-80"] += 1
        else:
            buckets["80-100"] += 1

    return {
        "total_courses": len(courses),
        "courses": course_items,
        "mastery_distribution": buckets,
    }


@router.get("/stats/agent")
def stats_agent(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Agent 运行统计:对话量 / 分支分布 / 风控命中 / 日趋势"""
    total_messages = db.query(func.count(InteractionLog.id)).scalar() or 0
    total_sessions = db.query(func.count(func.distinct(InteractionLog.session_id))).scalar() or 0
    by_branch = dict(db.query(InteractionLog.branch, func.count(InteractionLog.id))
                     .group_by(InteractionLog.branch).all())
    risk_hits = db.query(func.count(RiskLog.id)).scalar() or 0
    daily_rows = (
        db.query(func.date(InteractionLog.created_at), func.count(InteractionLog.id))
        .group_by(func.date(InteractionLog.created_at))
        .order_by(func.date(InteractionLog.created_at).asc())
        .all()
    )
    return {
        "total_messages": total_messages,
        "total_sessions": total_sessions,
        "by_branch": by_branch,
        "risk_hits": risk_hits,
        "daily": [{"date": str(d), "count": c} for d, c in daily_rows],
    }


# ==================== 前台镜像:教师端 ====================

@router.get("/teacher/courses", response_model=List[CourseOut])
def admin_teacher_courses(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """全部课程(管理员视角)"""
    return db.query(Course).order_by(Course.id.desc()).all()


@router.post("/teacher/courses", response_model=CourseOut)
def admin_create_course(
    req: AdminCourseCreate,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """代建课程"""
    teacher_id = req.teacher_id or admin.id
    target = db.query(User).filter(User.id == teacher_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="指定教师不存在")

    data = req.model_dump(exclude={"teacher_id"})
    # 管理员代建视为平台已审核,直接通过
    course = Course(teacher_id=teacher_id, audit_status="approved", **data)
    db.add(course)
    db.commit()
    db.refresh(course)
    _audit(db, admin, request, "create", "course", course.id,
           json.dumps({"name": course.name, "teacher_id": teacher_id}, ensure_ascii=False))
    return course


@router.get("/teacher/courses/{course_id}", response_model=CourseOut)
def admin_get_course(
    course_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _get_course_or_404(db, course_id)


@router.put("/teacher/courses/{course_id}", response_model=CourseOut)
def admin_update_course(
    course_id: int,
    req: CourseCreate,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(db, course_id)
    before = {"name": course.name, "code": course.code,
              "syllabus": course.syllabus, "semester": course.semester}
    course.name = req.name
    course.code = req.code
    course.syllabus = req.syllabus
    course.semester = req.semester
    db.commit()
    db.refresh(course)
    _audit(db, admin, request, "update", "course", course.id, json.dumps(
        {"before": before, "after": req.model_dump()}, ensure_ascii=False))
    return course


@router.delete("/teacher/courses/{course_id}")
def admin_delete_course(
    course_id: int,
    request: Request,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """软删除课程，保留全部关联数据"""
    from datetime import datetime

    course = _get_course_or_404(db, course_id)
    name = course.name
    course.deleted_at = datetime.utcnow()
    db.commit()
    _audit(db, admin, request, "delete", "course", course_id,
           json.dumps({"name": name}, ensure_ascii=False))
    return {"id": course_id, "deleted": True}


@router.post("/teacher/materials", response_model=MaterialOut)
def admin_upload_material(
    request: Request,
    course_id: int = Form(...),
    type: str = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    _get_course_or_404(db, course_id)
    material = save_material(db, course_id, type, title, file)
    _audit(db, admin, request, "create", "material", material.id,
           json.dumps({"title": title, "course_id": course_id}, ensure_ascii=False))
    return material


@router.post("/teacher/lesson-plan")
def admin_lesson_plan(
    req: LessonPlanRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """教案生成(SSE,管理员代教师触发)"""
    course = _get_course_or_404(db, req.course_id)
    msg = f"请为课程《{course.name}》生成教案框架。"
    if req.chapter:
        msg += f"指定章节:{req.chapter}。"
    if req.hours:
        msg += f"课时数:{req.hours}。"
    msg += "要求给出教学目标、重难点、教学环节与时间分配,供教师审核修改。"

    chat_req = ChatRequest(session_id=None, course_id=req.course_id, message=msg)
    return StreamingResponse(
        stream_agent_response(chat_req, admin, db, force_branch="teacher", request=request),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/teacher/class-report/{course_id}", response_model=ClassReportOut)
def admin_class_report(
    course_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(db, course_id)
    return build_class_report(db, course)


@router.post("/teacher/export")
def admin_export(
    req: ExportRequest,
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    _get_course_or_404(db, req.course_id)
    payload = {**req.data, "course_id": req.course_id, "teacher_name": admin.name}
    result = doc_generator(doc_type=req.type, data=payload)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ==================== 前台镜像:学生端 ====================

@router.get("/student/courses")
def admin_student_courses(
    student_id: Optional[int] = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """学生课程列表(可按学生代查;不指定则返回全部课程)"""
    if student_id:
        rows = (
            db.query(Course, StudentProfile)
            .join(StudentProfile, StudentProfile.course_id == Course.id)
            .filter(StudentProfile.user_id == student_id)
            .order_by(Course.id.desc())
            .all()
        )
        return [
            {
                "id": course.id, "teacher_id": course.teacher_id,
                "name": course.name, "code": course.code,
                "syllabus": course.syllabus, "semester": course.semester,
                "audit_status": course.audit_status,
                "overall_progress": float(profile.overall_progress or 0),
            }
            for course, profile in rows
        ]

    return [
        {
            "id": c.id, "teacher_id": c.teacher_id, "name": c.name, "code": c.code,
            "syllabus": c.syllabus, "semester": c.semester,
            "audit_status": c.audit_status,
        }
        for c in db.query(Course).order_by(Course.id.desc()).all()
    ]


@router.get("/student/progress/{course_id}", response_model=ProgressOut)
def admin_student_progress(
    course_id: int,
    student_id: Optional[int] = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """学生进度(指定 student_id 精确到人,否则全班聚合)"""
    if student_id:
        profile = _ensure_profile(db, student_id, course_id, require_enrolled=False)
        return _build_progress(db, profile, course_id)
    return _aggregate_progress(db, course_id)


@router.get("/student/wrong-questions", response_model=List[WrongQuestionOut])
def admin_student_wrong_questions(
    course_id: int = Query(...),
    student_id: Optional[int] = Query(None),
    limit: int = Query(100, le=500),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """错题集(指定学生或个人;不指定则课程内全部)"""
    if student_id:
        profile = _ensure_profile(db, student_id, course_id, require_enrolled=False)
        return (
            db.query(WrongQuestion)
            .filter(WrongQuestion.profile_id == profile.id)
            .order_by(WrongQuestion.created_at.desc())
            .limit(limit)
            .all()
        )
    return (
        db.query(WrongQuestion)
        .join(StudentProfile, WrongQuestion.profile_id == StudentProfile.id)
        .filter(StudentProfile.course_id == course_id)
        .order_by(WrongQuestion.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/student/review-plans", response_model=List[ReviewPlanOut])
def admin_student_review_plans(
    course_id: int = Query(...),
    student_id: Optional[int] = Query(None),
    status: str = Query("pending"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """复习计划(可指定学生)"""
    query = (
        db.query(ReviewPlan)
        .join(WrongQuestion, ReviewPlan.wrong_question_id == WrongQuestion.id)
        .join(StudentProfile, WrongQuestion.profile_id == StudentProfile.id)
        .filter(StudentProfile.course_id == course_id)
    )
    if student_id:
        query = query.filter(StudentProfile.user_id == student_id)
    if status != "all":
        query = query.filter(ReviewPlan.status == status)
    return query.order_by(ReviewPlan.next_review_at.asc()).limit(200).all()


@router.post("/student/interview/start")
def admin_interview_start(
    req: InterviewStartRequest,
    request: Request,
    student_id: int = Query(..., description="被代查学生 ID"),
    admin: User = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """代学生开启模拟面试(SSE)"""
    target = db.query(User).filter(User.id == student_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="学生不存在")
    if target.role != "student":
        raise HTTPException(status_code=400, detail="目标用户不是学生")

    _ensure_profile(db, target.id, req.course_id, require_enrolled=False)
    msg = f"请开始模拟面试,课程 ID 为 {req.course_id}。"
    if req.focus_kp_ids:
        names = [
            kp.name for kp in db.query(KnowledgePoint)
            .filter(KnowledgePoint.id.in_(req.focus_kp_ids))
            .all()
        ]
        if names:
            msg += "请重点考察以下知识点:" + "、".join(names) + "。"
    chat_req = ChatRequest(session_id=None, course_id=req.course_id, message=msg)
    return StreamingResponse(
        stream_agent_response(chat_req, target, db, force_branch="interview", request=request),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/student/interview/records", response_model=List[InterviewRecordOut])
def admin_interview_records(
    course_id: int = Query(...),
    student_id: int = Query(..., description="被代查学生 ID"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """面试记录(指定学生)"""
    profile = _ensure_profile(db, student_id, course_id, require_enrolled=False)
    return (
        db.query(InterviewRecord)
        .filter(InterviewRecord.profile_id == profile.id)
        .order_by(InterviewRecord.round.asc())
        .all()
    )


@router.post("/storage/cleanup")
def trigger_storage_cleanup(
    admin: User = Depends(require_admin_write),
):
    """手动触发上传文件清理(每日 03:30 也会自动执行)"""
    result = cleanup_uploads_task()
    logger.info("手动清理上传文件: admin=%s result=%s", admin.id, result)
    return result
