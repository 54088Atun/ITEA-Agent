"""公开站点内容:首页与联系页的可配置文案

管理端把结构化内容以 JSON 存进 system_config,这里只读取这两项,
不会暴露其它配置键。
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.log import SystemConfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/site", tags=["公开站点"])

HOME_KEY = "site.home_content"
CONTACT_KEY = "site.contact_content"
SITE_KEYS = (HOME_KEY, CONTACT_KEY)


def load_site_content(db: Session) -> dict:
    """读取站点内容;缺失或格式错误时返回 None,由前端回落到内置默认文案"""
    rows = (
        db.query(SystemConfig)
        .filter(SystemConfig.config_key.in_(SITE_KEYS))
        .all()
    )
    stored = {row.config_key: row.config_value for row in rows}

    def _parse(key: str) -> Optional[dict]:
        raw = stored.get(key)
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("站点内容格式错误,已忽略: %s", key)
            return None
        return value if isinstance(value, dict) else None

    return {"home": _parse(HOME_KEY), "contact": _parse(CONTACT_KEY)}


@router.get("/content")
def get_public_site_content(response: Response, db: Session = Depends(get_db)):
    """公开读取首页与联系页内容(无需登录);禁止缓存,后台保存后立即生效"""
    response.headers["Cache-Control"] = "no-store"
    return load_site_content(db)
