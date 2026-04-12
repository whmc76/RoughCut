# RoughCut

面向口播/开箱视频的自动剪辑 + 字幕审校系统。

上传原始视频后，流水线自动完成：转写 → 术语纠错 → 静音/语气词剪辑 → 字幕烧录 → 渲染输出，每个任务产出一组成片文件：`{YYYYMMDD}_{文件名}.mp4` + `.srt` + `_cover.jpg`。

---

## 功能

- **自动剪辑** — 检测静音段和语气词，生成剪辑时间轴，保留有效内容
- **转写** — 默认使用 OpenAI `gpt-4o-transcribe`，本地服务优先建议 `qwen3_asr`；离线本地依赖可选 `FunASR SenseVoice` 或 `faster-whisper`
- **字幕** — 字幕时间戳重映射至剪辑后时间轴，烧录荧光描边样式（黑字 + 绿色发光）
- **封面选帧** — 视觉模型从多个候选帧中挑选最佳封面，可选标题文字叠加
- **旋转修正** — 视觉模型识别实际画面方向，正确处理 iPhone 横屏/竖屏及错误元数据
- **渲染诊断** — 每次 render 落盘保存源文件哈希校验、ffprobe 结果、完整 ffmpeg 命令与 stderr 日志，便于手动复现
- **术语纠错** — 维护品牌/型号词表，自动匹配并标注疑似错误
- **断点续跑** — 每步骤状态持久化在数据库，进程崩溃后可从中断处继续
- **目录监听** — 监听指定文件夹，新视频自动入队处理
- **多 LLM 后端** — MiniMax / OpenAI / Anthropic / Ollama 可配置切换

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

后台仍由 4 个长期进程推进任务，通过数据库协调状态：

```
orchestrator — 状态机，轮询 job_steps 推进流水线
worker-media — FFmpeg 媒体处理（Celery）
worker-llm   — 转写后处理 / LLM 推理（Celery）
watcher      — 目录监听，自动入队
```

流水线步骤顺序：

```
probe → extract_audio → transcribe → subtitle_postprocess
      → content_profile → summary_review → glossary_review
      → edit_plan → render → platform_package
```

---

## 环境要求

- Python 3.11+
- `pnpm`
- `uv`（项目内部 Python 依赖与 CLI 仍使用它）
- FFmpeg（需在 PATH 中，支持 libx264 / libass；如需硬编码，可额外启用 h264_qsv / h264_amf / h264_nvenc）
- Docker / Docker Compose（推荐用于基础服务或完整部署）
- LLM 后端之一：MiniMax API Key、Ollama（本地）或 OpenAI API Key

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

- `F:/roughcut_outputs/output`
- `F:/roughcut_outputs/render-debug`
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

- `http://127.0.0.1:38471/`

数字人相关服务现在默认走独立共享服务，不再依赖 RoughCut 内部 Docker：

- HeyGem: `http://127.0.0.1:49202`
- IndexTTS2 accel 主实例: `http://127.0.0.1:49204`
- HeyGem 数据根: `F:/roughcut_outputs/heygem`
- 参考音频缓存目录: `F:/roughcut_outputs/voice_refs`

### 5. 配置环境变量

复制 `.env.example` 为 `.env` 并按需修改：

```bash
cp .env.example .env
```

最小配置（本地 Ollama + 本地 ASR 服务）：

```env
REASONING_PROVIDER=ollama
REASONING_MODEL=qwen3.5:9b        # 需支持视觉
TRANSCRIPTION_PROVIDER=qwen3_asr
TRANSCRIPTION_MODEL=qwen3-asr-1.7b

ROUGHCUT_OUTPUT_ROOT=F:/roughcut_outputs
JOB_STORAGE_DIR=F:/roughcut_outputs/jobs
OUTPUT_DIR=F:/roughcut_outputs/output
RENDER_DEBUG_DIR=F:/roughcut_outputs/render-debug
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
HEYGEM_SHARED_ROOT=F:/roughcut_outputs/heygem
HEYGEM_VOICE_ROOT=F:/roughcut_outputs/voice_refs
QWEN_ASR_API_BASE_URL=http://127.0.0.1:18096
VOICE_PROVIDER=indextts2
VOICE_CLONE_API_BASE_URL=http://127.0.0.1:49204
```

