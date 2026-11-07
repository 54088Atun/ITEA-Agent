"""本批共用的 UTC 时间工具

约定:
- 数据库 DateTime 列存 naive UTC;
- 外部输入的绝对时间必须带时区,先转 naive UTC 再入库;
- 入库前统一到秒精度,与 MySQL DATETIME(0) 对齐,避免四舍五入造成可见时间偏差。
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """当前 UTC 时间(naive,秒精度)"""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def normalize_seconds(value: datetime) -> datetime:
    """去掉微秒,保持原有的 naive/aware 属性"""
    return value.replace(microsecond=0)


def to_utc_naive(value: datetime) -> datetime:
    """带时区时间转 naive UTC;naive 输入直接拒绝,避免隐式按本地时区解释"""
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def parse_iso_utc(value: str) -> datetime:
    """解析带时区的 ISO 字符串为 naive UTC"""
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return to_utc_naive(parsed)
