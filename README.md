# RoughCut

**当前版本：** RoughCut v0.1.5（2026-04-27）

面向口播/开箱视频的自动剪辑 + 字幕审校系统。

上传原始视频后，流水线按固定审核关口推进：转写 → 字幕后处理 → 术语纠错 → 内容画像 → 摘要确认 → 剪辑决策 → 渲染输出 → 成片审核 → 平台文案。摘要确认之后，下游默认只消费已确认版本，不再在 `edit_plan` 阶段回写字幕。

---

## 功能

- **自动剪辑** — 检测静音段和语气词，生成剪辑时间轴，保留有效内容
- **转写** — 默认使用通用 `local_http_asr` 本地 HTTP ASR 插槽，当前配置指向 MOSS-Audio 8B Instruct；离线本地依赖可选 `FunASR SenseVoice` 或 `faster-whisper`，云端可切回 OpenAI
- **字幕** — 字幕时间戳重映射至剪辑后时间轴，烧录荧光描边样式（黑字 + 绿色发光）
- **封面选帧** — 视觉模型从多个候选帧中挑选最佳封面，可选标题文字叠加
- **旋转修正** — 视觉模型识别实际画面方向，正确处理 iPhone 横屏/竖屏及错误元数据
- **渲染诊断** — 每次 render 落盘保存源文件哈希校验、ffprobe 结果、完整 ffmpeg 命令与 stderr 日志，便于手动复现
- **术语纠错** — 维护品牌/型号词表，自动匹配并标注疑似错误
- **断点续跑** — 每步骤状态持久化在数据库，进程崩溃后可从中断处继续
- **目录监听** — 监听指定文件夹，新视频自动入队处理
- **多 LLM 后端** — MiniMax / 智谱 GLM / OpenAI / Anthropic / Ollama 可配置切换

---

## 架构

前后端现在拆成两层：

```
frontend     — React + Vite 控制台
api          — FastAPI API + 生产环境静态托管 frontend/dist
```

当前 React 控制台已接管：

- 任务列表 / 上传建任务 / 内容核对 / 字幕报告
- 监控目录扫描与入队
- 包装素材管理
- 风格模板选择
- 行为记忆统计
- 术语词表
- 系统设置与服务控制

当前项目仍处于原型开发阶段，默认策略是：

- 新需求直接重构，不为旧页面/旧配置保留兼容层
- 优先保证结构收敛、代码可维护，再考虑迁移成本
- 只有确认进入正式版后，才开始补兼容策略
- 主逻辑合理、数据来源正确、职责边界清晰之后，才补失败用例和异常拦截；禁止用失败用例固化错误的生产路径

项目级构建原则见 [Project Build Principles](docs/design/project-build-principles.md)。

后台仍由 5 个长期进程推进任务，通过数据库协调状态：

```
orchestrator — 状态机，轮询 job_steps 推进流水线
worker-media — FFmpeg 媒体处理（Celery）
worker-llm   — 转写后处理 / LLM 推理（Celery）
worker-agent — Telegram/ACP/Codex 远程工程任务（Celery）
watcher      — 目录监听，自动入队
```

流水线步骤顺序：

```
probe → extract_audio → transcribe → subtitle_postprocess
      → glossary_review → subtitle_translation → content_profile
      → summary_review → ai_director → avatar_commentary
      → edit_plan → render → final_review → platform_package
```

这条顺序是当前的统一执行主线；公开设计文档入口见 [设计文档索引](docs/design/INDEX.md)。
同时，任务接口现在直接暴露 `review_step / review_detail`，前端不再自行猜测当前处于摘要审核还是成片审核。

---

## 环境要求

- Python 3.11+
- `pnpm`
- `uv`（项目内部 Python 依赖与 CLI 仍使用它）
- FFmpeg（需在 PATH 中，支持 libx264 / libass；如需硬编码，可额外启用 h264_qsv / h264_amf / h264_nvenc）
- Docker / Docker Compose（推荐用于基础服务或完整部署）
- LLM 后端之一：MiniMax API Key、Ollama（本地）或 OpenAI API Key

---

## 开源发布前清洗

公开仓库只保留可复用代码、公开文档和示例配置。以下内容应保持在本地忽略文件或外部系统中，不进入 Git 历史：

- `.env`、浏览器登录态、账号映射、密钥和令牌
- 真实创作者档案、真实发布任务、热词记忆、学习缓存
- Codex/agent 状态文档、会话台账、真实运行证据
- 临时排障脚本、导出的调试产物、一次性截图/图片

当前仓库已通过 `.gitignore` 隔离这些目录和文件，但如果它们曾经进入过 Git 历史，忽略规则本身不够，还需要重写历史。

历史清洗脚本：[`scripts/rewrite_open_source_history.ps1`](scripts/rewrite_open_source_history.ps1)

配套模板：

- [`scripts/open_source_history/paths.example.txt`](scripts/open_source_history/paths.example.txt)
- [`scripts/open_source_history/replace-text.example.txt`](scripts/open_source_history/replace-text.example.txt)

推荐流程：

1. 先确保当前工作树已经把私有文件从索引移除，并由 `.gitignore` 接管。
2. 提交最终的开源清理改动；历史重写只处理已提交历史，不会包含未提交工作树。
3. 基于模板准备本地路径清单和替换词表。
4. 运行历史清洗脚本，生成一个新的镜像仓库和校验副本。
5. 在重写后的仓库再次扫描敏感串，并在确认无误后再执行强推。
6. 任何已经暴露过的密钥都要在 Git 之外完成轮换；重写历史不能替代密钥轮换。

完整发布清单见 [Open Source Release Checklist](docs/design/open-source-release-checklist.md)。

---

## 快速开始

现在推荐只把 `pnpm` 当作统一入口。Python 侧依然由 `uv` 负责，但日常命令统一从根目录执行 `pnpm ...`。

### 1. 安装 pnpm 和 uv

```bash
# 安装 pnpm
corepack enable
corepack prepare pnpm@latest --activate

# Windows (PowerShell) 安装 uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 安装依赖

```bash
pnpm bootstrap
```

这一步会：

- 用 `uv sync --extra dev` 安装默认 Python 依赖
- 用 `pnpm install` 安装根工作区和 `frontend/` 的前端依赖

如果你明确要在宿主机里启用 `funasr` / `faster-whisper`，再额外运行：

```bash
uv sync --extra dev --extra local-asr
```

### 3. 初始化项目目录

```bash
pnpm setup
```

这一步会创建：

- `./data/runtime/jobs`
- `./data/runtime/output`
- `./data/runtime/cache`
- `./data/runtime/render-debug`
- `./data/runtime/tools`
- `./data/runtime/voice_refs`
- `./data/runtime/voice`
- `watch`
- `.env`（若不存在且 `.env.example` 存在）

### 4. 启动基础依赖

现在推荐的日常开发路径是：本地 Python + 本地前端 + 必要时只起 `infra`。

最低成本常驻，只起基础设施：

```bash
pnpm docker:infra:up
```

这一步主要给本地 API / worker 提供 PostgreSQL、Redis 和 MinIO，不负责承载默认开发入口。

如果你明确要跑容器化 runtime，再显式启动：

```bash
pnpm docker:runtime:up
```

其中基础设施包含 PostgreSQL（5432）和 Redis（6379），容器化 runtime/full 仍保留，但属于显式容器模式。

如果你要一次性起全套服务并带自动重建，使用：

```bash
pnpm docker:auto:auto-up
```

只起 runtime（不带 automation）并自动重建：

```bash
pnpm docker:runtime:auto-up
```

对应的服务访问地址默认为：

- `http://127.0.0.1:${ROUGHCUT_API_PORT}/`，默认值在 `roughcut.ports.env` 中是 `38471`

