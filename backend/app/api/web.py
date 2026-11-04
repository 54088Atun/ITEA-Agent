"""受控联网路由:Web 搜索与页面抓取(教师、管理员)

返回结果必须带来源,与校内 RAG 分开标注。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import require_teacher
from app.models.user import User
from app.schemas.web import WebFetchRequest, WebSearchRequest
from app.services import web_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/web", tags=["受控联网"])


@router.post("/search")
def web_search(
    req: WebSearchRequest,
    _user: User = Depends(require_teacher),
):
    """联网搜索:需配置服务商;结果带链接与来源标记"""
    try:
        return web_access.search(req.query, req.top_k)
    except web_access.WebNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except web_access.WebAccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except web_access.WebAccessError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/fetch")
def web_fetch(
    req: WebFetchRequest,
    _user: User = Depends(require_teacher),
):
    """抓取白名单域名页面正文:不执行脚本、不跟随重定向"""
    try:
        return web_access.fetch(req.url)
    except web_access.WebAccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except web_access.WebAccessError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
