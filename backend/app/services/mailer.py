"""邮件发送服务(阿里云邮件推送 DirectMail)

不引入阿里云 SDK:用 httpx + 标准库 hmac/hashlib/base64 直接实现 RPC 签名,
减少生产镜像体积。配置见 Settings 中的 ALIYUN_MAIL_* 项。

优先使用控制台审核通过的模板发送(Template.TemplateId + TemplateData),
模板未配置时回退为直接发送 HTML 正文,便于本地联调。
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from app.core.config import settings
from app.core.log_sanitizer import mask_email

logger = logging.getLogger(__name__)

ALIYUN_MAIL_VERSION = "2015-11-23"
ALIYUN_MAIL_ACTION = "SingleSendMail"

_SUBJECTS = {
    "register": "【ITEA】注册验证码",
    "reset_password": "【ITEA】密码重置验证码",
    "change_email": "【ITEA】邮箱变更验证码",
}
_PURPOSE_TEXT = {
    "register": "注册账号",
    "reset_password": "重置密码",
    "change_email": "更换绑定邮箱",
}


class MailSendError(RuntimeError):
    """邮件发送失败(配置缺失、网关拒绝或网络异常)"""


def is_mail_configured() -> bool:
    return bool(settings.mail_configured)


def _percent_encode(value: str) -> str:
    """阿里云 RPC 签名要求的 percent-encode(空格 %20、* 转 %2A、~ 保留)"""
    return quote(str(value), safe="~")


def _sign(params: dict, secret: str) -> str:
    canonical = "&".join(
        f"{_percent_encode(key)}={_percent_encode(value)}"
        for key, value in sorted(params.items())
    )
    string_to_sign = "GET&%2F&" + _percent_encode(canonical)
    digest = hmac.new(
        f"{secret}&".encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def template_id_for(purpose: str) -> str:
    """按用途取控制台模板 ID;未配置返回空串(走 HTML 直发回退)"""
    mapping = {
        "register": settings.ALIYUN_MAIL_TEMPLATE_REGISTER,
        "reset_password": settings.ALIYUN_MAIL_TEMPLATE_RESET_PASSWORD,
        "change_email": settings.ALIYUN_MAIL_TEMPLATE_CHANGE_EMAIL,
    }
    return (mapping.get(purpose) or "").strip()


def _build_params(
    to_email: str,
    subject: str,
    html: str = "",
    text: str = "",
    template_id: str = "",
    template_data: Optional[dict] = None,
) -> dict:
    reply_to = (settings.ALIYUN_MAIL_REPLY_TO or "").strip()
    params = {
        "Action": ALIYUN_MAIL_ACTION,
        "Format": "JSON",
        "Version": ALIYUN_MAIL_VERSION,
        "AccessKeyId": settings.ALIYUN_MAIL_ACCESS_KEY_ID,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": secrets.token_hex(16),
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "RegionId": settings.ALIYUN_MAIL_REGION_ID,
        "AccountName": settings.ALIYUN_MAIL_ACCOUNT_NAME,
        "AddressType": str(settings.ALIYUN_MAIL_ADDRESS_TYPE),
        "ReplyToAddress": "true" if reply_to else "false",
        "ToAddress": to_email,
        "Subject": subject,
    }
    if reply_to:
        params["ReplyAddress"] = reply_to
    if settings.ALIYUN_MAIL_FROM_ALIAS:
        params["FromAlias"] = settings.ALIYUN_MAIL_FROM_ALIAS
    if template_id:
        # 模板发送时 HtmlBody/TextBody 会被忽略,统一不传
        params["Template"] = json.dumps(
            {
                "TemplateId": str(template_id),
                "TemplateData": template_data or {},
            },
            ensure_ascii=False, separators=(",", ":"),
        )
    else:
        params["HtmlBody"] = html
        params["TextBody"] = text
    return params


def _send_once(
    to_email: str,
    subject: str,
    html: str = "",
    text: str = "",
    template_id: str = "",
    template_data: Optional[dict] = None,
) -> None:
    params = _build_params(
        to_email, subject, html, text, template_id, template_data,
    )
    params["Signature"] = _sign(params, settings.ALIYUN_MAIL_ACCESS_KEY_SECRET)
    # 用标准库发请求:避免 httpx 的 INFO 日志把带验证码/密钥的完整 URL 打出来
    query = urllib.parse.urlencode(
        params, quote_via=urllib.parse.quote, safe="~",
    )
    url = f"https://{settings.ALIYUN_MAIL_ENDPOINT}/?{query}"
    try:
        with urllib.request.urlopen(
            url, timeout=max(1, settings.ALIYUN_MAIL_TIMEOUT),
        ) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except (urllib.error.URLError, OSError) as exc:
        raise MailSendError(type(exc).__name__) from exc

    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError):
        data = {}
    code = str(data.get("Code") or "")
    if status != 200 or code not in ("", "OK"):
        # 只透传错误码,不向调用方暴露阿里云原始报文
        logger.warning(
            "阿里云邮件发送失败: %s code=%s status=%s",
            mask_email(to_email), code or "unknown", status,
        )
        raise MailSendError(code or f"http_{status}")


def send_html(to_email: str, subject: str, html: str, text: Optional[str] = None) -> None:
    """发送 HTML 邮件;失败重试 1 次,仍失败则抛 MailSendError"""
    if not is_mail_configured():
        raise MailSendError("mail_not_configured")
    body = text or ""
    last_error: Optional[Exception] = None
    for _ in range(2):
        try:
            _send_once(to_email, subject, html, body)
            logger.info("邮件已发送: %s subject=%s", mask_email(to_email), subject)
            return
        except MailSendError as exc:
            last_error = exc
    raise MailSendError(str(last_error) if last_error else "send_failed")


def send_template(
    to_email: str,
    subject: str,
    template_id: str,
    template_data: Optional[dict] = None,
) -> None:
    """按控制台模板发送;失败重试 1 次,仍失败则抛 MailSendError"""
    if not is_mail_configured():
        raise MailSendError("mail_not_configured")
    last_error: Optional[Exception] = None
    for _ in range(2):
        try:
            _send_once(
                to_email, subject, template_id=template_id,
                template_data=template_data or {},
            )
            logger.info(
                "邮件已发送(模板): %s template=%s",
                mask_email(to_email), template_id,
            )
            return
        except MailSendError as exc:
            last_error = exc
    raise MailSendError(str(last_error) if last_error else "send_failed")


def _render_code_email(purpose: str, code: str) -> tuple[str, str, str]:
    action = _PURPOSE_TEXT.get(purpose, "验证身份")
    subject = _SUBJECTS.get(purpose, "【ITEA】邮箱验证码")
    html = f"""\
