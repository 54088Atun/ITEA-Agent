"""隐私设置请求/响应模型(PC-07)"""
from typing import Literal

from pydantic import BaseModel

Visibility = Literal["private", "teachers", "classmates"]


class PrivacyOut(BaseModel):
    name_visibility: str
    email_visibility: str
    learning_visibility: str


class PrivacyUpdate(BaseModel):
    name_visibility: Visibility = "classmates"
    email_visibility: Visibility = "private"
    learning_visibility: Visibility = "teachers"
