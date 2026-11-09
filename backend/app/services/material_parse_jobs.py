"""教材解析任务(NF-04):上传后异步解析 + 内容审核(NF-02)

流程:
1. 上传接口保存文件与素材后调用 enqueue 创建 pending 任务,并交由后台执行
2. run_parse_job 解析文本 → 内容审核 → 更新进度与结论
3. 审核通过 status=done、素材 moderation_status=approved;命中违规 status=rejected,
   素材置为 rejected(不参与检索、学生不可预览);解析异常 status=failed 可重试

生产环境由 FastAPI BackgroundTasks 执行 process_parse_job;测试可直接调用
run_parse_job(使用传入的会话)。
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.log_sanitizer import safe_exception
from app.models.course import Course, CourseMaterial, MaterialParseJob
from app.services.content_moderation import (
    moderation_enabled, record_rejection, screen_with_config,
)
from app.services.material_parser import IMAGE_EXTS, extract_text, extract_text_async
from app.services.runtime_metrics import record_runtime_metric

logger = logging.getLogger(__name__)

MAX_RESULT_CHARS = 12000
STATUS_LABEL = {
    "pending": "排队中",
    "processing": "解析中",
    "done": "已解析",
    "rejected": "未通过审核",
    "failed": "解析失败",
}


def material_out(
    material: CourseMaterial, job: Optional[MaterialParseJob] = None,
) -> dict:
    """素材序列化:附带解析任务状态,供前端展示进度与重试"""
    return {
        "id": material.id,
        "course_id": material.course_id,
        "type": material.type,
        "title": material.title,
        "file_path": material.file_path,
        "chunk_count": material.chunk_count,
        "moderation_status": material.moderation_status,
        "uploaded_at": material.uploaded_at,
        "parse_status": job.status if job else None,
        "parse_progress": job.progress if job else 0,
        "parse_error": job.error if job else None,
        "parse_attempts": job.attempts if job else 0,
    }


def get_job(db: Session, material_id: int) -> Optional[MaterialParseJob]:
    return db.query(MaterialParseJob).filter(
        MaterialParseJob.material_id == material_id,
    ).first()


def enqueue(db: Session, material: CourseMaterial) -> MaterialParseJob:
    """创建或重置解析任务(pending),素材回到待审核状态"""
    job = get_job(db, material.id)
    if job is None:
        job = MaterialParseJob(material_id=material.id, course_id=material.course_id)
        db.add(job)
    job.status = "pending"
    job.progress = 0
    job.error = None
    job.moderation_hits = None
    job.finished_at = None
    material.moderation_status = "pending"
    db.commit()
    db.refresh(job)
    return job


def _finish(job: MaterialParseJob, status: str, error: Optional[str]) -> None:
    job.status = status
    job.progress = 100
    job.error = error
    job.finished_at = datetime.utcnow()


def _refresh_course_index(db: Session, course_id: int) -> None:
    """按最新解析结果重建课程检索索引;失败只记日志,不影响解析结论"""
    try:
        from app.agent.tools.rag_search import rebuild_course_index

        rebuild_course_index(db, course_id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("课程索引重建失败 course=%s: %s", course_id, safe_exception(exc))


def _run_parse_job(db: Session, job_id: int) -> Optional[MaterialParseJob]:
    """执行解析与审核;使用调用方会话,便于测试断言"""
    job = db.query(MaterialParseJob).filter(MaterialParseJob.id == job_id).first()
    if job is None:
        return None
    material = db.query(CourseMaterial).filter(
        CourseMaterial.id == job.material_id,
    ).first()
    if material is None:
        _finish(job, "failed", "素材不存在")
        db.commit()
        return job

    job.status = "processing"
    job.progress = 10
    job.attempts = (job.attempts or 0) + 1
    job.error = None
    job.moderation_hits = None
    material.moderation_status = "pending"
    db.commit()

    path = Path(material.file_path)
    if not path.is_file():
        _finish(job, "failed", "素材文件缺失，请重新上传")
        material.moderation_status = "approved"
        db.commit()
        return job

    try:
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTS:
            text = asyncio.run(extract_text_async(path, path.name))
        else:
            text = extract_text(path, path.name)
    except HTTPException as exc:
        _finish(job, "failed", str(exc.detail))
        material.moderation_status = "approved"
        db.commit()
        return job
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "素材解析失败 material=%s: %s", material.id, safe_exception(exc),
        )
        _finish(job, "failed", "解析失败，请重试或更换文件格式")
        material.moderation_status = "approved"
        db.commit()
        return job

    job.progress = 70
    verdict = (
        screen_with_config(db, text) if moderation_enabled(db)
        else {"flagged": False, "categories": [], "hits": []}
    )
    if verdict["flagged"]:
        job.moderation_hits = json.dumps(verdict, ensure_ascii=False)
        _finish(
            job, "rejected",
            "内容审核未通过：" + "、".join(verdict["categories"]),
        )
        material.moderation_status = "rejected"
        course = db.query(Course).filter(Course.id == material.course_id).first()
        record_rejection(
            db, course.teacher_id if course else 0, text, verdict,
            f"素材#{material.id} {material.title}",
        )
        db.commit()
        logger.info("素材审核拒绝 material=%s hits=%s", material.id, verdict["hits"])
        # 素材可能此前已入库,驳回后需从索引中移除
        _refresh_course_index(db, material.course_id)
        return job

    job.result_text = text[:MAX_RESULT_CHARS]
    _finish(job, "done", None)
    material.moderation_status = "approved"
    db.commit()
    logger.info(
        "素材解析完成 material=%s chars=%s attempts=%s",
        material.id, len(text), job.attempts,
    )
    # 解析/审核通过后立即刷新课程索引,让 Agent 能基于新素材作答
    _refresh_course_index(db, material.course_id)
    return job


def run_parse_job(db: Session, job_id: int) -> Optional[MaterialParseJob]:
    started_at = time.monotonic()
    try:
        job = _run_parse_job(db, job_id)
    except Exception:
        record_runtime_metric(
            "parse", "failure", (time.monotonic() - started_at) * 1000,
        )
        raise
    if job is not None:
        outcome = {"done": "success", "failed": "failure", "rejected": "rejected"}[
            job.status
        ]
        record_runtime_metric(
            "parse", outcome, (time.monotonic() - started_at) * 1000,
        )
    return job


def process_parse_job(job_id: int) -> None:
    """后台执行入口:独立会话,异常不向调用方抛出"""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        run_parse_job(db, job_id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("解析任务异常 job=%s: %s", job_id, safe_exception(exc))
        try:
            job = db.query(MaterialParseJob).filter(
                MaterialParseJob.id == job_id,
            ).first()
            if job:
                _finish(job, "failed", "解析任务异常，请重试")
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()
