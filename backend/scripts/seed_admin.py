"""初始化管理员账号(幂等)

账号信息只从环境变量读取,不写入仓库。

用法(在 backend 目录):
    $env:ADMIN_EMAIL="admin@example.com"; $env:ADMIN_PASSWORD="<强密码>"; python scripts/seed_admin.py
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.core.security import hash_password  # noqa: E402


def main():
    email = (os.getenv("ADMIN_EMAIL") or "").strip()
    password = os.getenv("ADMIN_PASSWORD") or ""
    if not email or not password:
        print("请先设置 ADMIN_EMAIL 与 ADMIN_PASSWORD 环境变量")
        raise SystemExit(2)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.role = "admin"
            user.status = "active"
            user.password_hash = hash_password(password)
        else:
            user = User(
                role="admin", name="系统管理员", email=email,
                password_hash=hash_password(password), status="active",
                email_verified_at=datetime.utcnow(),
            )
            db.add(user)
        db.commit()
        print(f"ok: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
