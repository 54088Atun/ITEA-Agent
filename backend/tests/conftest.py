"""测试环境公共配置:默认关闭图形验证码,避免所有登录用例都要先取验证码"""
import pytest


@pytest.fixture(autouse=True)
def _disable_captcha_by_default(monkeypatch):
    from app.api import auth as auth_api

    monkeypatch.setattr(auth_api, "captcha_required", lambda: False)