<div style="font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
            max-width:520px;margin:0 auto;padding:28px;color:#1f2937;">
  <h2 style="font-size:18px;margin:0 0 12px;">ITEA 教学助手</h2>
  <p style="font-size:14px;line-height:1.8;margin:0 0 16px;">
    你正在{action}，请在页面中输入下方验证码完成验证。
  </p>
  <div style="font-size:32px;font-weight:700;letter-spacing:8px;color:#1d4ed8;
              background:#eff6ff;border-radius:8px;padding:18px 0;text-align:center;">
    {code}
  </div>
  <p style="font-size:13px;color:#6b7280;line-height:1.8;margin:16px 0 0;">
    验证码 10 分钟内有效，仅可使用一次，请勿转发给他人。
  </p>
  <p style="font-size:12px;color:#9ca3af;line-height:1.8;margin:12px 0 0;">
    若非本人操作，请忽略本邮件，你的账号不会受到影响。
  </p>
</div>"""
    text = f"ITEA 教学助手\n你正在{action}，验证码:{code}\n10 分钟内有效，请勿转发。"
    return subject, html, text


def send_verification_code(to_email: str, purpose: str, code: str) -> None:
    """发送验证码邮件;未配置邮件通道时,非生产环境写日志便于联调"""
    subject, html, text = _render_code_email(purpose, code)
    if not is_mail_configured():
        if settings.ENVIRONMENT.strip().lower() == "production":
            raise MailSendError("mail_not_configured")
        logger.warning(
            "邮件服务未配置(开发环境),验证码 %s purpose=%s email=%s",
            code, purpose, mask_email(to_email),
        )
        return
    template_id = template_id_for(purpose)
    if template_id:
        # 模板变量与控制台 {Code} 占位一一对应
        send_template(to_email, subject, template_id, {"Code": str(code)})
        return
    send_html(to_email, subject, html, text)