`RENDER_VIDEO_ENCODER` 当前支持 `auto`、`libx264`、`h264_qsv`、`h264_amf`、`h264_nvenc`。`auto` 会优先选择 Intel `QSV` 或 AMD `AMF` 这类集显编码方案，只有集显不可用时才回退到 `NVENC`，最后才是 `libx264`。

其中 `49204` 当前约定为独立 `IndexTTS2 accel` 正式入口。不要再并行常驻 `baseline / sage / accel` 多个实例去争抢同一块 GPU。

MiniMax 默认配置：

```env
MINIMAX_API_KEY=sk-...
REASONING_PROVIDER=minimax
REASONING_MODEL=MiniMax-M2.7
```

OpenAI 兼容替代配置：

```env
OPENAI_API_KEY=sk-...
REASONING_PROVIDER=openai
REASONING_MODEL=gpt-5.4
TRANSCRIPTION_PROVIDER=openai
TRANSCRIPTION_MODEL=gpt-4o-transcribe
```

如果你希望 RoughCut 走 Codex / GPT-5 系列的工程型模型链路，当前 OpenAI Provider 已统一切到 `Responses API`，
因此这条链路会同时覆盖：

- 推理生成
- 多帧图像理解
- `web_search` 搜索增强

兼容模式下可以继续使用 `OPENAI_AUTH_MODE=codex_compat` + helper 命令输出凭据。

推荐本地中文 ASR 服务：

```env
TRANSCRIPTION_PROVIDER=qwen3_asr
TRANSCRIPTION_MODEL=qwen3-asr-1.7b
```

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

- Vite 开发地址 `http://127.0.0.1:5173`
- FastAPI 地址 `http://127.0.0.1:8000`

如果只想启动单个进程：

```bash
pnpm dev:web
pnpm dev:api
pnpm dev:orchestrator
pnpm dev:worker:media
pnpm dev:worker:llm
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
- ACP 默认优先调用 Codex，并建议使用 `gpt-5.4-mini` 承担工程级任务；Claude 作为后备桥接后端
- ACP/Codex prompt 会自动附带 RoughCut 项目规则和同 Telegram 会话的近期任务记忆，避免每次冷启动
- 如果是需要改代码的扩展类请求，会自动创建待确认任务
- 如果是分析类请求，会直接创建只读诊断任务

### 9. 测试与构建

```bash
pnpm test
pnpm build
pnpm lint
```

细分命令：

```bash
pnpm test:clip -- E:/videos/demo.mp4
pnpm test:frontend
pnpm test:backend
pnpm build:frontend
pnpm build:backend
```

如果你要每次换一条视频源做完整链路测试，不要走 `pytest`，直接跑手工链路测试：

```bash
pnpm test:clip -- E:/videos/demo.mp4
uv run roughcut clip-test E:/videos/demo.mp4 --channel-profile edc_tactical --sample-seconds 90
```

每次只要换掉传入的视频路径，就会生成一条新的测试任务产物到 `F:/roughcut_outputs/tests/manual-tests/`。

构建前端后，FastAPI 会直接托管 `frontend/dist`。

### 10. 一键本地启动（Windows）

```powershell
./start_roughcut.bat
```

Windows 下当前建议把 [start_roughcut.bat](E:/WorkSpace/RoughCut/start_roughcut.bat) 作为用户入口：

- `start_roughcut.bat`
  默认开发入口。后台拉起本地 API / orchestrator / workers，并服务本地构建的 `frontend/dist`；这个终端窗口本身就是托管器，直接关窗即可停掉整套服务
- `start_roughcut.bat infra`
  只启动 PostgreSQL / Redis / MinIO 这套轻量基础设施，供本地服务使用
- `start_roughcut.bat runtime`
  显式容器模式。启动容器化 `api + orchestrator + worker-media + worker-llm`；`runtime/full` 默认会带上 `docker-compose.dev.yml`，通过 bind mount + 容器内 watcher 提供 live source sync；默认不在容器里安装 `local-asr` extras
- `start_roughcut.bat runtime-local-asr`
  启动 runtime，并显式在 Docker 镜像里启用 `local-asr` extras
- `start_roughcut.bat full`
  显式容器模式。启动 runtime + automation（当前包含 `watcher`）；`runtime/full` 默认会带上 `docker-compose.dev.yml`，通过 bind mount + 容器内 watcher 提供 live source sync；默认不在容器里安装 `local-asr` extras
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
- `pnpm docker:runtime:auto-up`
  从根目录启动显式容器化 runtime，并自动构建重建（host-side）
- `pnpm docker:auto:auto-up`
  从根目录启动显式容器化 full（runtime + automation），并自动构建重建（host-side）
- `start_roughcut.bat dev`
  直接运行统一入口 `pnpm dev`
- `start_roughcut.bat test`
  运行 `pnpm test`
- `start_roughcut.bat clip-test E:\videos\demo.mp4`
  跑一条指定视频源的完整手工测试链路
- `start_roughcut.bat build`
  运行 `pnpm build`

`start_roughcut.ps1` 是当前主脚本，也是一键启动的实际实现。

默认开发建议是把 `start_roughcut.bat` 作为默认开发入口；Docker 更适合基础依赖、部署验证和显式容器化运行。`pnpm docker:up/down` 现在只作为 `infra` 快捷别名保留。

---

## Docker 部署

仓库现在推荐把 Docker 拆成三层，而不是继续只用一个全量 compose：

- `docker-compose.infra.yml`
  只放 `postgres` / `redis`
- `docker-compose.runtime.yml`
  放推荐常驻的 `migrate` / `api` / `orchestrator` / `worker-media` / `worker-llm`
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
docker compose -f docker-compose.infra.yml up -d
```