数字人相关服务现在默认走独立共享服务，不再依赖 RoughCut 内部 Docker：

- HeyGem: `http://127.0.0.1:49202`
- 语音克隆默认走 RunningHub；本地 `49204` 仅在显式启用 IndexTTS2 时使用
- HeyGem 公共服务目录: 通过 `HEYGEM_DOCKER_COMPOSE_FILE` / `HEYGEM_DOCKER_ENV_FILE` 指向外部共享服务
- HeyGem 公共服务数据根: 通过 `HEYGEM_SHARED_ROOT` 指向共享目录
- HeyGem 公共服务语音目录: 通过 `HEYGEM_VOICE_ROOT` 指向共享目录
- RoughCut 不迁移 HeyGem 本体或公共数据根；只迁移自己的 `jobs` / `output` / `cache` / `render-debug` / `tools` / `voice_refs` / `voice` 等运行数据

### 5. 配置环境变量

复制 `.env.example` 为 `.env` 并按需修改：

```bash
cp .env.example .env
```

所有本机端口统一放在 `roughcut.ports.env`，包括 API、Vite、PostgreSQL、Redis、MinIO、本地 ASR/TTS/数字人服务和浏览器发布代理。`.env` 只放密钥、模型选择、路径、功能开关等运行配置；需要换端口时改 `roughcut.ports.env`，不要在脚本或页面里散落硬编码端口。

最小配置（本地 Ollama + 本地 ASR 服务）：

```env
REASONING_PROVIDER=ollama
REASONING_MODEL=qwen3.5:9b        # 需支持视觉
TRANSCRIPTION_PROVIDER=local_http_asr
TRANSCRIPTION_MODEL=qwen3-asr-1.7b-forced-aligner
LOCAL_ASR_API_BASE_URL=http://127.0.0.1:30080
LOCAL_ASR_MODEL_NAME=qwen3-asr-1.7b-forced-aligner
LOCAL_ASR_DISPLAY_NAME=Qwen3-ASR 1.7B + ForcedAligner

ROUGHCUT_OUTPUT_ROOT=./data/runtime
JOB_STORAGE_DIR=./data/runtime/jobs
OUTPUT_DIR=./data/runtime/output
RENDER_DEBUG_DIR=./data/runtime/render-debug
PACKAGING_ASSET_DIR=assets/packaging
RENDER_VIDEO_ENCODER=auto
AUTO_CONFIRM_CONTENT_PROFILE=true
CONTENT_PROFILE_REVIEW_THRESHOLD=0.72
AUTO_ACCEPT_GLOSSARY_CORRECTIONS=true
GLOSSARY_CORRECTION_REVIEW_THRESHOLD=0.9
AUTO_SELECT_COVER_VARIANT=true
COVER_SELECTION_REVIEW_GAP=0.08
PACKAGING_SELECTION_REVIEW_GAP=0.08
PACKAGING_SELECTION_MIN_SCORE=0.6
AVATAR_PROVIDER=heygem
AVATAR_API_BASE_URL=http://127.0.0.1:49202
AVATAR_TRAINING_API_BASE_URL=http://127.0.0.1:49204
HEYGEM_DOCKER_ENV_FILE=../heygem/.env
HEYGEM_SHARED_ROOT=./data/heygem-shared
HEYGEM_VOICE_ROOT=./data/heygem-shared/voice/data
VOICE_PROVIDER=runninghub
VOICE_CLONE_API_BASE_URL=https://www.runninghub.cn
VOICE_CLONE_VOICE_ID=2003864334474354690
```

`RENDER_VIDEO_ENCODER` 当前支持 `auto`、`libx264`、`h264_qsv`、`h264_amf`、`h264_nvenc`。`auto` 会优先选择 Intel `QSV` 或 AMD `AMF` 这类集显编码方案，只有集显不可用时才回退到 `NVENC`，最后才是 `libx264`。

语音克隆默认走 RunningHub；只有显式设置 `VOICE_PROVIDER=indextts2` 和 `INDEXTTS2_API_PORT` 时，本地启动脚本才会探测 IndexTTS2。

MiniMax 默认配置：

```env
MINIMAX_API_KEY=sk-...
MINIMAX_CODING_PLAN_API_KEY=sk-... # 可留空，默认复用 MINIMAX_API_KEY
REASONING_PROVIDER=minimax
REASONING_MODEL=MiniMax-M2.7
MULTIMODAL_FALLBACK_PROVIDER=minimax
MULTIMODAL_FALLBACK_MODEL=MiniMax-M2.7
SEARCH_PROVIDER=minimax
SEARCH_FALLBACK_PROVIDER=minimax
```

OpenAI 兼容替代配置：

```env
OPENAI_API_KEY=sk-...
REASONING_PROVIDER=openai
REASONING_MODEL=gpt-5.5
TRANSCRIPTION_PROVIDER=openai
TRANSCRIPTION_MODEL=gpt-4o-transcribe
```

智谱 GLM 配置：

```env
ZHIPU_API_KEY=sk-...
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
ZHIPU_CODING_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4
ZHIPU_MCP_HTTP_BASE_URL=https://open.bigmodel.cn/api/mcp
REASONING_PROVIDER=zhipu
REASONING_MODEL=glm-5.1
VISION_MODEL=glm-4.6v-flash
MULTIMODAL_FALLBACK_PROVIDER=zhipu
MULTIMODAL_FALLBACK_MODEL=glm-4.6v-flash
SEARCH_PROVIDER=zhipu
SEARCH_FALLBACK_PROVIDER=zhipu
ZHIPU_SEARCH_ENGINE=search_pro
```

智能发布封面默认使用 Codex 内置 `image_gen` 工作流：系统会先用候选帧合成接触表识别高光帧，再为每个平台写出一份 `*.codex-imagegen.json` 请求清单和参考帧；请求未完成或生成失败时，该平台物料保持 `publish_ready=false`，不会生成可发布兜底封面。只有显式设置 `INTELLIGENT_COPY_COVER_IMAGE_BACKEND=openai_images_api` 时，才会走直接 OpenAI Images API 后端。Codex 路径里的 `INTELLIGENT_COPY_COVER_CODEX_RUNNER_MODEL` 只控制执行 `image_gen` 调用的 Codex 文本代理，默认 `gpt-5.4-mini` + `low`；真正影响画面质量的是请求里的 prompt、尺寸/比例、文字约束、QC 和重试策略，不是把执行代理改成 `gpt-5.5`。

Codex 图片请求完成后，用 `uv run python scripts/run_codex_imagegen_queue.py <smart-copy目录> --complete <请求json> --result <Codex生成图片>` 回填并标记完成；只有请求 JSON 状态为 `completed` 且输出文件存在，封面才会进入可发布状态。

