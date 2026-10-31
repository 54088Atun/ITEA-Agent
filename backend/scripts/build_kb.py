"""知识库入库脚本

用法:
    cd backend
    python -m scripts.build_kb --course-id 1
    python -m scripts.build_kb --course-id 1 --dir uploads/1   # 直接指定目录

功能:
    读取课程教材文件(txt/md/pdf) → 分块 → 向量化 → 构建 FAISS 索引 → 回写 chunk_count
"""
import argparse
import logging
import os
import sys

# 确保能导入 app 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SUPPORTED_EXT = {".txt", ".md", ".pdf"}


def read_file(path: str) -> str:
    """读取文件内容(txt/md 直读,pdf 用 pdfplumber)"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md"):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    elif ext == ".pdf":
        try:
            import pdfplumber
            texts = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    texts.append(page.extract_text() or "")
            return "\n".join(texts)
        except ImportError:
            logger.warning("pdfplumber 未安装,pip install pdfplumber 后重试。跳过 %s", path)
            return ""
    return ""


def collect_from_db(course_id: int) -> list[dict]:
    """从数据库读取该课程已上传的教材"""
    from app.db.session import SessionLocal
    from app.models.course import CourseMaterial

    db = SessionLocal()
    try:
        materials = db.query(CourseMaterial).filter(CourseMaterial.course_id == course_id).all()
        documents = []
        for m in materials:
            if not os.path.exists(m.file_path):
                logger.warning("文件不存在: %s", m.file_path)
                continue
            content = read_file(m.file_path)
            if content.strip():
                documents.append({
                    "content": content,
                    "source": m.title,
                    "scope": m.type,
                })
                logger.info("读取教材: %s (%d 字)", m.title, len(content))
        return documents
    finally:
        db.close()


def collect_from_dir(directory: str, scope: str = "courseware") -> list[dict]:
    """直接扫描目录下的文件"""
    documents = []
    for fname in sorted(os.listdir(directory)):
        path = os.path.join(directory, fname)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(fname)[1].lower() not in SUPPORTED_EXT:
            continue
        content = read_file(path)
        if content.strip():
            documents.append({"content": content, "source": fname, "scope": scope})
            logger.info("读取文件: %s (%d 字)", fname, len(content))
    return documents


def build(course_id: int, documents: list[dict]):
    """构建 FAISS 索引并回写数据库"""
    from app.agent.tools.rag_search import get_manager
    from app.db.session import SessionLocal
    from app.models.course import CourseMaterial

    manager = get_manager()
    manager.build_index(course_id, documents)

    # 回写 chunk_count
    total_chunks = sum(
        len(manager.chunk_text(doc["content"])) for doc in documents
    )
    db = SessionLocal()
    try:
        db.query(CourseMaterial).filter(CourseMaterial.course_id == course_id).update(
            {CourseMaterial.chunk_count: total_chunks}
        )
        db.commit()
    finally:
        db.close()

    logger.info("课程 %s 入库完成: %d 个文档, %d 个分块", course_id, len(documents), total_chunks)


def main():
    parser = argparse.ArgumentParser(description="知识库入库脚本")
    parser.add_argument("--course-id", type=int, required=True, help="课程 ID")
    parser.add_argument("--dir", type=str, default="", help="直接指定文件目录(不查数据库)")
    parser.add_argument("--scope", type=str, default="courseware", help="目录模式下的 scope")
    args = parser.parse_args()

    if args.dir:
        documents = collect_from_dir(args.dir, args.scope)
    else:
        documents = collect_from_db(args.course_id)

    if not documents:
        logger.error("没有可入库的文档,请先上传教材或检查目录路径。")
        sys.exit(1)

    build(args.course_id, documents)


if __name__ == "__main__":
    main()