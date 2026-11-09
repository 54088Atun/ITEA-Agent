# -*- coding: utf-8 -*-
"""阿里云 DirectMail 参数构造:模板发送、回信地址与 HTML 回退"""
import json

from app.core.config import settings
from app.services import mailer


def test_build_params_uses_template(monkeypatch):
    monkeypatch.setattr(settings, "ALIYUN_MAIL_ACCOUNT_NAME", "noreply@mail.itea-agent.xyz")
    monkeypatch.setattr(settings, "ALIYUN_MAIL_REPLY_TO", "3232762850@qq.com")

    params = mailer._build_params(
        "stu@campus.edu.cn", "【ITEA】注册验证码",
        template_id="447891", template_data={"Code": "482913"},
    )

    assert params["AccountName"] == "noreply@mail.itea-agent.xyz"
    assert params["ReplyToAddress"] == "true"
    assert params["ReplyAddress"] == "3232762850@qq.com"
    # 模板以 JSON 字符串传参,签名时按普通参数编码
    assert json.loads(params["Template"]) == {
        "TemplateId": "447891", "TemplateData": {"Code": "482913"},
    }
    assert "HtmlBody" not in params
    assert "TextBody" not in params


def test_build_params_falls_back_to_html(monkeypatch):
    monkeypatch.setattr(settings, "ALIYUN_MAIL_REPLY_TO", "")

    params = mailer._build_params("stu@campus.edu.cn", "主题", "<p>正文</p>", "正文")

    assert params["HtmlBody"] == "<p>正文</p>"
    assert params["TextBody"] == "正文"
    assert params["ReplyToAddress"] == "false"
    assert "ReplyAddress" not in params
    assert "Template" not in params


def test_template_id_for_purpose(monkeypatch):
    monkeypatch.setattr(settings, "ALIYUN_MAIL_TEMPLATE_REGISTER", "447891")
    monkeypatch.setattr(settings, "ALIYUN_MAIL_TEMPLATE_RESET_PASSWORD", "447892")

    assert mailer.template_id_for("register") == "447891"
    assert mailer.template_id_for("reset_password") == "447892"
    assert mailer.template_id_for("unknown") == ""
