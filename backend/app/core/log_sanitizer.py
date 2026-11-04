"""统一日志脱敏工具。"""
import logging
import re


_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_email(email: str) -> str:
    local, separator, domain = email.partition("@")
    if not separator or not local:
        return email
    return f"{local[0]}***@{domain}"


def mask_emails(text: str) -> str:
    return _EMAIL_PATTERN.sub(lambda match: mask_email(match.group(0)), text)


def content_meta(text: str) -> str:
    return f"[内容已脱敏 chars={len(text)}]"


def safe_exception(exc: Exception) -> str:
    return type(exc).__name__


class SensitiveLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_emails(record.getMessage())
        record.args = ()
        return True