推荐常驻（基础设施 + Docker runtime，默认 live source sync）：

```bash
docker compose -f docker-compose.infra.yml -f docker-compose.runtime.yml -f docker-compose.dev.yml up -d --build
```

全自动无人值守（再加 watcher，默认 live source sync）：

```bash
docker compose -f docker-compose.infra.yml -f docker-compose.runtime.yml -f docker-compose.automation.yml -f docker-compose.dev.yml up -d --build
```

推荐常驻默认包含：

- `api`：FastAPI + 内置静态面板，访问 `http://localhost:8000`
- `orchestrator`
- `worker-media`
- `worker-llm`
- `postgres`
- `redis`

全自动无人值守额外包含：

- `watcher`

### 3. 查看日志

```bash
docker compose -f docker-compose.infra.yml -f docker-compose.runtime.yml logs -f api
docker compose -f docker-compose.infra.yml -f docker-compose.runtime.yml logs -f orchestrator
docker compose -f docker-compose.infra.yml -f docker-compose.runtime.yml logs -f worker-media
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
  单次执行 `docker compose up -d --build --force-recreate`，只重建 `migrate / api / orchestrator / worker-media / worker-llm`，不会主动重建 `postgres / redis`
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

- `F:/roughcut_outputs/output`：成片输出
- `F:/roughcut_outputs/render-debug`：render 诊断目录
- `F:/roughcut_outputs/jobs`：任务运行期文件与中间产物
- `F:/roughcut_outputs/heygem`：HeyGem 输入 / temp / result
- `./watch`：可选目录监听挂载点（启用 automation compose 时使用）

  ### 5. 说明
  
- Docker 镜像默认内置 `uv`、`ffmpeg` 和 `Noto Sans CJK` 中文字体。
- Docker 镜像会在构建阶段自动执行 `frontend/` 下的前端依赖安装和构建。
- 默认 Docker 入口会强制清空 `ROUGHCUT_DOCKER_PYTHON_EXTRAS`，优先走更轻的 runtime 构建；如果你确实要在容器内启用 `funasr` / `faster-whisper`，使用 `pnpm docker:runtime:up:local-asr`、`pnpm docker:auto:up:local-asr`，或显式传 `-DockerPythonExtras local-asr`。
- 当前项目默认 ASR 方案为 `openai + gpt-4o-transcribe`；本地服务优先建议 `qwen3_asr + qwen3-asr-1.7b`；离线本地依赖可选 `funasr + sensevoice-small` 或 `faster_whisper`。
  - 推荐把长期在线形态收敛到 `infra + runtime` 这一档；`watcher` 只在确实需要自动扫盘时再加入。
- 推荐本地开发使用 `uv + npm`，容器部署使用 `docker compose`，不要混用系统级 `pip` 和容器内运行时配置。

---

## API 使用

### 上传视频

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -F "file=@video.mov"
```

