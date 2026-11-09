"""测试环境公共配置:默认关闭图形验证码与邮箱验证,避免既有用例被迫改造"""
import pytest


@pytest.fixture(autouse=True)
def _disable_auth_challenges_by_default(monkeypatch):
    from app.api import auth as auth_api

    monkeypatch.setattr(auth_api, "captcha_required", lambda: False)
    monkeypatch.setattr(auth_api, "email_verification_required", lambda: False)
