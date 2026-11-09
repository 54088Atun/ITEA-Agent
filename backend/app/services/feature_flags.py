"""能力开关与配额配置:统一从 system_config 读取,缺省值兜底

管理端可在「系统配置」页直接修改,无需重启;未知键按缺省值处理。
"""
from sqlalchemy.orm import Session

from app.models.log import SystemConfig
from app.services.asr import asr_enabled
from app.services.capabilities import role_capabilities
from app.services.vision import vlm_enabled, vision_enabled
from app.services.web_access import web_search_enabled

FEATURE_DEFAULTS = {
    "feature_image_vision": ("on", "图片识图开关(on/off)"),
    "feature_assignments": ("on", "作业与考试开关(on/off)"),
    "feature_course_share": ("on", "课程分享码开关(on/off)"),
    "feature_exams": ("on", "题库与在线考试开关(on/off)"),
    "upload_image_max_mb": ("8", "图片上传大小上限(MB,1-8)"),
    "vision_daily_limit": ("30", "每人每日识图上传次数上限(0 为不限)"),
    "feature_asr": ("on", "语音识别开关(on/off)"),
    "feature_content_moderation": ("on", "上传内容审核开关(on/off)"),
    "moderation_keywords": ("", "自定义审核关键词(JSON,分类→词表,可选)"),
    "asr_max_mb": ("10", "单次音频大小上限(MB,1-50)"),
    "asr_max_seconds": ("300", "单次音频时长上限(秒,0 为不限)"),
    "asr_daily_limit": ("50", "每人每日语音识别次数上限(0 为不限)"),
    "asr_daily_seconds": ("1800", "每人每日语音识别总时长上限(秒,0 为不限)"),
}

_OFF_VALUES = {"off", "false", "0", "no", "disabled"}


def _raw(db: Session, key: str) -> str:
    row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    if row and row.config_value is not None and str(row.config_value).strip() != "":
        return str(row.config_value).strip()
    return FEATURE_DEFAULTS.get(key, ("", ""))[0]


def is_enabled(db: Session, key: str) -> bool:
    return _raw(db, key).lower() not in _OFF_VALUES


def get_int(db: Session, key: str, default: int = 0) -> int:
    try:
        return int(_raw(db, key))
    except (TypeError, ValueError):
        try:
            return int(FEATURE_DEFAULTS[key][0])
        except (KeyError, ValueError):
            return default


def public_features(db: Session, role: str = "student") -> dict:
    """供前端读取的开关与限额(不含敏感配置)"""
    return {
        "capabilities": role_capabilities(role),
        "feature_image_vision": is_enabled(db, "feature_image_vision"),
        "vision_ready": is_enabled(db, "feature_image_vision") and vision_enabled(),
        "vlm_ready": vlm_enabled(),
        "feature_assignments": is_enabled(db, "feature_assignments"),
        "feature_course_share": is_enabled(db, "feature_course_share"),
        "feature_exams": is_enabled(db, "feature_exams"),
        "upload_image_max_mb": max(1, min(get_int(db, "upload_image_max_mb", 8), 8)),
        "vision_daily_limit": max(0, get_int(db, "vision_daily_limit", 30)),
        "feature_asr": is_enabled(db, "feature_asr"),
        "asr_ready": is_enabled(db, "feature_asr") and asr_enabled(),
        "web_search_ready": web_search_enabled(),
        "asr_max_mb": max(1, min(get_int(db, "asr_max_mb", 10), 50)),
        "asr_max_seconds": max(0, get_int(db, "asr_max_seconds", 300)),
        "asr_daily_limit": max(0, get_int(db, "asr_daily_limit", 50)),
        "asr_daily_seconds": max(0, get_int(db, "asr_daily_seconds", 1800)),
    }


def seed_defaults(db: Session) -> None:
    """首次启动写入缺省配置(幂等)"""
    created = 0
    for key, (value, desc) in FEATURE_DEFAULTS.items():
        if db.query(SystemConfig).filter(SystemConfig.config_key == key).first():
            continue
        db.add(SystemConfig(config_key=key, config_value=value, description=desc))
        created += 1
    if created:
        db.commit()
