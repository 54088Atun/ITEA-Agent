"""管理端可执行动作:白名单、权限校验与操作审计

管理助手与页面共用同一套权限口径:
- observer 只能查看,不能执行任何写操作;
- 涉及管理员账号的动作仅超级管理员可执行;
- 每个动作执行后都写入 operation_logs,便于事后追溯。
"""
import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import admin_level_of
from app.core.security import hash_password
from app.models.course import Course
from app.models.log import SystemConfig
from app.models.user import User
from app.services.audit_service import write_operation_log
from app.services.storage_cleanup import cleanup_uploads_task

logger = logging.getLogger(__name__)

MAX_BATCH = 200


@dataclass(frozen=True)
class AdminAction:
    key: str
    label: str
    description: str
    params: str
    requires_write: bool
    handler: Callable[[Session, User, dict], dict]


def _ok(message: str, **data) -> dict:
    return {"ok": True, "message": message, "data": data}


def _fail(message: str) -> dict:
    return {"ok": False, "message": message, "data": {}}


def _int_list(value: Any) -> list[int]:
    if value is None:
        return []
    raw = value if isinstance(value, (list, tuple)) else [value]
    result: list[int] = []
    for item in raw:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _find_users(db: Session, args: dict) -> list[User]:
    ids = _int_list(args.get("user_ids") or args.get("user_id"))
    email = str(args.get("email") or "").strip()
    query = db.query(User)
    if ids:
        return query.filter(User.id.in_(ids)).all()
    if email:
        return query.filter(User.email == email).all()
    return []


def _is_last_active_super(db: Session, target: User) -> bool:
    """停用/降级前检查:系统必须保留一个启用状态的超级管理员"""
    if target.role != "admin" or admin_level_of(target) != "super":
        return False
    others = (
        db.query(User)
        .filter(User.role == "admin", User.id != target.id)
        .with_for_update()
        .all()
    )
    return not any(
        user.status == "active" and admin_level_of(user) == "super"
        for user in others
    )


# ---------- 动作实现 ----------

def _audit_courses(db: Session, admin: User, args: dict) -> dict:
    status = str(args.get("audit_status") or "approved").strip().lower()
    if status not in ("pending", "approved", "rejected"):
        return _fail("审核状态只能是 approved / rejected / pending")

    ids = _int_list(args.get("course_ids") or args.get("course_id"))
    query = db.query(Course)
    if ids:
        query = query.filter(Course.id.in_(ids))
    else:
        query = query.filter(Course.audit_status == "pending")

    courses = query.order_by(Course.id.asc()).limit(MAX_BATCH).all()
    if not courses:
        return _ok("没有符合条件的课程,未做任何修改")

    before = {course.id: course.audit_status for course in courses}
    for course in courses:
        course.audit_status = status
    db.commit()

    action = {"approved": "approve", "rejected": "reject"}.get(status, "update")
    write_operation_log(
        db, admin, action, "course", None,
        json.dumps(
            {
                "source": "assistant",
                "course_ids": [course.id for course in courses],
                "before": before,
                "after": status,
            },
            ensure_ascii=False,
        ),
    )
    label = {"approved": "通过", "rejected": "驳回", "pending": "退回待审核"}[status]
    return _ok(
        f"已将 {len(courses)} 门课程{label}",
        course_ids=[course.id for course in courses],
        courses=[{"id": course.id, "name": course.name} for course in courses],
    )


