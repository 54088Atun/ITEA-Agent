"""rag_search:知识库向量检索(FAISS + sentence-transformers)

实现要点:
- 文档分块(chunk 500 字, overlap 50)
- embedding 使用多语言 MiniLM(支持中文)
- 检索结果带来源标注,注入 prompt 供反思层校验
"""
import os
import json
import logging
import time
from typing import Optional

from app.services.course_access import agent_course_scope_error
from app.services.runtime_metrics import record_runtime_metric

logger = logging.getLogger(__name__)

# 延迟加载的全局单例
_manager = None


class RAGManager:
    """FAISS 向量索引管理器"""

    def __init__(self):
        self._embedding_model = None
        self._indexes = {}      # course_id -> {index, chunks}
        self._index_dir = os.path.join("static", "faiss_indexes")
        os.makedirs(self._index_dir, exist_ok=True)

    @property
    def embedding_model(self):
        """延迟加载 embedding 模型(首次调用较慢)"""
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                from app.core.config import settings
                model_name = settings.EMBEDDING_MODEL
                self._embedding_model = SentenceTransformer(model_name)
                logger.info("Embedding 模型加载完成: %s", model_name)
                logger.info("Embedding 模型加载完成")
            except Exception as e:
                logger.error("Embedding 模型加载失败: %s", e)
                raise
        return self._embedding_model

    # ---------- 分块 ----------

    @staticmethod
    def chunk_spans(text: str, chunk_size: int = 500, overlap: int = 50) -> list[tuple[int, int]]:
        """分块并保留原文区间,供页码/原文定位使用"""
        if not text:
            return []
        spans = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            spans.append((start, min(end, len(text))))
            start = end - overlap
        return spans

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        """按字符分块,带重叠"""
        return [
            text[start:end]
            for start, end in RAGManager.chunk_spans(text, chunk_size, overlap)
        ]

    @staticmethod
    def page_of_offset(page_spans: list[dict], offset: int) -> int | None:
        """按字符偏移定位页码;无页信息时返回 None"""
        for span in page_spans or []:
            if span.get("start", 0) <= offset < span.get("end", 0):
                return span.get("page")
        return page_spans[0].get("page") if page_spans else None

    # ---------- 构建/加载索引 ----------

    def build_index(self, course_id: int, documents: list[dict]):
        """从文档列表构建 FAISS 索引

        documents: [{
            "content": str, "source": str, "scope": str,
            "material_id": int | None,
            "page_spans": [{"page": int, "start": int, "end": int}],  # 可选,用于页码定位
        }, ...]
        """
        import faiss
        import numpy as np

        all_chunks = []
        for doc in documents:
            content = doc.get("content", "")
            page_spans = doc.get("page_spans") or []
            material_id = doc.get("material_id")
            for index, (start, end) in enumerate(self.chunk_spans(content)):
                all_chunks.append({
                    "text": content[start:end],
                    "source": doc.get("source", "未知来源"),
                    "scope": doc.get("scope", "courseware"),
                    "material_id": material_id,
                    "page": self.page_of_offset(page_spans, start),
                    "chunk_index": index,
                })

        if not all_chunks:
            logger.warning("课程 %s 无文档可索引", course_id)
            return

        started_at = time.monotonic()
        try:
            texts = [c["text"] for c in all_chunks]
            embeddings = self.embedding_model.encode(texts, normalize_embeddings=True)
            embeddings = np.array(embeddings, dtype="float32")

            index = faiss.IndexFlatIP(embeddings.shape[1])
            index.add(embeddings)

            self._indexes[course_id] = {"index": index, "chunks": all_chunks}
            # 持久化
            idx_path = os.path.join(self._index_dir, f"course_{course_id}.index")
            meta_path = os.path.join(self._index_dir, f"course_{course_id}.json")
            faiss.write_index(index, idx_path)
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(all_chunks, f, ensure_ascii=False)
            logger.info("课程 %s 索引构建完成(%d chunks)", course_id, len(all_chunks))
        except Exception:
            record_runtime_metric(
                "index", "failure", (time.monotonic() - started_at) * 1000,
            )
            raise
        record_runtime_metric(
            "index", "success", (time.monotonic() - started_at) * 1000,
        )

    def index_ready(self, course_id: int) -> bool:
        """索引文件是否就绪(不加载 faiss,便于每轮快速判断)"""
        idx_path = os.path.join(self._index_dir, f"course_{course_id}.index")
        meta_path = os.path.join(self._index_dir, f"course_{course_id}.json")
        return os.path.exists(idx_path) and os.path.exists(meta_path)

    def load_index(self, course_id: int) -> bool:
        """加载已有索引,成功返回 True"""
        if course_id in self._indexes:
            return True
        idx_path = os.path.join(self._index_dir, f"course_{course_id}.index")
        meta_path = os.path.join(self._index_dir, f"course_{course_id}.json")
        if not (os.path.exists(idx_path) and os.path.exists(meta_path)):
            return False
        try:
            import faiss

            index = faiss.read_index(idx_path)
            with open(meta_path, "r", encoding="utf-8") as f:
                chunks = json.load(f)
            self._indexes[course_id] = {"index": index, "chunks": chunks}
            logger.info("课程 %s 索引加载完成(%d chunks)", course_id, len(chunks))
            return True
        except Exception as e:
            logger.warning("课程 %s 索引加载失败: %s", course_id, e)
            return False

    # ---------- 检索 ----------

    def search(
        self,
        query: str,
        course_id: int,
        scope: Optional[str] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """向量检索,返回带来源标注的片段"""
        import numpy as np

        if not self.load_index(course_id):
            logger.warning("课程 %s 无可用索引,返回空结果", course_id)
            return []

        data = self._indexes[course_id]
        query_vec = self.embedding_model.encode(
            [query], normalize_embeddings=True
        )
        query_vec = np.array(query_vec, dtype="float32")

        scores, indices = data["index"].search(query_vec, top_k * 2)

        results = []
        for rank, (score, idx) in enumerate(zip(scores[0], indices[0])):
            if idx < 0 or idx >= len(data["chunks"]):
                continue
            chunk = data["chunks"][idx]
            if scope and chunk["scope"] != scope:
                continue
            results.append({
                "text": chunk["text"],
                "source": chunk["source"],
                "scope": chunk["scope"],
                "score": float(score),
                "material_id": chunk.get("material_id"),
                "page": chunk.get("page"),
                "chunk_index": chunk.get("chunk_index"),
            })
            if len(results) >= top_k:
                break

        return results


def get_manager() -> RAGManager:
    global _manager
    if _manager is None:
        _manager = RAGManager()
    return _manager


def index_ready(course_id: int) -> bool:
    """不加载模型的轻量索引就绪判断"""
    return get_manager().index_ready(course_id)


# ---------- 工具入口 ----------

def rag_search(
    query: str,
    course_id: int,
    scope: Optional[str] = None,
    top_k: int = 5,
    user_id: Optional[int] = None,
) -> dict:
    """知识库检索工具(仅在已构建课程 FAISS 索引时可用)

    课程事实题应优先使用 `course_evidence`(复用课程检索 API);本工具用于
    已显式构建索引的场景,未配置索引或依赖缺失时返回明确不可用,不伪造来源。

    Args:
        query: 检索问题
        course_id: 课程 ID
        scope: 检索范围(courseware/syllabus/exercise/interview)
        top_k: 返回条数
        user_id: 调用者 ID,用于课程范围强校验(缺失即拒绝)

    Returns:
        {"fragments": [...], "context": "拼接文本"} 或
        {"fragments": [], "context": "(...)", "error": "index_unavailable|retrieval_failed"}
    """
    scope_error = agent_course_scope_error(user_id, course_id)
    if scope_error:
        return {
            "fragments": [],
            "context": f"(检索失败: {scope_error})",
            "error": scope_error,
        }
    try:
        manager = get_manager()
        load_index = getattr(manager, "load_index", None)
        if callable(load_index) and not load_index(course_id):
            logger.warning("课程 %s 未配置检索索引,返回不可用", course_id)
            return {
                "fragments": [],
                "context": "(检索不可用: 课程索引未配置)",
                "error": "index_unavailable",
            }
        fragments = manager.search(query, course_id, scope, top_k)
        # 拼接为带来源标注的上下文文本,供 prompt 注入与反思层校验
        context_parts = [
            f"[{i+1}] (来源: {f['source']}) {f['text']}"
            for i, f in enumerate(fragments)
        ]
        return {
            "fragments": fragments,
            "context": "\n\n".join(context_parts) if context_parts else "(未检索到相关内容)",
        }
    except Exception as e:
        logger.error("rag_search 执行失败: %s", e)
        return {
            "fragments": [],
            "context": "(检索不可用: 检索服务异常)",
            "error": "retrieval_failed",
        }