"""认证相关请求/响应模型"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional


class RegisterRequest(BaseModel):
    role: str = Field(..., pattern="^(teacher|student)$")
    name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, value: str) -> str:
        if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
            raise ValueError("密码需至少 8 位，且同时包含字母和数字")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    role: str
    name: str
    email: str
    status: Optional[str] = "active"
    admin_level: Optional[str] = None
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    # 兼容旧前端:保留扁平字段
    access_token: str
    token_type: str = "bearer"
    # 访问令牌剩余有效秒数,供前端提前续期
    expires_in: int = 0
    role: str
    name: str
    # 新契约:补用户 ID 与完整用户对象
    user_id: int
    user: UserOut