返回 `job_id`。

### 查询进度

```bash
curl http://localhost:8000/api/v1/jobs/{job_id}
```

返回各步骤状态（pending / running / done / failed）。

### 下载成片

```bash
curl http://localhost:8000/api/v1/jobs/{job_id}/download -o output.mp4
```

### 术语词表管理

```bash
# 添加术语
curl -X POST http://localhost:8000/api/v1/glossary \
  -H "Content-Type: application/json" \
  -d '{"wrong_forms": ["苹果手机", "爱疯"], "correct_form": "iPhone", "category": "brand"}'

# 查询所有术语
curl http://localhost:8000/api/v1/glossary
```

### 审校报告

```bash
curl http://localhost:8000/api/v1/jobs/{job_id}/report
```

---

## 配置说明

所有配置项通过 `.env` 文件或环境变量设置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `JOB_STORAGE_DIR` | `F:/roughcut_outputs/jobs` | 任务运行期文件根目录 |
| `OUTPUT_DIR` | `F:/roughcut_outputs/output` | 成片输出目录 |
| `OUTPUT_NAME_PATTERN` | `{date}_{stem}` | 输出文件名模板 |
| `RENDER_DEBUG_DIR` | `F:/roughcut_outputs/render-debug` | render 调试产物目录 |
| `REASONING_PROVIDER` | `minimax` | 推理后端：`openai` / `anthropic` / `minimax` / `ollama` |
| `REASONING_MODEL` | `MiniMax-M2.7-highspeed` | 推理模型名称 |
| `MULTIMODAL_FALLBACK_PROVIDER` | `ollama` | 主模型视觉失败时的本地备份 provider |
| `MULTIMODAL_FALLBACK_MODEL` | `""` | 主模型视觉失败时的本地备份视觉模型（空 = 自动探测） |
| `SEARCH_PROVIDER` | `auto` | 搜索后端：优先主模型搜索桥接，失败回退本地搜索 |
| `SEARCH_FALLBACK_PROVIDER` | `searxng` | 主模型搜索失败时的兜底搜索后端 |
| `MODEL_SEARCH_HELPER` | `""` | 主模型搜索/MCP 的本地桥接命令，读取 `ROUGHCUT_SEARCH_QUERY` 环境变量 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI/Codex 兼容接口地址 |
| `OPENAI_AUTH_MODE` | `api_key` | `api_key` / `codex_compat` |
| `OPENAI_API_KEY_HELPER` | `""` | Codex 兼容模式下返回凭证的本地命令 |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Anthropic/Claude Code 兼容接口地址 |
| `ANTHROPIC_AUTH_MODE` | `api_key` | `api_key` / `claude_code_compat` |
| `ANTHROPIC_API_KEY_HELPER` | `""` | Claude Code 兼容模式下返回凭证的本地命令 |
| `MINIMAX_API_KEY` | `""` | MiniMax 普通推理 API Key（OpenAI 兼容） |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.com/v1` | MiniMax OpenAI 兼容接口地址 |
| `MINIMAX_API_HOST` | `https://api.minimaxi.com` | MiniMax Coding Plan / MCP API Host |
| `MINIMAX_CODING_PLAN_API_KEY` | `""` | MiniMax Coding Plan Key；留空时搜索/MCP 默认回退 `MINIMAX_API_KEY` |
| `VISION_MODEL` | `""` | 视觉模型（空 = 使用 reasoning_model） |
| `TRANSCRIPTION_PROVIDER` | `openai` | 转写后端：`openai` / `qwen3_asr` / `funasr` / `faster_whisper` |
| `TRANSCRIPTION_MODEL` | `gpt-4o-transcribe` | 转写模型 |
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
| `TELEGRAM_AGENT_STATE_DIR` | `F:/roughcut_outputs/telegram-agent` | Telegram agent 本地任务状态文件目录 |
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
当前推荐链路是：ACP 主走 Claude Code `opus`，失败时自动 fallback 到 Codex `gpt-5.4-mini`。
| `AUTO_CONFIRM_CONTENT_PROFILE` | `true` | 高置信度内容摘要自动确认，避免任务卡在人工核对 |
| `CONTENT_PROFILE_REVIEW_THRESHOLD` | `0.72` | 内容摘要自动确认阈值，范围 `0.0` 到 `1.0` |
| `AUTO_ACCEPT_GLOSSARY_CORRECTIONS` | `true` | 高置信度术语纠错自动接受，只保留风险项待确认 |
| `GLOSSARY_CORRECTION_REVIEW_THRESHOLD` | `0.9` | 术语纠错自动接受阈值，范围 `0.0` 到 `1.0` |
| `AUTO_SELECT_COVER_VARIANT` | `true` | 自动选择首选封面，默认只在候选分差接近时提醒确认 |
| `COVER_SELECTION_REVIEW_GAP` | `0.08` | 首选封面与次优封面的最小安全分差，范围 `0.0` 到 `1.0` |
| `PACKAGING_SELECTION_REVIEW_GAP` | `0.08` | BGM/插入素材首选与次优的最小安全分差，过近时建议确认 |
| `PACKAGING_SELECTION_MIN_SCORE` | `0.6` | BGM/插入素材最低自动通过分，低于该值建议确认 |

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