如果你希望 RoughCut 走 Codex / GPT-5 系列的工程型模型链路，仍可显式切回 OpenAI Provider。当前 OpenAI Provider 已统一切到 `Responses API`，
因此这条可选链路会同时覆盖：

- 推理生成
- 多帧图像理解
- `web_search` 搜索增强

`OPENAI_AUTH_MODE=helper` 只适合 helper 返回实际 OpenAI Platform API key 的情况。
如果 helper 只是输出 `~/.codex/auth.json` 里的 ChatGPT access token，直接调用 OpenAI `Responses API`
做 `web_search` 当前会因为缺少 `api.responses.write` / `api.model.read` scope 而失败。
如果你要复用 Codex ChatGPT 登录态自带的联网搜索，请改走 `MODEL_SEARCH_HELPER`，
例如：`MODEL_SEARCH_HELPER=python scripts/codex_model_search_helper.py`。

推荐本地中文 ASR 服务：

```env
TRANSCRIPTION_PROVIDER=local_http_asr
TRANSCRIPTION_MODEL=qwen3-asr-1.7b-forced-aligner
LOCAL_ASR_API_BASE_URL=http://127.0.0.1:30080
LOCAL_ASR_MODEL_NAME=qwen3-asr-1.7b-forced-aligner
LOCAL_ASR_DISPLAY_NAME=Qwen3-ASR 1.7B + ForcedAligner
```

Qwen3-ASR Docker 服务使用 `Qwen/Qwen3-ASR-1.7B` 和 `Qwen/Qwen3-ForcedAligner-0.6B`，通过 `docker-compose.qwen3-asr.yml` 部署到 `roughcut` compose 项目下，并返回逐字时间戳。

如果你不走独立服务，而是想在宿主机内直接装离线依赖，再选：

```env
TRANSCRIPTION_PROVIDER=funasr
TRANSCRIPTION_MODEL=sensevoice-small
```

### 6. 运行自检

```bash
pnpm doctor
```

如果缺少 `ffmpeg`、`ffprobe` 或 Python 版本不满足要求，命令会直接失败并给出原因。

### 7. 初始化数据库

```bash
pnpm migrate
```

### 8. 本地开发

一条命令启动前端 + API + orchestrator + 两个 worker：

```bash
pnpm dev
```

默认：

- Vite 开发地址 `http://127.0.0.1:${ROUGHCUT_FRONTEND_DEV_PORT}`，默认由 `roughcut.ports.env` 定义为 `5173`
- FastAPI 地址 `http://127.0.0.1:${ROUGHCUT_API_PORT}`，默认由 `roughcut.ports.env` 定义为 `38471`

如果只想启动单个进程：

```bash
pnpm dev:web
pnpm dev:api
pnpm dev:orchestrator
pnpm dev:worker:media
pnpm dev:worker:llm
pnpm dev:worker:agent
pnpm dev:watcher
pnpm dev:telegram-agent
```

Telegram 轮询入口建议独立运行：

```bash
pnpm dev:telegram-agent
```

当前支持的远程命令：

- `/status`
- `/jobs [limit]`
- `/job <job_id>`
- `/run <claude|codex|acp> <preset> --task "..."`
- `/task <task_id> [--full]`
- `/tasks [limit]`
- `/presets`
- `/confirm <task_id>`
- `/cancel <task_id>`
- `/review [content|subtitle] <job_id> <pass|reject|note> [备注]`

当 Telegram 收到未知命令，或直接收到“修复错误 / 结构优化 / 链路优化 / 扩展命令”这类自然语言工程请求时，agent 会自动尝试分流：

- 优先走 ACP bridge
- ACP 默认优先调用 Codex，并建议使用 `gpt-5.5` low reasoning 承担工程级任务；Claude 作为后备桥接后端
- ACP/Codex prompt 会自动附带 RoughCut 项目规则和同 Telegram 会话的近期任务记忆，避免每次冷启动
- `build` preset 会在独立 git worktree 中执行构建/测试，不污染主工作树
- 如果是需要改代码的扩展类请求，会自动创建待确认任务
- 如果是分析类请求，会直接创建只读诊断任务

### 9. 构建与校验

```bash
pnpm build
pnpm lint
```

细分命令：

```bash
pnpm build:frontend
pnpm build:backend
pnpm lint:frontend
pnpm lint:backend
```

构建前端后，FastAPI 会直接托管 `frontend/dist`。

### 10. 一键本地启动（Windows）

```powershell
./start_roughcut.bat
```

Windows 下当前建议把 [start_roughcut.bat](./start_roughcut.bat) 作为用户入口：

- `start_roughcut.bat`
  默认 Docker full dev 入口。启动 `roughcut` compose 分组下的 infra + runtime + automation + dev overlay：后端源码 bind mount 并热重载，worker / orchestrator 由 `watchfiles` 自动重启，容器内 `frontend-watch` 持续更新 `frontend/dist`。端口仍统一来自 `roughcut.ports.env`
- `start_roughcut.bat rebuild`
  与默认入口相同，但显式加 `-BuildDocker` 强制重建 `roughcut:local`；改了 `Dockerfile`、`pyproject.toml`、`uv.lock`、`package.json`、`pnpm-lock.yaml` 或 Python extras 后使用
- `start_roughcut.bat local`
  旧本地开发入口。后台拉起本地 API / orchestrator / workers，同时启动 Vite 前端开发服务器；浏览器使用终端里打印的 `Frontend URL` 或 `Frontend LAN URL`
- `start_roughcut.bat infra`
  只启动 PostgreSQL / Redis / MinIO 这套轻量基础设施，供本地服务使用
- `start_roughcut.bat runtime`
  显式容器模式。启动容器化 `api + orchestrator + worker-media + worker-llm + worker-agent`；`runtime/full` 默认会带上 `docker-compose.dev.yml`，通过 bind mount + 容器内 watcher 提供 live source sync；默认不在容器里安装 `local-asr` extras
- `start_roughcut.bat runtime-local-asr`
  启动 runtime，并显式在 Docker 镜像里启用 `local-asr` extras
- `start_roughcut.bat full`
  显式容器模式。启动 runtime + automation（当前包含 `watcher`）；`runtime/full` 默认会带上 `docker-compose.dev.yml`，通过 bind mount + 容器内 watcher 提供 live source sync；默认不在容器里安装 `local-asr` extras
- `start_roughcut.bat test`
  启动默认 Docker full dev 栈后，再附加一个本地 Vite 测试端口。前端走热更新，API 仍代理到 Docker `roughcut-api-1`。适合联调全文剪辑、投影字幕和手动编辑页
- `start_roughcut.bat full-test`
  与 `test` 相同
- `start_roughcut.bat runtime-test`
  启动 Docker runtime 后附加本地 Vite 测试端口；不带 automation
- `start_roughcut.bat full-local-asr`
  启动 full stack，并显式在 Docker 镜像里启用 `local-asr` extras
- `start_roughcut.bat runtime-down`
  关闭 runtime
- `start_roughcut.bat full-down`
  关闭 runtime + automation
- `start_roughcut.bat runtime-watch`
  显式启动 host-side rebuild watch，监听 workspace 改动并自动 refresh Docker runtime；适合需要整套镜像重建的开发/维护场景，不适合重任务常驻队列
