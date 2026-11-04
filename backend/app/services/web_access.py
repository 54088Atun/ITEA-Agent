"""受控联网:域名白名单、结果缓存、来源可追溯

安全边界:
- 搜索必须显式配置服务商;未配置时明确返回"未启用"
- 抓取只允许 http/https 与白名单域名,禁止内网/回环地址
- 不执行页面脚本、不跟随重定向,限制响应体积
- 所有结果带来源,与校内 RAG 分开标注
"""
import ipaddress
import logging
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 8000
_cache: dict[str, tuple[float, dict]] = {}


class WebAccessError(Exception):
    """联网访问被拒绝或失败"""


class WebNotConfigured(WebAccessError):
    """联网检索服务未配置"""


class WebAccessDenied(WebAccessError):
    """白名单、内网地址或体积等安全策略拒绝"""


def allowed_domains() -> list[str]:
    raw = (settings.WEB_ALLOWED_DOMAINS or "").replace(";", ",")
    return [
        item.strip().lower().lstrip(".")
        for item in raw.split(",")
        if item.strip()
    ]


def _domain_allowed(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    if not host:
        return False
    for domain in allowed_domains():
        if host == domain or host.endswith("." + domain):
            return True
    return False


def _assert_public_host(host: str) -> None:
    """拒绝回环、内网、链路本地等地址,避免 SSRF"""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise WebAccessError(f"域名无法解析: {host}") from exc
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            raise WebAccessDenied("目标地址属于内网或保留地址,已拒绝")


def _cache_get(key: str) -> dict | None:
    entry = _cache.get(key)
    if not entry:
        return None
    created_at, value = entry
    if time.time() - created_at > settings.WEB_CACHE_TTL:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: dict) -> None:
    _cache[key] = (time.time(), value)
    if len(_cache) > 256:
        oldest = min(_cache.items(), key=lambda item: item[1][0])[0]
        _cache.pop(oldest, None)


def _search_endpoint(provider: str) -> str:
    if settings.WEB_SEARCH_API_BASE.strip():
        return settings.WEB_SEARCH_API_BASE.strip()
    if provider == "bing":
        return "https://api.bing.microsoft.com/v7.0/search"
    if provider == "serpapi":
        return "https://serpapi.com/search.json"
    return ""


def search(query: str, top_k: int = 5) -> dict:
    """受控 Web 搜索:必须配置服务商,结果带来源链接"""
    keyword = (query or "").strip()
    if not keyword:
        raise WebAccessError("缺少搜索关键词")
    if len(keyword) > 200:
        raise WebAccessError("搜索关键词过长")
    top_k = min(max(1, int(top_k)), 10)

    provider = (settings.WEB_SEARCH_PROVIDER or "none").strip().lower()
    api_key = (settings.WEB_SEARCH_API_KEY or "").strip()
    endpoint = _search_endpoint(provider)
    if provider in ("none", "") or not endpoint or not api_key:
        raise WebNotConfigured(
            "联网检索未启用:请配置 WEB_SEARCH_PROVIDER 与 WEB_SEARCH_API_KEY",
        )

    cache_key = f"search:{provider}:{top_k}:{keyword}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    headers = {}
    params: dict = {"q": keyword}
    if provider == "bing":
        headers["Ocp-Apim-Subscription-Key"] = api_key
        params.update({"count": top_k, "mkt": "zh-CN", "setLang": "zh"})
    elif provider == "serpapi":
        params.update({"num": top_k, "api_key": api_key, "hl": "zh-cn"})
    else:
        raise WebNotConfigured(f"不支持的搜索服务商: {provider}")

    try:
        with httpx.Client(timeout=settings.WEB_FETCH_TIMEOUT) as client:
            response = client.get(endpoint, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise WebAccessError(f"联网检索失败: {exc}") from exc

    items: list[dict] = []
    if provider == "bing":
        for row in (payload.get("webPages") or {}).get("value", [])[:top_k]:
            items.append({
                "title": row.get("name") or "",
                "url": row.get("url") or "",
                "snippet": row.get("snippet") or "",
            })
    else:
        for row in payload.get("organic_results", [])[:top_k]:
            items.append({
                "title": row.get("title") or "",
                "url": row.get("link") or "",
                "snippet": row.get("snippet") or "",
            })

    result = {
        "query": keyword,
        "provider": provider,
        "items": [
            {**item, "source": "web"} for item in items if item["url"]
        ],
        "cached": False,
    }
    _cache_set(cache_key, result)
    return result


class _TextExtractor(HTMLParser):
    """提取标题与正文,跳过脚本、样式与导航噪音"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        elif tag in ("script", "style", "noscript", "template"):
            self._skip_depth += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style", "noscript", "template") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
        elif not self._skip_depth:
            self._parts.append(text)

    @property
    def text(self) -> str:
        joined = " ".join(self._parts)
        return " ".join(joined.split())[:MAX_TEXT_CHARS]


def extract_text(html: str) -> dict:
    """把 HTML 转成标题与纯文本,便于引用"""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001  页面结构异常时退化为空正文
        logger.warning("HTML 解析异常,返回已解析部分")
    return {"title": parser.title[:200], "text": parser.text}


def fetch(url: str) -> dict:
    """受控抓取:白名单域名 + 不跟随重定向 + 限制体积"""
    target = (url or "").strip()
    if not target:
        raise WebAccessError("缺少 URL")
    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https"):
        raise WebAccessDenied("只支持 http/https 链接")
    host = parsed.hostname or ""
    if not _domain_allowed(host):
        raise WebAccessDenied(f"域名不在白名单内: {host}")
    _assert_public_host(host)

    cache_key = f"fetch:{target}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    try:
        with httpx.Client(
            timeout=settings.WEB_FETCH_TIMEOUT,
            follow_redirects=False,
        ) as client:
            with client.stream("GET", target) as response:
                if 300 <= response.status_code < 400:
                    raise WebAccessDenied("目标返回重定向,已按安全策略拒绝")
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > settings.WEB_FETCH_MAX_BYTES:
                        raise WebAccessDenied("页面体积超过限制")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                content_type = response.headers.get("content-type", "")
    except httpx.HTTPError as exc:
        raise WebAccessError(f"页面抓取失败: {exc}") from exc

    if "html" not in content_type.lower() and "text" not in content_type.lower():
        raise WebAccessDenied("只支持抓取 HTML/文本页面")

    html = raw.decode("utf-8", errors="replace")
    extracted = extract_text(html)
    result = {
        "url": target,
        "title": extracted["title"],
        "text": extracted["text"],
        "content_type": content_type,
        "source": "web",
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cached": False,
    }
    _cache_set(cache_key, result)
    return result


def clear_cache() -> None:
    _cache.clear()