def _set_user_status(db: Session, admin: User, args: dict) -> dict:
    status = str(args.get("status") or "").strip().lower()
    if status not in ("active", "disabled"):
        return _fail("账号状态只能是 active(启用)或 disabled(禁用)")

    targets = _find_users(db, args)
    if not targets:
        return _fail("没有找到目标账号,请提供准确的 user_id 或邮箱")

    changed, skipped = [], []
    for target in targets:
        if target.id == admin.id and status == "disabled":
            skipped.append(f"{target.name}: 不能禁用当前登录账号")
            continue
        if target.role == "admin" and admin_level_of(admin) != "super":
            skipped.append(f"{target.name}: 仅超级管理员可管理管理员账号")
            continue
        if status == "disabled" and _is_last_active_super(db, target):
            skipped.append(f"{target.name}: 系统至少保留一个启用状态的超级管理员")
            continue

        target.status = status
        if status == "disabled":
            target.token_version = int(target.token_version or 0) + 1
        changed.append(target)

    if not changed:
        return _fail("; ".join(skipped) or "没有可修改的账号")

    db.commit()
    write_operation_log(
        db, admin, "disable" if status == "disabled" else "enable",
        "user", None,
        json.dumps(
            {
                "source": "assistant",
                "user_ids": [user.id for user in changed],
                "status": status,
                "skipped": skipped,
            },
            ensure_ascii=False,
        ),
    )
    label = "禁用" if status == "disabled" else "启用"
    message = f"已{label} {len(changed)} 个账号"
    if skipped:
        message += f"; {len(skipped)} 个未处理"
    return _ok(
        message,
        user_ids=[user.id for user in changed],
        skipped=skipped,
    )


def _reset_password(db: Session, admin: User, args: dict) -> dict:
    password = str(args.get("new_password") or "")
    if len(password) < 6:
        return _fail("新密码至少 6 位")

    targets = _find_users(db, args)
    if not targets:
        return _fail("没有找到目标账号,请提供准确的 user_id 或邮箱")
    if len(targets) > 1:
        return _fail("匹配到多个账号,请改用 user_id 指定唯一的账号")

    target = targets[0]
    if target.role == "admin" and admin_level_of(admin) != "super":
        return _fail("仅超级管理员可重置管理员账号密码")

    target.password_hash = hash_password(password)
    target.token_version = int(target.token_version or 0) + 1
    db.commit()
    write_operation_log(
        db, admin, "update", "user", target.id,
        json.dumps({"source": "assistant", "field": "password_reset"}, ensure_ascii=False),
    )
    return _ok(f"已重置 {target.name} 的密码,该账号旧登录状态已失效")


def _set_config(db: Session, admin: User, args: dict) -> dict:
    key = str(args.get("config_key") or "").strip()
    if not key:
        return _fail("缺少配置键 config_key")
    if len(key) > 100:
        return _fail("配置键过长")
    value = args.get("config_value")
    if value is None:
        return _fail("缺少配置值 config_value")
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    if len(value) > 20_000:
        return _fail("配置值过长")

    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    before = cfg.config_value if cfg else None
    if not cfg:
        cfg = SystemConfig(config_key=key, description="管理助手创建")
        db.add(cfg)
    cfg.config_value = value
    cfg.updated_by = admin.id
    db.commit()

    write_operation_log(
        db, admin, "config", "config", None,
        json.dumps(
            {"source": "assistant", "key": key, "before": before, "after": value},
            ensure_ascii=False,
        ),
    )
    return _ok(f"配置项 {key} 已更新", config_key=key, config_value=value)


def _cleanup_storage(db: Session, admin: User, args: dict) -> dict:
    result = cleanup_uploads_task()
    write_operation_log(
        db, admin, "delete", "storage", None,
        json.dumps({"source": "assistant", **result}, ensure_ascii=False),
    )
    if result.get("error"):
        return _fail(f"清理失败: {result['error']}")
    return _ok(
        f"已清理 {result.get('deleted', 0)} 个过期文件,"
        f"释放 {round((result.get('freed_bytes') or 0) / 1024, 1)} KB",
        **result,
    )


def _stats_report(db: Session, admin: User, args: dict) -> dict:
    from app.models.log import InteractionLog, RiskLog
    from sqlalchemy import func

    role_counts = dict(db.query(User.role, func.count(User.id)).group_by(User.role).all())
    course_status = dict(
        db.query(Course.audit_status, func.count(Course.id))
        .group_by(Course.audit_status)
        .all()
    )
    risk_total = db.query(func.count(RiskLog.id)).scalar() or 0
    messages = db.query(func.count(InteractionLog.id)).scalar() or 0
    return _ok(
        "平台数据已汇总",
        users_by_role=role_counts,
        courses_by_status=course_status,
        risk_logs=risk_total,
        interaction_logs=messages,
    )