- `start_roughcut.bat full-watch`
  显式启动 host-side rebuild watch，监听 workspace 改动并自动 refresh runtime + automation
- `start_roughcut.bat install-autostart`
  注册 Windows 登录任务，开机登录后自动启动默认 Docker full dev 模式；任务不会每次强制 build
- `start_roughcut.bat uninstall-autostart`
  移除 Windows 登录任务
- `pnpm docker:runtime:auto-up`
  从根目录启动显式容器化 runtime，并自动构建重建（host-side）
- `pnpm docker:auto:auto-up`
  从根目录启动显式容器化 full（runtime + automation），并自动构建重建（host-side）
- `start_roughcut.bat dev`
  直接运行统一入口 `pnpm dev`
- `start_roughcut.bat build`
  运行 `pnpm build`

如果你已经习惯默认入口，也可以直接这样用而不记新别名：

```powershell
./start_roughcut.bat -FrontendDev
```

这会等价于 `full + 本地 Vite 测试端口`。

`start_roughcut.ps1` 是当前主脚本，也是一键启动的实际实现。

默认开发建议是把 `start_roughcut.bat` 作为 Docker full dev 入口；本地 Python 模式保留为 `start_roughcut.bat local`。运行时 core infra preflight 默认关闭，但外部 GPU ASR/TTS 服务 guard 默认开启，会在空闲后自动停掉共享容器；如需禁用，再显式设置 `DOCKER_GPU_GUARD_ENABLED=false`。只有显式设置 `RUNTIME_PREFLIGHT_DOCKER_ENABLED=true` 时，RoughCut 才会自动管理 PostgreSQL / Redis / MinIO 这类 core infra 容器。`pnpm docker:up/down` 现在只作为 `infra` 快捷别名保留。

---

## Docker 部署

仓库现在推荐把 Docker 拆成三层，而不是继续只用一个全量 compose：

- `docker-compose.infra.yml`
  只放 `postgres` / `redis`
- `docker-compose.runtime.yml`
  放推荐常驻的 `migrate` / `api` / `orchestrator` / `worker-media` / `worker-llm` / `worker-agent`
- `docker-compose.automation.yml`
  放可选自动化服务，当前第一版只包含 `watcher`

### 1. 准备配置

```bash
cp .env.example .env
```

在 `.env` 中填写你的模型配置和 API Key。容器内的 PostgreSQL / Redis 地址由 runtime / automation compose 自动覆盖为容器服务名，无需手动改成 `postgres` / `redis`。

### 2. 构建并启动

最低成本常驻（只起基础设施）：

```bash
docker compose --env-file roughcut.ports.env -f docker-compose.infra.yml up -d
```

推荐常驻开发（基础设施 + Docker runtime，默认 live source sync）：

```bash
pnpm docker:dev:up
```

强制重建镜像后启动：

```bash
pnpm docker:dev:rebuild
```

等价的完整 compose 命令：

```bash
docker compose --env-file roughcut.ports.env -f docker-compose.infra.yml -f docker-compose.runtime.yml -f docker-compose.automation.yml -f docker-compose.dev.yml up -d
```

推荐常驻默认包含：

- `api`：FastAPI + 内置静态面板，访问 `http://localhost:${ROUGHCUT_API_PORT}`；容器内部监听端口为 `ROUGHCUT_API_INTERNAL_PORT`
- `orchestrator`
- `worker-media`
- `worker-llm`
- `worker-agent`
- `postgres`
- `redis`

全自动无人值守额外包含：

- `watcher`

### 3. 查看日志

```bash
docker compose --env-file roughcut.ports.env -f docker-compose.infra.yml -f docker-compose.runtime.yml logs -f api
docker compose --env-file roughcut.ports.env -f docker-compose.infra.yml -f docker-compose.runtime.yml logs -f orchestrator
docker compose --env-file roughcut.ports.env -f docker-compose.infra.yml -f docker-compose.runtime.yml logs -f worker-media
```

### 3.5 Docker 开发态自动同步 workspace 改动

RoughCut 现在保留两种明确分离的代码同步模式：

- 容器默认同步模式：`runtime/full` 自动带上 `docker-compose.dev.yml`，通过 bind mount + 容器内 watcher 提供 live source sync。
- 显式重建模式：`runtime-watch/full-watch` 使用 host-side rebuild watch，在宿主机监听改动后触发一次 Docker refresh。

`docker-compose.dev.yml` 当前负责：

- 把 `./src` 挂到 `/app/src`
- 把 `./frontend/dist` 挂到 `/app/frontend/dist`
- 让 `api` 使用 `--reload`
- 让 `orchestrator` / `worker-*` 使用 `watchfiles`
- 启动 `frontend-watch` 持续构建前端产物

host-side rebuild watch 仍由两层脚本提供：

- `scripts/run-roughcut-docker-refresh-session.ps1`
  单次执行 `docker compose up -d --build --force-recreate`，只重建 `migrate / api / orchestrator / worker-media / worker-llm / worker-agent`，不会主动重建 `postgres / redis`
- `scripts/watch-roughcut-docker-runtime.ps1`
  持续监听 `src/`、`frontend/`、`scripts/`、compose、`Dockerfile`、`pyproject.toml`、`uv.lock` 等改动，debounce 后触发 refresh

常用命令：

```bash
pnpm docker:runtime:up
pnpm docker:runtime:watch
pnpm docker:runtime:auto-up
pnpm docker:runtime:up:local-asr
pnpm docker:runtime:watch:local-asr
pnpm docker:auto:watch
pnpm docker:auto:auto-up
pnpm docker:auto:up:local-asr
```

如果你明确要跑容器化 runtime，显式 Docker 启停入口直接走 live source sync：

```bash
pnpm docker:runtime:up
pnpm docker:runtime:down
pnpm docker:auto:up
pnpm docker:auto:down
```

如果你需要显式 host-side rebuild watch，使用：

```powershell
./start_roughcut.bat runtime-watch
./start_roughcut.bat full-watch
```

如果你要把“启动 + 自动重建”合并为一条命令，可直接用：

```bash
pnpm docker:runtime:auto-up
pnpm docker:auto:auto-up
```

host-side rebuild watch 方案和 Hydra 的差别是：

- Hydra 需要同步 runtime home / SQLite 状态
- RoughCut 不需要同步 runtime home，因为状态真相在 PostgreSQL / Redis 和宿主机输出目录
- RoughCut 的 watch 主要负责“代码变了就重建并重启 runtime 容器”

注意：

- 日常开发优先走本地 Python + 本地前端；Docker 更适合基础依赖、部署验证和显式容器化运行
- `runtime/full` 仍保留，但属于显式容器模式，不再作为默认开发入口
- `runtime-watch/full-watch` 更适合你明确需要整套镜像重建的场景，但不适合正在跑重任务的稳定常驻队列
- host-side rebuild watch 每次命中改动都会重建并 `force-recreate` `api / orchestrator / workers`
- `data/`、`logs/`、`watch/`、`.venv/`、`node_modules/`、`docs/` 默认不会触发 host-side rebuild refresh

### 4. 数据目录

