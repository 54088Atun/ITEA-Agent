"""API 路由汇总"""
from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.course import router as course_router
from app.api.chat import router as chat_router
from app.api.student import router as student_router
from app.api.teacher import router as teacher_router
from app.api.admin import router as admin_router
from app.api.agent import router as agent_router
from app.api.classroom import router as classroom_router
from app.api.uploads import router as uploads_router
from app.api.me import router as me_router
from app.api.assignments import router as assignments_router
from app.api.course_share import router as course_share_router
from app.api.records import router as records_router
from app.api.exams import router as exams_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(course_router)
api_router.include_router(chat_router)
api_router.include_router(student_router)
api_router.include_router(teacher_router)
api_router.include_router(admin_router)
api_router.include_router(classroom_router)
api_router.include_router(uploads_router)
api_router.include_router(me_router)
api_router.include_router(assignments_router)
api_router.include_router(course_share_router)
api_router.include_router(records_router)
api_router.include_router(exams_router)
api_router.include_router(agent_router)
