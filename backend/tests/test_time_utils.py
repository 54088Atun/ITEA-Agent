"""UTC 时间工具:精度统一、时区转换与非法输入"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core import time as time_utils


def test_utcnow_is_naive_and_second_precision():
    now = time_utils.utcnow()
    assert now.tzinfo is None
    assert now.microsecond == 0
    reference = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((reference - now).total_seconds()) < 2


def test_to_utc_naive_converts_offset_and_drops_microseconds():
    value = datetime(2026, 11, 5, 9, 0, 0, 123456,
                     tzinfo=timezone(timedelta(hours=8)))
    assert time_utils.to_utc_naive(value) == datetime(2026, 11, 5, 1, 0, 0)


def test_to_utc_naive_rejects_naive_input():
    with pytest.raises(ValueError):
        time_utils.to_utc_naive(datetime(2026, 11, 5, 9, 0, 0))


def test_parse_iso_utc_accepts_offset_and_z():
    assert time_utils.parse_iso_utc("2026-11-05T09:00:00+08:00") == datetime(
        2026, 11, 5, 1, 0, 0,
    )
    assert time_utils.parse_iso_utc("2026-11-05T01:00:00Z") == datetime(
        2026, 11, 5, 1, 0, 0,
    )
    with pytest.raises(ValueError):
        time_utils.parse_iso_utc("2026-11-05T09:00:00")


def test_normalize_seconds_keeps_tzinfo():
    aware = datetime(2026, 11, 5, 9, 0, 0, 999999, tzinfo=timezone.utc)
    assert time_utils.normalize_seconds(aware) == datetime(
        2026, 11, 5, 9, 0, 0, tzinfo=timezone.utc,
    )