- `./data/runtime/jobs`：任务运行期文件与中间产物
- `./data/runtime/output`：成片输出
- `./data/runtime/cache`：RoughCut 本地缓存（如启用）
- `./data/runtime/render-debug`：render 诊断目录
- `./data/runtime/tools`：百宝箱工具历史、TTS/ASR 输出与参考上传历史
- `./data/runtime/voice_refs`：旧版语音参考文件
- `./data/runtime/voice`：RoughCut 自有语音任务数据
- `./data/runtime/content_profile_review_stats.json`：创作配置自动审校统计
- `HEYGEM_SHARED_ROOT`：HeyGem 公共服务输入 / temp / result 的共享目录，不属于 RoughCut 私有数据迁移范围
- `./watch`：可选目录监听挂载点（启用 automation compose 时使用）

  ### 5. 说明
  
- Docker 镜像默认内置 `uv`、`ffmpeg` 和 `Noto Sans CJK` 中文字体。
- Docker 镜像会在构建阶段自动执行 `frontend/` 下的前端依赖安装和构建。
- 默认 Docker 入口会强制清空 `ROUGHCUT_DOCKER_PYTHON_EXTRAS`，优先走更轻的 runtime 构建；如果你确实要在容器内启用 `funasr` / `faster-whisper`，使用 `pnpm docker:runtime:up:local-asr`、`pnpm docker:auto:up:local-asr`，或显式传 `-DockerPythonExtras local-asr`。
- 当前项目默认 ASR 方案为 `local_http_asr + qwen3-asr-1.7b-forced-aligner`，具体本地模型通过 `LOCAL_ASR_MODEL_NAME` 和 `LOCAL_ASR_API_BASE_URL` 配置；当前默认指向 `Qwen3-ASR 1.7B + ForcedAligner`。离线本地依赖可选 `funasr + sensevoice-small` 或 `faster_whisper`，云端可切回 `openai + gpt-4o-transcribe`。
  - 推荐把长期在线形态收敛到 `infra + runtime` 这一档；`watcher` 只在确实需要自动扫盘时再加入。
- 推荐本地开发使用 `uv + npm`，容器部署使用 `docker compose`，不要混用系统级 `pip` 和容器内运行时配置。

---

## API 使用

### 上传视频

```bash
curl -X POST "${ROUGHCUT_API_BASE:-http://localhost:38471/api/v1}/jobs" \
  -F "file=@video.mov"
```

返回 `job_id`。

### 查询进度

```bash
curl "${ROUGHCUT_API_BASE:-http://localhost:38471/api/v1}/jobs/{job_id}"
```

返回各步骤状态（pending / running / done / failed）。

### 下载成片

```bash
curl "${ROUGHCUT_API_BASE:-http://localhost:38471/api/v1}/jobs/{job_id}/download" -o output.mp4
```

### 术语词表管理

```bash
# 添加术语
curl -X POST "${ROUGHCUT_API_BASE:-http://localhost:38471/api/v1}/glossary" \
  -H "Content-Type: application/json" \
  -d '{"wrong_forms": ["苹果手机", "爱疯"], "correct_form": "iPhone", "category": "brand"}'

# 查询所有术语
curl "${ROUGHCUT_API_BASE:-http://localhost:38471/api/v1}/glossary"
```

### 审校报告

```bash
curl "${ROUGHCUT_API_BASE:-http://localhost:38471/api/v1}/jobs/{job_id}/report"
```

---

## 配置说明

所有配置项通过 `.env` 文件或环境变量设置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `JOB_STORAGE_DIR` | `./data/runtime/jobs` | 任务运行期文件根目录 |
| `OUTPUT_DIR` | `./data/runtime/output` | 成片输出目录 |
| `OUTPUT_NAME_PATTERN` | `{date}_{stem}` | 输出文件名模板 |
| `RENDER_DEBUG_DIR` | `./data/runtime/render-debug` | render 调试产物目录 |
| `REASONING_PROVIDER` | `minimax` | 推理后端：`openai` / `anthropic` / `minimax` / `zhipu` / `ollama` |
| `REASONING_MODEL` | `MiniMax-M2.7` | 推理模型名称 |
| `REASONING_EFFORT` | `low` | 推理强度默认值 |
| `MULTIMODAL_FALLBACK_PROVIDER` | `minimax` | 主模型视觉失败时的备份 provider |
| `MULTIMODAL_FALLBACK_MODEL` | `MiniMax-M2.7` | 主模型视觉失败时的备份视觉/多模态模型 |
| `SEARCH_PROVIDER` | `minimax` | 搜索后端；默认使用 MiniMax Coding Plan / MCP 搜索 |
| `SEARCH_FALLBACK_PROVIDER` | `minimax` | 主模型搜索失败时的兜底搜索后端 |
| `MODEL_SEARCH_HELPER` | `""` | 本地模型搜索桥接命令；MiniMax MCP 搜索默认不需要 Codex helper |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI/Codex 兼容接口地址 |
| `OPENAI_AUTH_MODE` | `api_key` | `api_key` / `helper` |
| `OPENAI_API_KEY_HELPER` | `""` | helper 模式下返回 OpenAI Platform API key 的本地命令；不要把 ChatGPT access token 直接当作 Platform search API 凭证 |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Anthropic/Claude Code 兼容接口地址 |
| `ANTHROPIC_AUTH_MODE` | `api_key` | `api_key` / `helper` |
| `ANTHROPIC_API_KEY_HELPER` | `""` | helper 模式下返回凭证的本地命令 |
| `MINIMAX_API_KEY` | `""` | MiniMax 普通推理 API Key（OpenAI 兼容） |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.com/v1` | MiniMax OpenAI 兼容接口地址 |
| `MINIMAX_API_HOST` | `https://api.minimaxi.com` | MiniMax Coding Plan / MCP API Host |
| `MINIMAX_CODING_PLAN_API_KEY` | `""` | MiniMax Coding Plan Key；留空时搜索/MCP 默认回退 `MINIMAX_API_KEY` |
| `ZHIPU_API_KEY` | `""` | 智谱 API Key |
| `ZHIPU_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | 智谱 GLM 推理 / 多模态 / 网页读取接口地址 |
| `ZHIPU_CODING_BASE_URL` | `https://open.bigmodel.cn/api/coding/paas/v4` | 智谱 Coding Plan 接口地址 |
| `ZHIPU_MCP_HTTP_BASE_URL` | `https://open.bigmodel.cn/api/mcp` | 智谱 MCP HTTP 服务根地址 |
| `ZHIPU_SEARCH_ENGINE` | `search_pro` | 智谱联网搜索引擎档位 |
| `VISION_MODEL` | `""` | 视觉模型（空 = 使用 reasoning_model） |
| `TRANSCRIPTION_PROVIDER` | `local_http_asr` | 转写后端：`local_http_asr` / `openai` / `funasr` / `faster_whisper` |
| `TRANSCRIPTION_MODEL` | `qwen3-asr-1.7b-forced-aligner` | 转写模型占位符；本地 HTTP ASR 的实际模型由 `LOCAL_ASR_MODEL_NAME` 决定 |
| `LOCAL_ASR_API_BASE_URL` | `http://127.0.0.1:30080` | 本地 HTTP ASR 服务地址 |
| `LOCAL_ASR_MODEL_NAME` | `qwen3-asr-1.7b-forced-aligner` | 当前本地 HTTP ASR 实际模型名 |
| `LOCAL_ASR_DISPLAY_NAME` | `Qwen3-ASR 1.7B + ForcedAligner` | 前端显示名称 |
| `RUNTIME_PREFLIGHT_DOCKER_ENABLED` | `false` | 是否允许运行时 preflight 自动启动 Docker 中的 PostgreSQL / Redis |
| `DOCKER_GPU_GUARD_ENABLED` | `true` | 是否允许外部 GPU 服务 guard 自动启动并在空闲后停掉共享 ASR / TTS / 数字人 Docker 服务 |
| `SUBTITLE_FONT` | `Microsoft YaHei` | 字幕字体 |
| `SUBTITLE_FONT_SIZE` | `80` | 字幕字号（pt，相对 PlayResY） |
| `SUBTITLE_COLOR` | `000000` | 字幕文字颜色（RGB hex，黑色） |
| `SUBTITLE_OUTLINE_COLOR` | `00FF00` | 字幕描边颜色（RGB hex，荧光绿） |
| `SUBTITLE_OUTLINE_WIDTH` | `5` | 描边宽度 |
| `COVER_CANDIDATE_COUNT` | `10` | 封面候选帧数量 |
| `COVER_TITLE` | `""` | 封面叠加标题（空 = 不叠加） |
| `FFMPEG_TIMEOUT_SEC` | `600` | FFmpeg 单次执行超时（秒） |
| `MAX_UPLOAD_SIZE_MB` | `2048` | 上传文件大小上限（MB） |
| `TELEGRAM_AGENT_ENABLED` | `false` | 启用独立 Telegram agent；建议与 `roughcut telegram-agent` 独立进程一起使用 |
| `TELEGRAM_AGENT_CLAUDE_ENABLED` | `false` | 允许 Telegram agent 调用本机 Claude Code CLI |
| `TELEGRAM_AGENT_CLAUDE_COMMAND` | `claude` | Claude Code CLI 命令名 |
| `TELEGRAM_AGENT_CLAUDE_MODEL` | `opus` | Claude Code CLI 模型名；为空则使用 Claude 默认模型 |
| `TELEGRAM_AGENT_CODEX_COMMAND` | `codex` | Codex CLI 命令名；用于 `/run codex ...` 或 ACP `codex` backend |
| `TELEGRAM_AGENT_ACP_COMMAND` | `""` | 外部 ACP bridge 命令；Telegram agent 会通过 stdin 发送 JSON 负载 |
| `TELEGRAM_AGENT_TASK_TIMEOUT_SEC` | `900` | Telegram agent 异步任务超时 |
| `TELEGRAM_AGENT_RESULT_MAX_CHARS` | `3500` | Telegram 回推结果摘要最大字符数 |
| `TELEGRAM_AGENT_STATE_DIR` | `./data/runtime/telegram-agent` | Telegram agent 本地任务状态文件目录 |
| `FACT_CHECK_ENABLED` | `false` | 事实核验开关（Phase 2） |

