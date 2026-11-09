# ITEA-Agent

面向教学场景的智能教育 Agent 系统，覆盖学生个性化学习、教师课程与班级管理、平台运营与安全管理。后端基于 FastAPI 与 LangGraph，前端基于 Vue 3 与 Element Plus，支持课程知识库检索、学习状态跟踪、多 Agent 协作以及受控管理操作。

## 核心能力

### 学生学习

- 课程导向的智能辅导、知识点解析与练习反馈。
- 学情档案、知识点掌握度、错题集与复习计划。
- 课程作业、模拟面试、代码练习及学习进度查看。
- 基于课程资料的知识库检索，并在回答中保留来源信息。

### 教师教学

- 课程、课件、知识点、班级与学生管理。
- 作业发布、课程资料解析、题库与考核计划生成。
- 班级学情统计、学习报告和课程分享。
- 教师 Agent 辅助查询课程证据、分析学情和生成教学内容。

### 平台管理

- 用户、课程审核、系统配置、风控日志与操作审计。
- Agent 运行记录、运行指标、取消与计划调整等运行控制。
- 管理写操作采用“预览 → 确认 → 执行”闭环，取消不产生数据变更。
- 受控 SQL 统计、项目只读自检与域名白名单联网访问。

### Agent 运行时

- LangGraph 编排的路由、规划、工具执行、反思与记忆写入流程。
- 会话检查点、运行恢复、上下文预算压缩与长期记忆。
- 多 Agent 专家协作、工具调用边界、内容安全与提示注入防护。
- 可选图片识别、语音转写、本地向量模型和受控联网能力。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | Vue 3、Vite、Element Plus、Pinia、Axios |
| 后端 | Python、FastAPI、Uvicorn、SQLAlchemy |
| Agent | LangGraph、LangChain、OpenAI 兼容模型接口 |
| 数据 | MySQL、FAISS、sentence-transformers |
| 测试 | pytest、Node.js 内置测试运行器 |

## 目录结构

```text
ITEA-Agent/
├── backend/
│   ├── app/
│   │   ├── agent/          # Agent 图、节点、工具与提示词
│   │   ├── api/            # FastAPI 路由
│   │   ├── core/           # 配置、安全与公共依赖
│   │   ├── models/         # SQLAlchemy 数据模型
│   │   ├── schemas/        # 请求与响应模型
│   │   └── services/       # 业务服务
│   ├── evals/              # Agent 评测用例与运行框架
│   ├── scripts/            # 知识库和管理员初始化脚本
│   ├── tests/              # 后端自动化测试
│   ├── .env.example        # 环境变量模板
│   └── requirements.txt
├── frontend/
│   ├── src/                # 页面、组件、状态与 API 客户端
│   ├── tests/              # 前端单元测试
│   └── package.json
├── init_db.sql             # MySQL 数据库初始化脚本
└── LICENSE
```

## 环境要求

- Python 3.13（当前依赖组合已验证）
- Node.js 20.19+ 或 22.12+
- MySQL 8.0
- 一个兼容 OpenAI 接口格式的大语言模型服务

图片识别、语音转写、本地视觉模型和本地 ASR 均为可选能力，不是基础启动的前置条件。

## 快速开始

以下命令以 Windows PowerShell 为例；macOS 与 Linux 可使用对应的虚拟环境激活和文件复制命令。

### 1. 获取代码

```powershell
git clone https://github.com/54088Atun/ITEA-Agent.git
cd ITEA-Agent
```

### 2. 初始化数据库

使用 MySQL 客户端执行根目录的 `init_db.sql`：

```powershell
mysql -u root -p -e "source init_db.sql"
```

脚本会创建 `itea_agent` 数据库及项目所需数据表（仅表结构，不含业务数据；默认系统配置由后端启动时幂等写入）。

### 3. 配置并启动后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `backend/.env`，至少检查以下配置：

```dotenv
DATABASE_URL=mysql+pymysql://数据库用户:数据库密码@localhost:3306/itea_agent?charset=utf8mb4
SECRET_KEY=请替换为足够长的随机字符串
LLM_API_BASE=https://api.deepseek.com
LLM_API_KEY=你的模型服务密钥
LLM_MODEL=deepseek-flash
```

初始化本地管理员并启动服务：

