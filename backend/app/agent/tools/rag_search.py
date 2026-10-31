"""rag_search:知识库向量检索(FAISS + sentence-transformers)

实现要点:
- 文档分块(chunk 500 字, overlap 50)
- embedding 使用多语言 MiniLM(支持中文)
- 检索结果带来源标注,注入 prompt 供反思层校验
"""
import os
import json
import logging
from typing import Optional

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
    def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        """按字符分块,带重叠"""
        if not text:
            return []
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start = end - overlap
        return chunks

    # ---------- 构建/加载索引 ----------

    def build_index(self, course_id: int, documents: list[dict]):
        """从文档列表构建 FAISS 索引

        documents: [{"content": str, "source": str, "scope": str}, ...]
        """
        import faiss
        import numpy as np

        all_chunks = []
        for doc in documents:
            for chunk in self.chunk_text(doc["content"]):
                all_chunks.append({
                    "text": chunk,
                    "source": doc.get("source", "未知来源"),
                    "scope": doc.get("scope", "courseware"),
                })

        if not all_chunks:
            logger.warning("课程 %s 无文档可索引", course_id)
            return

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

    def load_index(self, course_id: int) -> bool:
        """加载已有索引,成功返回 True"""
        if course_id in self._indexes:
            return True
        try:
            import faiss

            idx_path = os.path.join(self._index_dir, f"course_{course_id}.index")
            meta_path = os.path.join(self._index_dir, f"course_{course_id}.json")
            if not (os.path.exists(idx_path) and os.path.exists(meta_path)):
                return False
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
            })
            if len(results) >= top_k:
                break

        return results


def get_manager() -> RAGManager:
    global _manager
    if _manager is None:
        _manager = RAGManager()
    return _manager


# ---------- 工具入口 ----------

def rag_search(
    query: str,
    course_id: int,
    scope: Optional[str] = None,
    top_k: int = 5,
) -> dict:
    """知识库检索工具

    Args:
        query: 检索问题
        course_id: 课程 ID
        scope: 检索范围(courseware/syllabus/exercise/interview)
        top_k: 返回条数

    Returns:
        {"fragments": [{"text", "source", "scope", "score"}, ...], "context": "拼接文本"}
    """
    try:
        manager = get_manager()
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
        return {"fragments": [], "context": f"(检索失败: {e})"}