如果要直接启用仓库内置的 ACP bridge，推荐配置：

```env
TELEGRAM_AGENT_ACP_COMMAND=uv run python scripts/acp_bridge.py
ROUGHCUT_ACP_BRIDGE_BACKEND=claude
ROUGHCUT_ACP_BRIDGE_FALLBACK_BACKEND=codex
TELEGRAM_AGENT_CLAUDE_MODEL=opus
ROUGHCUT_ACP_BRIDGE_CLAUDE_MODEL=opus
ROUGHCUT_ACP_BRIDGE_CODEX_COMMAND=codex
ROUGHCUT_ACP_BRIDGE_CODEX_MODEL=gpt-5.4-mini
```

如果要让内置 ACP bridge 改走 Codex，可以改成：

```env
TELEGRAM_AGENT_ACP_COMMAND=uv run python scripts/acp_bridge.py
ROUGHCUT_ACP_BRIDGE_BACKEND=codex
ROUGHCUT_ACP_BRIDGE_CODEX_COMMAND=codex
ROUGHCUT_ACP_BRIDGE_CODEX_MODEL=gpt-5.4-mini
```

如果不显式配置 `TELEGRAM_AGENT_ACP_COMMAND`，Telegram agent 也会默认回退到仓库内置的 `scripts/acp_bridge.py`。
当前推荐链路是：ACP 主走 Claude Code `opus`，失败时自动 fallback 到 Codex `gpt-5.4-mini` low reasoning。
| `AUTO_CONFIRM_CONTENT_PROFILE` | `true` | 高置信度内容摘要自动确认，避免任务卡在人工核对 |
| `CONTENT_PROFILE_REVIEW_THRESHOLD` | `0.72` | 内容摘要自动确认阈值，范围 `0.0` 到 `1.0` |
| `AUTO_ACCEPT_GLOSSARY_CORRECTIONS` | `true` | 高置信度术语纠错自动接受，只保留风险项待确认 |
| `GLOSSARY_CORRECTION_REVIEW_THRESHOLD` | `0.9` | 术语纠错自动接受阈值，范围 `0.0` 到 `1.0` |
| `AUTO_SELECT_COVER_VARIANT` | `true` | 自动选择首选封面，默认只在候选分差接近时提醒确认 |
| `COVER_SELECTION_REVIEW_GAP` | `0.08` | 首选封面与次优封面的最小安全分差，范围 `0.0` 到 `1.0` |
| `INTELLIGENT_COPY_COVER_IMAGE_GENERATION_ENABLED` | `true` | 智能发布封面必须完成图像生成；未完成时物料不可发布，不生成兜底封面 |
| `INTELLIGENT_COPY_COVER_IMAGE_BACKEND` | `codex_builtin` | 封面图像后端；默认是 Codex 内置 imagegen 请求清单，显式设为 `openai_images_api` 才走直接 Images API 后端 |
| `INTELLIGENT_COPY_COVER_IMAGE_MODEL` | `image2` | 直接 Images API 后端使用的图像编辑模型；Codex 内置路径不依赖这个 API 参数 |
| `INTELLIGENT_COPY_COVER_IMAGE_QUALITY` | `medium` | 直接 Images API 后端使用的图像编辑质量 |
| `INTELLIGENT_COPY_COVER_IMAGE_TIMEOUT_SEC` | `90` | 智能发布单张封面图像编辑超时（秒） |
| `INTELLIGENT_COPY_COVER_CODEX_RUNNER_MODEL` | `gpt-5.4-mini` | Codex 内置路径的执行代理模型；只负责理解请求、调用 `image_gen`、保存文件，不是底层图像模型 |
| `INTELLIGENT_COPY_COVER_CODEX_RUNNER_EFFORT` | `low` | Codex 内置路径的执行代理推理强度；默认低推理即可，画质优先通过 prompt contract / QC / 重试策略提升 |
| `PUBLICATION_BROWSER_AGENT_BASE_URL` | `http://127.0.0.1:49310` | 浏览器平台发布 agent 健康探针与执行入口；YouTube/X 默认不再走浏览器 agent |
| `PUBLICATION_BROWSER_AGENT_TIMEOUT_SEC` | `60` | 与浏览器发布 agent 通信超时（秒） |
| `PUBLICATION_BROWSER_CDP_URL` | `http://127.0.0.1:9222` | 连接已打开的 Chrome/Edge 远程调试端口 |
| `PUBLICATION_BROWSER` | `chrome` | 发布时要绑定的浏览器类型标识 |
| `PUBLICATION_BROWSER_USER_DATA_DIR` | - | 固定发布 profile 的 Chrome/Edge `User Data` 目录 |
| `PUBLICATION_BROWSER_PROFILE_DIRECTORY` | - | 固定发布 profile 子目录名（如 `Profile 1`） |
| `PUBLICATION_BROWSER_ALLOW_TAB_AUTOCREATE` | `false` | 关闭时要求任务前该平台发布页已在当前 CDP 会话中打开 |
| `PUBLICATION_BROWSER_AGENT_AUTH_TOKEN` | - | 访问发布 agent 的可选 token |
| `PUBLICATION_YOUTUBE_TOKEN_FILE` | - | YouTube Data API OAuth token JSON；YouTube 发布、封面、播放列表和定时发布均走该 API |
| `PUBLICATION_YOUTUBE_DEFAULT_CATEGORY_ID` | `22` | YouTube 未提供数字分类时使用的默认 categoryId |
| `PUBLICATION_X_API_KEY` | - | X API Key；X 转发/发帖走 Tweepy，不再走浏览器 |
| `PUBLICATION_X_API_SECRET` | - | X API Secret |
| `PUBLICATION_X_ACCESS_TOKEN` | - | X Access Token |
| `PUBLICATION_X_ACCESS_TOKEN_SECRET` | - | X Access Token Secret |
| `PUBLICATION_X_USERNAME` | - | X 用户名，用于生成发布回执 URL |
| `PACKAGING_ASSET_DIR` | `assets/packaging` | 包装素材持久目录；不要放在输出目录，避免清理成片时误删 BGM/水印/片头片尾 |
| `PACKAGING_ASSET_STORAGE_BACKEND` | `local` | 包装素材后端，当前为本地目录；预留给后续 OSS 热切换 |
| `PACKAGING_SELECTION_REVIEW_GAP` | `0.08` | BGM/插入素材首选与次优的最小安全分差，过近时建议确认 |
| `PACKAGING_SELECTION_MIN_SCORE` | `0.6` | BGM/插入素材最低自动通过分，低于该值建议确认 |