```powershell
$env:ADMIN_EMAIL="admin@example.com"
$env:ADMIN_PASSWORD="请设置强密码"
python scripts/seed_admin.py
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

后端地址：

- 健康检查：`http://127.0.0.1:8000/health`
- OpenAPI 文档：`http://127.0.0.1:8000/docs`

> `seed_admin.py` 只从 `ADMIN_EMAIL` / `ADMIN_PASSWORD` 环境变量读取账号信息，仓库内不内置任何默认账号或密码。重复执行脚本会重置该管理员密码。

### 4. 启动前端

另开终端，在仓库根目录执行：

```powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

访问 `http://127.0.0.1:5173`。Vite 会将 `/api`、`/uploads` 和 `/static` 代理到 `http://127.0.0.1:8000`，因此前端开发服务启动前应先启动后端。

## 可选能力

- `backend/requirements-asr.txt`：本地 faster-whisper 语音转写依赖。
- `backend/requirements-vlm.txt`：本地视觉语义理解依赖。
- `VISION_PROVIDER=local_ocr`：使用本地 OCR；默认可通过 OpenAI 兼容多模态接口识图。
- `ASR_PROVIDER=local`：使用本地 ASR；默认可通过 OpenAI 兼容转写接口。
- `WEB_SEARCH_PROVIDER`：配置受控联网检索；`none` 表示关闭搜索服务。

完整的上下文预算、上传文件清理、项目自检、联网白名单及多模态配置见 `backend/.env.example` 和 `backend/app/core/config.py`。

### 邮箱验证与邮件通道

注册、未验证账号激活与自助找回密码都依赖邮箱验证码。开发环境可保持 `MAIL_PROVIDER=none`（验证码会写入后端日志便于联调）；生产环境必须配置阿里云邮件推送：

```dotenv
MAIL_PROVIDER=aliyun
ALIYUN_MAIL_ACCESS_KEY_ID=你的RAM子账号AccessKeyId
ALIYUN_MAIL_ACCESS_KEY_SECRET=你的RAM子账号AccessKeySecret
ALIYUN_MAIL_ACCOUNT_NAME=noreply@mail.itea-agent.xyz
REQUIRE_EMAIL_VERIFICATION=true
```

上线前需在阿里云控制台完成发信域名 MX/SPF/DKIM 解析、发信地址验证，并为 RAM 子账号授予最小发信权限。临时回滚可将 `REQUIRE_EMAIL_VERIFICATION` 置为 `false`（登录不再拦截未验证账号）。

## 测试与构建

后端完整测试：

```powershell
cd backend
pytest -q
```

前端测试与生产构建：

```powershell
cd frontend
npm test
npm run build
```

`backend/evals/` 提供 Agent 评测用例与评测框架，供后续修改提示词、工具契约或运行链路时进行回归评估。

## 开源文件范围

仓库保留部署、开发、验证和二次开发所需的内容：

- 前后端源码、数据库初始化脚本和启动脚本。
- 后端测试、前端测试、Agent 评测及依赖锁文件。
- 不含真实密钥的环境变量示例。

以下内容不会纳入版本库：真实 `.env`、API 密钥、上传文件、向量索引、日志、缓存、虚拟环境、`node_modules`、前端构建产物、本地运行数据以及 `.trae/` 工作区文件。忽略规则见根目录 `.gitignore`。

## 安全说明

- 不要提交真实 `.env`、数据库密码、API 密钥、业务数据或课件；数据库仅表结构（`init_db.sql`）入库。
- 生产环境必须替换示例数据库密码与 JWT `SECRET_KEY`；管理员密码只通过环境变量注入，不要写入仓库或文档。
- 管理写操作必须先预览再由有权限的用户确认；请妥善保护管理员账号。
- 项目自检与联网访问应限制在可信目录和域名范围内。
- 本项目提供的安全边界不能替代生产环境的鉴权、备份、审计、限流和密钥管理措施。

## 参与贡献

1. Fork 仓库并创建功能分支。
2. 保持改动聚焦，不提交本地配置、运行产物或敏感数据。
3. 修改后端时运行 `pytest -q`；修改前端时运行 `npm test` 和 `npm run build`。
4. 提交 Pull Request，说明变更目的、影响范围和验证结果。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
