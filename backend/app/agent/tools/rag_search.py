"""rag_search:知识库检索(向量优先,词法兜底)

实现要点:
- 文档分块(chunk 500 字, overlap 50)
- 生产环境裁剪了 faiss/sentence-transformers 时,自动降级为 BM25 词法检索
  (中文按字符二元组切分),无需额外依赖即可基于课程资料作答
- 检索结果带来源标注,注入 prompt 供反思层校验
"""
import math
import os
import json
import logging
import re
import time
from collections import Counter
from typing import Optional

from app.core.config import settings
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
        self._index_dir = settings.RAG_INDEX_DIR
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

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """轻量分词:英文数字按词,中文按字符二元组,无需第三方分词依赖"""
        lowered = (text or "").lower()
        tokens = re.findall(r"[a-z0-9_]+", lowered)
        for seq in re.findall(r"[\u4e00-\u9fff]+", lowered):
            if len(seq) == 1:
                tokens.append(seq)
            else:
                tokens.extend(seq[i:i + 2] for i in range(len(seq) - 1))
        return tokens

    def _remove_index_files(self, course_id: int) -> None:
        for name in (f"course_{course_id}.index", f"course_{course_id}.json"):
            try:
                os.remove(os.path.join(self._index_dir, name))
            except FileNotFoundError:
                continue
            except OSError as exc:
                logger.warning("删除课程索引失败 %s: %s", name, exc)

    def build_index(self, course_id: int, documents: list[dict]) -> int:
        """从文档列表构建索引,返回分块数

        向量依赖(faiss/sentence-transformers)不可用时只落 chunks 元数据,
        检索自动使用 BM25 词法兜底,保证精简生产依赖下仍可基于课程资料作答。

        documents: [{
            "content": str, "source": str, "scope": str,
            "material_id": int | None,
            "page_spans": [{"page": int, "start": int, "end": int}],  # 可选,用于页码定位
        }, ...]
        """
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
            self._indexes.pop(course_id, None)
            self._remove_index_files(course_id)
            return 0

        started_at = time.monotonic()
        meta_path = os.path.join(self._index_dir, f"course_{course_id}.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(all_chunks, f, ensure_ascii=False)
        self._indexes[course_id] = {"index": None, "chunks": all_chunks}

        outcome = "success"
        if settings.RAG_VECTOR_ENABLED:
            try:
                import faiss
                import numpy as np

                texts = [c["text"] for c in all_chunks]
                embeddings = self.embedding_model.encode(texts, normalize_embeddings=True)
                embeddings = np.array(embeddings, dtype="float32")

                index = faiss.IndexFlatIP(embeddings.shape[1])
                index.add(embeddings)
                faiss.write_index(
                    index, os.path.join(self._index_dir, f"course_{course_id}.index"),
                )
                self._indexes[course_id]["index"] = index
                logger.info("课程 %s 向量索引构建完成(%d chunks)", course_id, len(all_chunks))
            except Exception as exc:  # noqa: BLE001
                # 依赖缺失或模型不可用:保留 chunks,检索走词法兜底
                outcome = "failure"
                logger.info("课程 %s 向量索引不可用,使用词法检索: %s", course_id, exc)

        record_runtime_metric(
            "index", outcome, (time.monotonic() - started_at) * 1000,
        )
        return len(all_chunks)

    def index_ready(self, course_id: int) -> bool:
        """分块元数据是否就绪(不加载模型;向量索引可选)"""
        meta_path = os.path.join(self._index_dir, f"course_{course_id}.json")
        return os.path.exists(meta_path)

    def load_index(self, course_id: int) -> bool:
        """加载已有索引,成功返回 True;向量索引不可用时仅加载 chunks"""
        idx_path = os.path.join(self._index_dir, f"course_{course_id}.index")
        meta_path = os.path.join(self._index_dir, f"course_{course_id}.json")
        if course_id in self._indexes:
            # 元数据被外部清理(素材删除/重建)时同步失效内存缓存,避免返回已删除内容
            if os.path.exists(meta_path):
                return True
            self._indexes.pop(course_id, None)
        if not os.path.exists(meta_path):
            return False
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                chunks = json.load(f)
        except Exception as e:
            logger.warning("课程 %s 索引元数据读取失败: %s", course_id, e)
            return False

        index = None
        if settings.RAG_VECTOR_ENABLED and os.path.exists(idx_path):
            try:
                import faiss

                index = faiss.read_index(idx_path)
            except Exception as e:  # noqa: BLE001
                logger.info("课程 %s 向量索引不可用,降级词法检索: %s", course_id, e)
        self._indexes[course_id] = {"index": index, "chunks": chunks}
        logger.info(
            "课程 %s 索引加载完成(%d chunks, 向量=%s)",
            course_id, len(chunks), index is not None,
        )
        return True

    # ---------- 检索 ----------

    @staticmethod
    def _fragment(chunk: dict, score: float) -> dict:
        return {
            "text": chunk["text"],
            "source": chunk["source"],
            "scope": chunk["scope"],
            "score": score,
            "material_id": chunk.get("material_id"),
            "page": chunk.get("page"),
            "chunk_index": chunk.get("chunk_index"),
        }

    def _vector_search(
        self, query: str, data: dict, scope: Optional[str], top_k: int,
    ) -> list[dict]:
        import numpy as np

        query_vec = self.embedding_model.encode(
            [query], normalize_embeddings=True
        )
        query_vec = np.array(query_vec, dtype="float32")

        scores, indices = data["index"].search(query_vec, top_k * 2)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(data["chunks"]):
                continue
            chunk = data["chunks"][idx]
            if scope and chunk["scope"] != scope:
                continue
            results.append(self._fragment(chunk, float(score)))
            if len(results) >= top_k:
                break
        return results

    def _lexical_search(
        self, query: str, data: dict, scope: Optional[str], top_k: int,
    ) -> list[dict]:
        """BM25 词法检索:未安装向量依赖时的默认检索方式"""
        chunks = data["chunks"]
        prepared = data.get("lexical")
        if prepared is None:
            tokenized = [self._tokenize(c.get("text", "")) for c in chunks]
            doc_freq = Counter()
            for tokens in tokenized:
                doc_freq.update(set(tokens))
            prepared = {
                "tf": [Counter(tokens) for tokens in tokenized],
                "lengths": [len(tokens) for tokens in tokenized],
                "df": doc_freq,
                "avgdl": (sum(len(t) for t in tokenized) / len(tokenized))
                if tokenized else 0.0,
            }
            data["lexical"] = prepared

        terms = set(self._tokenize(query))
        if not terms:
            return []

        total = len(chunks)
        avgdl = prepared["avgdl"] or 1.0
        doc_freq = prepared["df"]
        k1, b = 1.5, 0.75
        scored = []
        for i, counts in enumerate(prepared["tf"]):
            length = prepared["lengths"][i]
            score = 0.0
            for term in terms:
                freq = counts.get(term, 0)
                if not freq:
                    continue
                idf = math.log(
                    1 + (total - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5),
                )
                score += idf * freq * (k1 + 1) / (
                    freq + k1 * (1 - b + b * length / avgdl)
                )
            if score <= 0:
                continue
            chunk = chunks[i]
            if scope and chunk["scope"] != scope:
                continue
            scored.append((score, i))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            self._fragment(chunks[i], float(score))
            for score, i in scored[:top_k]
        ]

    def search(
        self,
        query: str,
        course_id: int,
        scope: Optional[str] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """检索,返回带来源标注的片段;向量不可用时自动降级为词法检索"""
        if not self.load_index(course_id):
            logger.warning("课程 %s 无可用索引,返回空结果", course_id)
            return []

        data = self._indexes[course_id]
        if data.get("index") is not None:
            try:
                return self._vector_search(query, data, scope, top_k)
            except Exception as exc:  # noqa: BLE001
                logger.info("课程 %s 向量检索失败,降级词法: %s", course_id, exc)
        return self._lexical_search(query, data, scope, top_k)


def get_manager() -> RAGManager:
    global _manager
    if _manager is None:
        _manager = RAGManager()
    return _manager


def index_ready(course_id: int) -> bool:
    """不加载模型的轻量索引就绪判断"""
    return get_manager().index_ready(course_id)


def rebuild_course_index(db, course_id: int) -> int:
    """按"审核通过 + 解析完成"的素材重建课程索引,返回分块总数

    素材上传解析完成、解析结果变化或素材删除后调用,保证检索内容与
    当前素材一致;索引构建失败向上抛出,由调用方决定是否影响主流程。
    """
    from app.models.course import CourseMaterial, MaterialParseJob

    rows = (
        db.query(CourseMaterial, MaterialParseJob)
        .join(MaterialParseJob, MaterialParseJob.material_id == CourseMaterial.id)
        .filter(
            CourseMaterial.course_id == course_id,
            CourseMaterial.moderation_status == "approved",
            MaterialParseJob.status == "done",
        )
        .all()
    )

    documents = []
    chunk_counts = {}
    for material, job in rows:
        text = (job.result_text or "").strip()
        if not text:
            continue
        documents.append({
            "content": text,
            "source": material.title or f"素材#{material.id}",
            "scope": material.type or "courseware",
            "material_id": material.id,
        })
        chunk_counts[material.id] = len(RAGManager.chunk_spans(text))

    total = get_manager().build_index(course_id, documents)
    for material, _job in rows:
        material.chunk_count = chunk_counts.get(material.id, 0)
    db.commit()
    logger.info("课程 %s 索引重建完成(%d 素材, %d chunks)",
                course_id, len(documents), total)
    return total


# ---------- 工具入口 ----------

def rag_search(
    query: str,
    course_id: int,
    scope: Optional[str] = None,
    top_k: int = 5,
    user_id: Optional[int] = None,
) -> dict:
    """知识库检索工具(课程索引就绪时可用;向量依赖缺失时走词法检索)

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