### 浏览器发布代理启动建议

- 浏览器先行登录，使用固定 profile。
- 不要再手写一整串 Chrome 启动参数，`User Data` / `Profile 2` 这种带空格值一旦拆参，就会额外打开 `data/`、`0.0.0.2` 之类的废页面。
- 推荐统一走仓库脚本：

```powershell
powershell -File .\scripts\start_publication_browser_session.ps1 `
  -UserDataDir "<your Chrome User Data directory>" `
  -ProfileDirectory "<your Chrome profile directory>"
```

- 如果是即梦生图 fallback 的独立 profile，再显式换成那套目录，不要和发布 profile 混用。

- 建议统一走仓库脚本启动 `publication-browser-agent`，不要再手写 `pwsh -Command` 拼环境变量：

```powershell
powershell -File .\scripts\start_publication_browser_agent.ps1 `
  -UserDataDir "<your Chrome User Data directory>" `
  -ProfileDirectory "<your Chrome profile directory>" `
  -EnableLivePublish `
  -StopExisting
```

- 根因说明：如果用手写的 `pwsh -Command` 串接 `$env:` 赋值，值里一旦有空格或变量名被拼坏，agent 子进程会直接丢失 `PUBLICATION_LIVE_PUBLISH_ENABLED` / profile 绑定信息，健康探针会退化成 `live_publish=false`、`attached_profile_binding=null`。
- 默认 `PUBLICATION_BROWSER_ALLOW_TAB_AUTOCREATE=false`，避免 agent 在错误 profile 下偷偷补开新页面。

浏览器平台发布任务开始前请先在该会话中手动打开对应平台发布页（例如抖音/小红书/B站发布页），否则后台会返回 `platform_tab_autocreate_disabled` 提示并阻止直接摸底发布。YouTube 默认走 YouTube Data API，X 默认走 Tweepy/X API，不需要也不应要求打开浏览器发布页。

统一发布前置检查命令（用于每次正式发布前复用）：

```bash
pnpm run publication:preflight
pnpm run publication:preflight:json   # 输出 artifacts/publication-preflight.json
```

该命令会同时校验：
- browser-agent 的能力与生效 profile 是否可复用；
- CDP 是否可连通、目标发布页 tab 是否存在；
- 返回标准化诊断结果（`ready` + `cdp_connected` + 各平台 tab 命中状态），便于复用到 CI/脚本。

如果你要把“正式发布前置网关”做成一条可复用链路，建议使用：

```bash
pnpm run publication:release-gate
pnpm run publication:release-gate:dry   # 只做 preflight，不做后端发布合同烟测
pnpm run publication:release-gate:real --media-path <你的本地视频路径>  # 进入真实发布执行链路校验
```

`publication:release-gate` 的通过标准（用于“发布前置可复用条件”）：
- 1）`browser-agent` 健康探针与能力检查 `ready=true`；
- 2）`cdp_connected=true`；
- 3）按 `--require-tabs` 时，所有目标平台的发布页 tab 都命中（`found`）；
- 4）后端发布合同烟测通过（`backend_contract_smoke.status=passed`，`created_attempts` 等于目标平台数）。

这不是“直接发真实平台”，而是“在可复用的前置条件下，保证发布链路在同一套约束下可复现且可判定”。

建议再补一层“发布成功语义回归”用于 CI/里程碑门禁（仍不触发真实发布）：

```bash
pnpm run publication:release-gate:published
```

它把后端合同烟测的预期终态提升为 `published`，用于验证“发布任务流”合约能把状态推进到发布成功语义；如果你要验证真实平台发帖成功，需要把 `publication_attempts` 运行态回表/日志与平台侧可见性对齐后人工复核。

`publication:release-gate:real` 用于“真实执行闭环验收”（会触发真实 publication attempt）：
- 需要传入真实本地视频文件 `--media-path`；
- 会先复用 `preflight` 能力校验；
- 构造临时 `Job + 发布计划 + publication attempts` ；
- 跑 worker 并轮询到目标状态（默认为 `published`）；
- 默认不设置 `visibility_or_publish_mode`，交给平台默认发布行为（通常对应公开发布）；如需仅验证流程可加 `--visibility-mode draft` 或 `--visibility-mode private` 并配套 `--expected-status`；
- 输出中会包含每个平台 attempt 最新状态、provider 回执、`provider_task_id`、`external_post_id/external_url`，用于你做最终人工/平台侧复核。

草稿链路示例（仅验证 workflow，不会走公开发布）：

```bash
pnpm run publication:release-gate:real --media-path ./assets/sample.mp4 --visibility-mode draft --expected-status draft_created
```

### 多适配器自动化发布闭环（autopilot）

如果你要把“环境检查→合同验收→真实执行→失败自动诊断→建议修复方案”做成一条统一动作，使用：

