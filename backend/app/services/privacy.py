"""隐私设置:姓名/邮箱/学习记录的可见范围(PC-07)

可见范围口径(由窄到宽):
- private     仅自己
- teachers    教师可见(学生本人与教师/管理员)
- classmates  同学可见(同时教师可见)

学习记录设为 private 时,教师报表不再展示该学生的明细,也不计入班级聚合。
"""
from sqlalchemy.orm import Session

from app.models.privacy import PrivacySetting

VISIBILITIES = ("private", "teachers", "classmates")
VISIBILITY_RANK = {"private": 0, "teachers": 1, "classmates": 2}
SCOPE_RANK = {"self": 0, "teacher": 1, "classmate": 2}

DEFAULTS = {
    "name_visibility": "classmates",
    "email_visibility": "private",
    "learning_visibility": "teachers",
}
VISIBILITY_LABEL = {
    "private": "仅自己",
    "teachers": "教师可见",
    "classmates": "同学可见",
}


def allowed(visibility: str, scope: str) -> bool:
    """scope: self / teacher / classmate"""
    return VISIBILITY_RANK.get(visibility, 0) >= SCOPE_RANK.get(scope, 0)


def get_or_create(db: Session, user_id: int, create: bool = True) -> PrivacySetting:
    row = db.query(PrivacySetting).filter(
        PrivacySetting.user_id == user_id,
    ).first()
    if row or not create:
        return row
    row = PrivacySetting(user_id=user_id, **DEFAULTS)
    db.add(row)
    db.flush()
    return row


def get_map(db: Session, user_ids: list[int]) -> dict[int, PrivacySetting]:
    if not user_ids:
        return {}
    rows = db.query(PrivacySetting).filter(
        PrivacySetting.user_id.in_(user_ids),
    ).all()
    return {row.user_id: row for row in rows}


def name_of(user, pref: PrivacySetting | None, scope: str, fallback: str = "匿名同学") -> str:
    visibility = pref.name_visibility if pref else DEFAULTS["name_visibility"]
    return user.name if allowed(visibility, scope) else fallback


def email_of(user, pref: PrivacySetting | None, scope: str) -> str:
    visibility = pref.email_visibility if pref else DEFAULTS["email_visibility"]
    return user.email if allowed(visibility, scope) else ""


def learning_visible(pref: PrivacySetting | None, scope: str = "teacher") -> bool:
    visibility = pref.learning_visibility if pref else DEFAULTS["learning_visibility"]
    return allowed(visibility, scope)