ADMIN_ACTIONS: dict[str, AdminAction] = {
    "course.audit": AdminAction(
        key="course.audit",
        label="审核课程",
        description="按课程 ID 审核,或不传 ID 时批量处理全部待审核课程",
        params='{"audit_status": "approved|rejected|pending", "course_ids": [1,2]}',
        requires_write=True,
        handler=_audit_courses,
    ),
    "user.set_status": AdminAction(
        key="user.set_status",
        label="启用/禁用账号",
        description="按 user_id 或邮箱启用、禁用账号",
        params='{"user_ids": [1], "email": "a@b.com", "status": "active|disabled"}',
        requires_write=True,
        handler=_set_user_status,
    ),
    "user.reset_password": AdminAction(
        key="user.reset_password",
        label="重置密码",
        description="按 user_id 或邮箱重置密码,旧登录状态立即失效",
        params='{"user_id": 1, "email": "a@b.com", "new_password": "至少6位"}',
        requires_write=True,
        handler=_reset_password,
    ),
    "config.set": AdminAction(
        key="config.set",
        label="修改系统配置",
        description="新增或修改一个系统配置项",
        params='{"config_key": "risk.enabled", "config_value": "true"}',
        requires_write=True,
        handler=_set_config,
    ),
    "storage.cleanup": AdminAction(
        key="storage.cleanup",
        label="清理过期上传文件",
        description="清理超过保留期的识图图片、录音与草稿文件",
        params="{}",
        requires_write=True,
        handler=_cleanup_storage,
    ),
    "stats.report": AdminAction(
        key="stats.report",
        label="汇总平台数据",
        description="汇总用户角色、课程审核状态、风控与对话总量",
        params="{}",
        requires_write=False,
        handler=_stats_report,
    ),
}


def action_catalog_text() -> str:
    """给模型看的动作清单(不含实现细节)"""
    lines = []
    for action in ADMIN_ACTIONS.values():
        flag = "写操作" if action.requires_write else "只读"
        lines.append(
            f"- {action.key}（{action.label}，{flag}）：{action.description}；参数 {action.params}"
        )
    return "\n".join(lines)


def action_catalog() -> list[dict]:
    return [
        {
            "key": action.key,
            "label": action.label,
            "description": action.description,
            "params": action.params,
            "requires_write": action.requires_write,
        }
        for action in ADMIN_ACTIONS.values()
    ]


# ---------- 预览与确认执行 ----------

PREVIEW_TTL_SECONDS = 300
TOKEN_SEPARATOR = "."
_IDEMPOTENCY: dict[str, dict] = {}
_IDEMPOTENCY_TTL_SECONDS = 3600


def _canonical(params: dict) -> str:
    return json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _make_confirmation_token(admin: User, action_key: str, params: dict) -> str:
    payload = {
        "admin_id": admin.id,
        "action": action_key,
        "params": params,
        "exp": int(time.time()) + PREVIEW_TTL_SECONDS,
    }
    raw = _canonical(payload).encode("utf-8")
    signature = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), raw, hashlib.sha256,
    ).hexdigest()
    return base64.urlsafe_b64encode(raw).decode("ascii") + TOKEN_SEPARATOR + signature