# 前后端测试
pnpm test

# 前端构建
pnpm build

# 后端 lint
pnpm lint:backend
```

### 项目改名或目录迁移后的环境修复

如果你把仓库从 `FastCut` 改名为 `RoughCut`，或直接移动了项目目录，记得重新安装 editable package。否则虚拟环境里的 `.pth` 和 pytest 缓存可能仍指向旧路径，表现为：

- `ModuleNotFoundError: No module named 'roughcut'`
- pytest 报错路径仍显示旧目录，例如 `E:/WorkSpace/FastCut/...`

建议执行：

```bash
python -m pip uninstall -y fastcut roughcut
python -m pip install -e ".[dev]"
```

如果 pytest 仍命中旧路径，再清理缓存后重跑：

```bash
# Windows
for /d /r %d in (__pycache__) do @if exist "%d" rd /s /q "%d"
if exist .pytest_cache rd /s /q .pytest_cache

# Linux / macOS
find . -type d -name "__pycache__" -prune -exec rm -rf {} +
rm -rf .pytest_cache
```

---

## 渲染排查

当 render 遇到旋转、任务文件路径或 ffmpeg 参数问题时，可直接查看：

- `F:/roughcut_outputs/render-debug/{job_id}_{output_name}/source.integrity.json`：下载源文件 SHA-256 校验
- `F:/roughcut_outputs/render-debug/{job_id}_{output_name}/source.ffprobe.json`：下载源文件的 ffprobe 结果
- `F:/roughcut_outputs/render-debug/{job_id}_{output_name}/render.ffmpeg.txt`：完整渲染命令
- `F:/roughcut_outputs/render-debug/{job_id}_{output_name}/strip.ffmpeg.txt` / `normalize.ffmpeg.txt`：旋转归一化命令
- `F:/roughcut_outputs/render-debug/{job_id}_{output_name}/*.stderr.log`：对应 ffmpeg stderr 输出

---

## Provider 兼容说明

- `MiniMax` 已按官方 OpenAI 兼容接口接入，可直接作为 `reasoning_provider=minimax` 使用。
- `Claude Code` 与 `Codex` 目前在本项目中采用“兼容凭证模式”而不是浏览器内第三方 OAuth 回跳。
- 兼容凭证模式的含义：你可以切到 `claude_code_compat` / `codex_compat`，并配置一个本地 helper 命令，让 RoughCut 在调用模型前获取当前凭证。
- 多模态链路现在默认“主模型优先，本地 Ollama 兜底”。主体识别、封面选帧、旋转判断优先走当前主模型视觉能力。
- 联网搜索链路现在默认 `SEARCH_PROVIDER=auto`。如果配置了 `MODEL_SEARCH_HELPER`，会优先走主模型搜索/MCP；失败后回退到 `SearXNG`。
