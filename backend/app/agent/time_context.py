"""Agent 时间上下文:统一注入服务端当前时间,支持自然语言相对日期换算。"""
from datetime import datetime
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Shanghai")
_WEEKDAYS = "一二三四五六日"


def now_text() -> str:
    """返回带时区与星期的当前时间文本。"""
    now = datetime.now(TIMEZONE)
    return (
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
        f"（Asia/Shanghai，星期{_WEEKDAYS[now.weekday()]}）"
    )


def time_prompt() -> str:
    """注入业务提示词的时间说明。"""
    return (
        f"\n\n【当前时间】{now_text()}。"
        "用户说“今天/明天/后天/本周/下周”时，请基于该时间换算为带时区的 ISO 8601 时间"
        "（例如 2026-11-10T20:00:00+08:00），不要要求用户自行换算或提供内部 ID。"
        "需要设置提醒时直接调用 reminder_scheduler，user_id 由系统自动补全。"
    )