def _verify_confirmation_token(
    token: str, admin: User, action_key: str, params: dict,
) -> bool:
    try:
        body, signature = token.split(TOKEN_SEPARATOR, 1)
        raw = base64.urlsafe_b64decode(body.encode("ascii"))
        expected = hmac.new(
            settings.SECRET_KEY.encode("utf-8"), raw, hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return False
        payload = json.loads(raw.decode("utf-8"))
        return (
            int(payload.get("exp", 0)) >= int(time.time())
            and int(payload.get("admin_id", 0)) == admin.id
            and payload.get("action") == action_key
            and payload.get("params") == params
        )
    except Exception:  # noqa: BLE001
        return False


def _preview_course_audit(db: Session, admin: User, args: dict) -> dict:
    status = str(args.get("audit_status") or "approved").strip().lower()
    if status not in ("pending", "approved", "rejected"):
        return _fail("审核状态只能是 approved / rejected / pending")

    ids = _int_list(args.get("course_ids") or args.get("course_id"))
    query = db.query(Course)
    if ids:
        query = query.filter(Course.id.in_(ids))
    else:
        query = query.filter(Course.audit_status == "pending")

    total = query.count()
    courses = query.order_by(Course.id.asc()).limit(MAX_BATCH).all()
    items = [
        {
            "id": course.id,
            "name": course.name,
            "code": course.code,
            "audit_status": course.audit_status,
            "teacher_id": course.teacher_id,
            "will_change": course.audit_status != status,
        }
        for course in courses
    ]
    label = {"approved": "通过", "rejected": "驳回", "pending": "退回待审核"}[status]
    return _ok(
        f"将把 {total} 门课程{label}",
        target_type="course",
        action_label=ADMIN_ACTIONS["course.audit"].label,
        count=total,
        shown=len(items),
        truncated=total > MAX_BATCH,
        risk_level="high" if total > 50 else "medium" if total > 10 else "low",
        items=items,
    )


def _preview_user_status(db: Session, admin: User, args: dict) -> dict:
    status = str(args.get("status") or "").strip().lower()
    if status not in ("active", "disabled"):
        return _fail("账号状态只能是 active(启用)或 disabled(禁用)")

    targets = _find_users(db, args)
    if not targets:
        return _fail("没有找到目标账号,请提供准确的 user_id、user_ids 或邮箱")

    items = []
    skipped = []
    for target in targets:
        reason = ""
        if target.id == admin.id and status == "disabled":
            reason = "不能禁用当前登录账号"
        elif target.role == "admin" and admin_level_of(admin) != "super":
            reason = "仅超级管理员可管理管理员账号"
        elif status == "disabled" and _is_last_active_super(db, target):
            reason = "系统至少保留一个启用状态的超级管理员"

        item = {
            "id": target.id,
            "name": target.name,
            "email": target.email,
            "role": target.role,
            "status": target.status,
            "will_change": not reason and target.status != status,
        }
        if reason:
            item["skip_reason"] = reason
            skipped.append(f"{target.name}: {reason}")
        items.append(item)

    change_count = sum(1 for item in items if item["will_change"])
    label = "禁用" if status == "disabled" else "启用"
    message = f"将{label} {change_count} 个账号"
    if skipped:
        message += f"; {len(skipped)} 个不符合条件"
    return _ok(
        message,
        target_type="user",
        action_label=ADMIN_ACTIONS["user.set_status"].label,
        count=change_count,
        shown=len(items),
        truncated=False,
        risk_level="high" if status == "disabled" else "medium",
        items=items,
        skipped=skipped,
    )


def _preview_reset_password(db: Session, admin: User, args: dict) -> dict:
    targets = _find_users(db, args)
    if not targets:
        return _fail("没有找到目标账号,请提供准确的 user_id 或邮箱")
    if len(targets) > 1:
        return _fail("匹配到多个账号,请改用 user_id 指定唯一的账号")
    target = targets[0]
    if target.role == "admin" and admin_level_of(admin) != "super":
        return _fail("仅超级管理员可重置管理员账号密码")
    return _ok(
        f"将重置 {target.name} 的密码,该账号旧登录状态会立即失效",
        target_type="user",
        action_label=ADMIN_ACTIONS["user.reset_password"].label,
        count=1,
        shown=1,
        truncated=False,
        risk_level="high",
        items=[{"id": target.id, "name": target.name, "email": target.email}],
    )


def _preview_set_config(db: Session, admin: User, args: dict) -> dict:
    key = str(args.get("config_key") or "").strip()
    if not key:
        return _fail("缺少配置键 config_key")
    value = args.get("config_value")
    if value is None:
        return _fail("缺少配置值 config_value")
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)

    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    return _ok(
        f"将修改配置项 {key}",
        target_type="config",
        action_label=ADMIN_ACTIONS["config.set"].label,
        count=1,
        shown=1,
        truncated=False,
        risk_level="high" if key.startswith(("auth.", "risk.", "security.")) else "medium",
        items=[{
            "config_key": key,
            "before": cfg.config_value if cfg else None,
            "after": value,
        }],
    )


def _preview_storage_cleanup(db: Session, admin: User, args: dict) -> dict:
    return _ok(
        "将扫描并删除超过保留期的上传文件",
        target_type="storage",
        action_label=ADMIN_ACTIONS["storage.cleanup"].label,
        count=None,
        shown=0,
        truncated=False,
        risk_level="medium",
        items=[],
    )


