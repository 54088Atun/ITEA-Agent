"""认证相关请求/响应模型"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional


class RegisterRequest(BaseModel):
    role: str = Field(..., pattern="^(teacher|student)$")
    name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


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

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    # 兼容旧前端:保留扁平字段
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str
    # 新契约:补用户 ID 与完整用户对象
    user_id: int
    user: UserOut