```bash
pnpm run publication:autopilot \
  --media-path ./assets/sample.mp4 \
  --platform-packaging ./artifacts/platform-packaging.json \
  --material-json ./smart-copy/smart-copy.json \
  --platform douyin --platform x \
  --target-profile-id <fas_profile_id> \
  --platform-adapter x=x_link_share \
  --platform-execution-mode x=link_share \
  --auto-retry --retry-cycles 2
```

`autopilot` 自动按以下策略运行：

- 先执行 `material_gate`；要求存在 `smart-copy.json` 里的 `material_contract`，且目标平台 `one_click_publish_ready=true`，否则不会进入真实发布。
- `stable-primary`：先跑稳定平台（douyin/小红书/B 站/快手/头条/YouTube）；
- `x-post`：再按 `x-mode` 处理 X（默认 `link_share`，会使用 `x_link_share`）；
- 每一阶段会串联 `preflight`、`release-gate`（默认开启）和 `real-release-gate`；
- 每一轮会附带 `mitigation.steps`（快速处理建议）和 `mitigation.playbook`（可执行建议映射）；
- 失败知识会追加入 `artifacts/publication-autopilot/publication-autopilot-knowledge.json`。

`autopilot` 覆盖两类关键参数：

- `--platform-adapter platform=adapter`，支持例如 `x=x_link_share`；
- `--platform-execution-mode platform=mode`，支持例如 `x=link_share` / `x=video`。

更多适配器矩阵、错误信号与故障固化流程见：[publication-adapter-autopilot-runbook.md](docs/publication-adapter-autopilot-runbook.md)。

---

## 项目结构

```
src/roughcut/
├── main.py              # FastAPI 应用入口
├── config.py            # 配置（Pydantic Settings）
├── cli.py               # CLI 入口（roughcut 命令）
├── db/                  # 数据库模型 + Alembic 迁移
├── api/                 # REST API 路由
├── providers/           # LLM/转写后端抽象层
│   ├── transcription/   # OpenAI / FunASR / local faster-whisper
│   ├── reasoning/       # OpenAI / Anthropic / Ollama
│   └── factory.py       # 按配置实例化 provider
├── media/               # 媒体处理
│   ├── probe.py         # 视频元数据探针
│   ├── audio.py         # 音频提取
│   ├── silence.py       # 静音检测（webrtcvad）
│   ├── rotation.py      # 视觉模型旋转检测
│   ├── subtitles.py     # ASS 字幕生成 + 时间轴重映射
│   ├── render.py        # FFmpeg 渲染
│   └── output.py        # 封面选帧 + 输出命名
├── speech/              # 转写 + 字幕后处理（断句、标点）
├── review/              # 术语匹配引擎 + 审校报告
├── edit/                # 剪辑决策 + 时间轴模型
├── pipeline/            # Celery 任务 + Orchestrator 状态机
├── watcher/             # 目录监听进程
└── storage/             # 宿主机文件系统任务存储层
```

---

## 数据库

主要数据表：

| 表名 | 用途 |
|------|------|
| `jobs` | 任务主记录，含状态和来源信息 |
| `job_steps` | 每步骤状态，支持重试和断点续跑 |
| `artifacts` | 步骤产物（路径或 JSON 数据） |
| `transcript_segments` | 转写段落（含词级时间戳） |
| `subtitle_items` | 字幕条目（断句后的展示单元） |
| `subtitle_corrections` | 术语纠错建议 |
| `timelines` | 剪辑时间轴 + 渲染计划 |
| `glossary_terms` | 术语词表 |
| `watch_roots` | 监控目录配置 |
| `fact_claims` | 事实断言（Phase 2 预留） |

---

## Phase 2 预留

以下功能已预留接口，默认关闭（`FACT_CHECK_ENABLED=false`）：

- 事实断言提取（`review/claims.py`）
- SearXNG 联网核验（`providers/search/`）
- 证据面板 Review UI

---

## 开发

```bash
# 初始化依赖
pnpm bootstrap

# 启动全套本地开发
pnpm dev

# 前端构建
pnpm build

# 后端 lint
pnpm lint:backend
```

### 项目改名或目录迁移后的环境修复

如果你把仓库从 `FastCut` 改名为 `RoughCut`，或直接移动了项目目录，记得重新安装 editable package。否则虚拟环境里的 `.pth` 和本地缓存可能仍指向旧路径，表现为：

- `ModuleNotFoundError: No module named 'roughcut'`
- 报错路径仍显示旧目录，例如 `C:/sample-workspace/OldProject/...`

建议执行：

```bash
python -m pip uninstall -y fastcut roughcut
python -m pip install -e ".[dev]"
```

如果路径仍命中旧目录，再清理缓存后重跑：

```bash
# Windows
for /d /r %d in (__pycache__) do @if exist "%d" rd /s /q "%d"

# Linux / macOS
find . -type d -name "__pycache__" -prune -exec rm -rf {} +
```

---

## 渲染排查

当 render 遇到旋转、任务文件路径或 ffmpeg 参数问题时，可直接查看：

- `./data/runtime/render-debug/{job_id}_{output_name}/source.integrity.json`：下载源文件 SHA-256 校验
- `./data/runtime/render-debug/{job_id}_{output_name}/source.ffprobe.json`：下载源文件的 ffprobe 结果
- `./data/runtime/render-debug/{job_id}_{output_name}/render.ffmpeg.txt`：完整渲染命令
- `./data/runtime/render-debug/{job_id}_{output_name}/strip.ffmpeg.txt` / `normalize.ffmpeg.txt`：旋转归一化命令
- `./data/runtime/render-debug/{job_id}_{output_name}/*.stderr.log`：对应 ffmpeg stderr 输出

---

## Provider 兼容说明

- `MiniMax` 已按官方 OpenAI 兼容接口接入，可直接作为 `reasoning_provider=minimax` 使用。
- `智谱` 已接入 `glm-5.1` 文本推理、`glm-4.6v-flash` 视觉、多结果 `web_search` 与 `reader` 网页读取；同时补充了 `web_search_prime` / `web_reader` / `zread` / `@z_ai/mcp-server` 的 MCP 配置导出。
- `Claude Code` 与 `Codex` 目前在本项目中采用 helper 凭证模式而不是浏览器内第三方 OAuth 回跳。
- helper 凭证模式的含义：你可以切到 `helper`，并配置一个本地 helper 命令，让 RoughCut 在调用模型前获取当前凭证。
- 如果 OpenAI helper 输出的是 `~/.codex/auth.json` 中的 ChatGPT access token，而不是实际 OpenAI Platform API key，
  则不能直接用它调用 OpenAI `/v1/models` 或 `Responses API` 搜索；当前实测分别会报缺少 `api.model.read` 与 `api.responses.write` scope。
- 如果要恢复使用 Codex ChatGPT 登录态自带的搜索能力，请改用 `SEARCH_FALLBACK_PROVIDER=model`
  和 `MODEL_SEARCH_HELPER=python scripts/codex_model_search_helper.py`，让 RoughCut 通过 `codex exec` 本体联网搜索。
- 多模态链路现在默认“主模型优先，本地 Ollama 兜底”。主体识别、封面选帧、旋转判断优先走当前主模型视觉能力。
- 联网搜索链路现在默认 `SEARCH_PROVIDER=auto`。如果配置了 `MODEL_SEARCH_HELPER`，会优先走主模型搜索/MCP；失败后回退到 `SearXNG`。