def _preview_stats_report(db: Session, admin: User, args: dict) -> dict:
    return _ok(
        "只读汇总平台数据,不会修改任何内容",
        target_type="stats",
        action_label=ADMIN_ACTIONS["stats.report"].label,
        count=None,
        shown=0,
        truncated=False,
        risk_level="low",
        items=[],
    )


_PREVIEW_HANDLERS: dict[str, Callable[[Session, User, dict], dict]] = {
    "course.audit": _preview_course_audit,
    "user.set_status": _preview_user_status,
    "user.reset_password": _preview_reset_password,
    "config.set": _preview_set_config,
    "storage.cleanup": _preview_storage_cleanup,
    "stats.report": _preview_stats_report,
}


def preview_action(
    db: Session,
    admin: User,
    action_key: str,
    args: Optional[dict] = None,
) -> dict:
    """预览动作影响范围,返回确认令牌;不写库"""
    action = ADMIN_ACTIONS.get(action_key)
    if action is None:
        return _fail(f"未登记的动作: {action_key}")
    if admin.role != "admin":
        return _fail("仅管理员可预览管理动作")
    if action.requires_write and admin_level_of(admin) == "observer":
        # 预览也不给观察者:避免展示一张永远点不动的确认卡片
        return _fail("观察者账号只能查看,不能执行写操作")

    params = args or {}
    handler = _PREVIEW_HANDLERS.get(action_key)
    result = handler(db, admin, params) if handler else _ok(
        "该动作暂不支持预览,可以直接执行",
        target_type="unknown",
        action_label=action.label,
        count=None,
        shown=0,
        truncated=False,
        risk_level="high" if action.requires_write else "low",
        items=[],
    )
    if not result.get("ok"):
        return result

    data = result.setdefault("data", {})
    data["requires_write"] = action.requires_write
    data["confirmation_token"] = _make_confirmation_token(admin, action_key, params)
    data["expires_in"] = PREVIEW_TTL_SECONDS
    return result


def _cleanup_idempotency() -> None:
    now = time.time()
    expired = [
        key for key, item in _IDEMPOTENCY.items()
        if now - item.get("at", 0) > _IDEMPOTENCY_TTL_SECONDS
    ]
    for key in expired:
        _IDEMPOTENCY.pop(key, None)


def execute_previewed_action(
    db: Session,
    admin: User,
    action_key: str,
    args: Optional[dict],
    confirmation_token: str,
    idempotency_key: str,
) -> dict:
    """校验确认令牌后执行动作;同一幂等键只执行一次"""
    params = args or {}
    if not idempotency_key or len(idempotency_key) > 100:
        return _fail("缺少有效的 idempotency_key")
    if not _verify_confirmation_token(confirmation_token, admin, action_key, params):
        return _fail("确认令牌无效或已过期,请重新预览")

    _cleanup_idempotency()
    cached = _IDEMPOTENCY.get(idempotency_key)
    if cached:
        if cached["admin_id"] != admin.id or cached["action"] != action_key:
            return _fail("idempotency_key 已被其他操作占用")
        return {**cached["result"], "idempotent": True}

    result = execute_action(db, admin, action_key, params)
    if result.get("ok"):
        _IDEMPOTENCY[idempotency_key] = {
            "admin_id": admin.id,
            "action": action_key,
            "result": result,
            "at": time.time(),
        }
    return result


def execute_action(
    db: Session,
    admin: User,
    action_key: str,
    args: Optional[dict] = None,
) -> dict:
    """执行一个已登记的动作;未登记、越权或异常都返回结构化失败"""
    action = ADMIN_ACTIONS.get(action_key)
    if action is None:
        return _fail(f"未登记的动作: {action_key}")
    if admin.role != "admin":
        return _fail("仅管理员可执行管理动作")
    if action.requires_write and admin_level_of(admin) == "observer":
        return _fail("观察者账号只能查看,不能执行写操作")

    try:
        return action.handler(db, admin, args or {})
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("管理动作执行失败(%s): %s", action_key, exc)
        return _fail(f"执行失败: {exc}")
