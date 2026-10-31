"""初始化管理员账号(幂等)

用法(在 backend 目录):
    $env:LLM_API_KEY="sk-test"; python scripts/seed_admin.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.core.security import hash_password  # noqa: E402

ADMIN_EMAIL = "admin@itea.com"
ADMIN_PASSWORD = "Admin@123456"


def main():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if user:
            user.role = "admin"
            user.status = "active"
            user.password_hash = hash_password(ADMIN_PASSWORD)
        else:
            user = User(
                role="admin", name="系统管理员", email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD), status="active",
            )
            db.add(user)
        db.commit()
        print(f"ok: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
