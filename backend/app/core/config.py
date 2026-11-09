"""全局配置,从环境变量 / .env 文件加载"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
DEFAULT_DATABASE_URL = "mysql+pymysql://root:123456@localhost:3306/itea_agent?charset=utf8mb4"
DEFAULT_SECRET_KEY = "change-this-to-a-random-secret-key"


class Settings(BaseSettings):
    # 数据库
    DATABASE_URL: str = DEFAULT_DATABASE_URL

    # JWT
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    ALGORITHM: str = "HS256"
    # 访问令牌短期有效,过期后由前端用刷新令牌静默续期
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 10080
    # 公开注册允许的邮箱域(逗号分隔,留空表示不限制),例如 edu.cn,university.edu
    REGISTER_EMAIL_DOMAINS: str = ""
    # 图形验证码:登录/注册前校验,一次性、5 分钟有效
    CAPTCHA_ENABLED: bool = True
    CAPTCHA_TTL_SECONDS: int = 300
    # 验证码存储:memory(默认,单进程) 或 file(共享目录,多进程/多实例)
    CAPTCHA_STORE: str = "memory"
    CAPTCHA_STORE_DIR: str = "data/captcha"
    # 登录限流:账号维度与 IP 维度(失败次数/窗口秒)
    LOGIN_IP_MAX_FAILURES: int = 20
    LOGIN_IP_WINDOW_SECONDS: int = 300

    # LLM(DeepSeek,兼容 OpenAI 接口格式)
    LLM_API_BASE: str = "https://api.deepseek.com"
    LLM_API_KEY: str = ""  # 必须从 .env 或环境变量注入,禁止硬编码
    LLM_MODEL: str = "deepseek-flash"  # 统一使用 flash,覆盖全部场景
    LLM_TEMPERATURE: float = 0.3
    # 任务规划:开启后 planner 用一次低成本模型调用生成计划;
    # 关闭时沿用静态模板,避免测试环境产生外部调用
    PLANNER_LLM_ENABLED: bool = False

    # 阿里云百炼(DashScope)API Key:识图与语音识别共用
    DASHSCOPE_API_KEY: str = ""
    # 图片识别:provider=openai 走多模态模型,provider=local_ocr 走本机 PP-OCRv5
    VISION_PROVIDER: str = "openai"
    VISION_API_BASE: str = ""
    VISION_API_KEY: str = ""
    VISION_MODEL: str = ""
    # 本地 OCR:脚本路径留空则自动探测 local-ocr-npu 技能
    VISION_LOCAL_SCRIPT: str = ""
    VISION_LOCAL_DEVICE: str = "cpu"
    VISION_LOCAL_TIMEOUT: int = 180
    # 本地图片语义理解(可选):留空则只用 OCR
    VISION_VLM_MODEL: str = ""
    VISION_VLM_MAX_NEW_TOKENS: int = 120
    VISION_VLM_TIMEOUT: int = 300

    # 语音识别:provider=openai 走兼容接口,provider=local 走本机 faster-whisper
    ASR_PROVIDER: str = "openai"
    ASR_API_BASE: str = ""
    ASR_API_KEY: str = ""
    ASR_MODEL: str = ""
    # 百炼实时语音识别(浏览器边录边出字)
    ASR_REALTIME_MODEL: str = "qwen-audio-3.1-asr-flash-message"
    ASR_REALTIME_URL: str = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    # 本地 ASR:模型名(tiny/base/small/medium)或本地模型目录,留空则关闭
    ASR_LOCAL_MODEL: str = ""
    ASR_LOCAL_DEVICE: str = "cpu"
    ASR_LOCAL_COMPUTE_TYPE: str = "int8"
    ASR_LANGUAGE: str = "zh"
    ASR_TIMEOUT: int = 60
    ASR_MAX_BYTES: int = 10 * 1024 * 1024
    # 聊天侧文档解析上限(不落盘留存)
    CHAT_DOC_MAX_BYTES: int = 10 * 1024 * 1024

    # 上传文件保留期(天)与每日清理时间
    FILE_RETENTION_DAYS: int = 30
    DRAFT_RETENTION_DAYS: int = 7
    CLEANUP_HOUR: int = 3
    CLEANUP_MINUTE: int = 30
    # 实际上传字节上限(不信任 Content-Length)
    MATERIAL_MAX_BYTES: int = 50 * 1024 * 1024
    CLASS_IMPORT_MAX_BYTES: int = 5 * 1024 * 1024

    # 向量模型
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    # 默认使用 BM25 词法检索(生产裁剪 torch 后仍可基于课程资料作答);
    # 显式开启且 faiss/sentence-transformers 可用时才额外构建向量索引。
    RAG_VECTOR_ENABLED: bool = False
    # 索引落盘目录:必须在静态挂载目录之外,避免被 /static 路由直接下载
    RAG_INDEX_DIR: str = "data/faiss_indexes"

    # 应用
    ENVIRONMENT: str = "development"  # development/test/production
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    STATIC_DIR: str = "static"
    UPLOAD_DIR: str = "uploads"
    # CORS 显式来源(逗号分隔);生产禁止通配符 *
    CORS_ALLOW_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 反思循环最大次数
    MAX_REFLECTION_ROUNDS: int = 2

    # 上下文工程(P1-2):按预算压缩学情、大纲、检索片段与历史
    CONTEXT_BUDGET_ENABLED: bool = True
    CONTEXT_RAG_CHARS: int = 2400
    CONTEXT_MAX_FRAGMENTS: int = 4
    CONTEXT_PROFILE_CHARS: int = 900
    CONTEXT_SYLLABUS_CHARS: int = 1200
    CONTEXT_HISTORY_TOKENS: int = 900

    # 多 Agent 协作(P1-7):专家级超时与失败重试
    COLLAB_EXPERT_TIMEOUT: int = 45
    COLLAB_EXPERT_RETRIES: int = 1

    # 代码沙箱限制
    CODE_EXEC_TIMEOUT: int = 10
    CODE_EXEC_MEMORY_MB: int = 256

    # 项目自检:留空则使用仓库根目录;仅允许访问该目录内的只读内容
    PROJECT_ROOT: str = ""
    PROJECT_MAX_FILE_BYTES: int = 512 * 1024
    PROJECT_MAX_READ_LINES: int = 400
    PROJECT_TEST_TIMEOUT: int = 300

    # 受控联网:未配置搜索服务时只允许受控抓取
    WEB_SEARCH_PROVIDER: str = "none"  # none/bing/serpapi
    WEB_SEARCH_API_BASE: str = ""
    WEB_SEARCH_API_KEY: str = ""
    WEB_ALLOWED_DOMAINS: str = "moe.gov.cn,edu.cn,gov.cn"
    WEB_FETCH_TIMEOUT: int = 10
    WEB_FETCH_MAX_BYTES: int = 2 * 1024 * 1024
    WEB_CACHE_TTL: int = 600

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"

    def __init__(self, **values):
        super().__init__(**values)
        if self.ENVIRONMENT.strip().lower() != "production":
            return

        invalid_fields = []
        if not self.SECRET_KEY.strip() or self.SECRET_KEY == DEFAULT_SECRET_KEY:
            invalid_fields.append("SECRET_KEY")
        if not self.DATABASE_URL.strip() or self.DATABASE_URL == DEFAULT_DATABASE_URL:
            invalid_fields.append("DATABASE_URL")
        if "*" in self.cors_origins:
            invalid_fields.append("CORS_ALLOW_ORIGINS")
        if invalid_fields:
            fields = ", ".join(invalid_fields)
            raise RuntimeError(f"生产环境必须显式配置非空且非默认值: {fields}")

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def static_path(self) -> Path:
        p = BASE_DIR / self.STATIC_DIR
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def upload_path(self) -> Path:
        p = BASE_DIR / self.UPLOAD_DIR
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()