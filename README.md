# RoughCut

面向口播/开箱视频的自动剪辑 + 字幕审校系统。

上传原始视频后，流水线自动完成：转写 → 术语纠错 → 静音/语气词剪辑 → 字幕烧录 → 渲染输出，每个任务产出一组成片文件：`{YYYYMMDD}_{文件名}.mp4` + `.srt` + `_cover.jpg`。

---

## 功能

- **自动剪辑** — 检测静音段和语气词，生成剪辑时间轴，保留有效内容
- **转写** — 支持 OpenAI gpt-4o-transcribe 或本地 faster-whisper
- **字幕** — 字幕时间戳重映射至剪辑后时间轴，烧录荧光描边样式（黑字 + 绿色发光）
- **封面选帧** — 视觉模型从多个候选帧中挑选最佳封面，可选标题文字叠加
- **旋转修正** — 视觉模型识别实际画面方向，正确处理 iPhone 横屏/竖屏及错误元数据
- **渲染诊断** — 每次 render 落盘保存源文件哈希校验、ffprobe 结果、完整 ffmpeg 命令与 stderr 日志，便于手动复现
- **术语纠错** — 维护品牌/型号词表，自动匹配并标注疑似错误
- **断点续跑** — 每步骤状态持久化在数据库，进程崩溃后可从中断处继续
- **目录监听** — 监听指定文件夹，新视频自动入队处理
- **多 LLM 后端** — OpenAI / Anthropic / Ollama 可配置切换

---

## 架构

5 个独立进程，通过数据库协调状态：

```
api          — FastAPI，上传/查询/下载
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
- FFmpeg（需在 PATH 中，支持 libx264 / libass）
- Docker（运行 PostgreSQL、Redis、MinIO）
- LLM 后端之一：Ollama（本地）或 OpenAI API Key

---

## 快速开始

### 1. 启动基础服务

```bash
docker-compose up -d
```

启动 PostgreSQL（5432）、Redis（6379）、MinIO（9000/9001）。

### 2. 安装依赖

```bash
pip install -e ".[dev]"
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env` 并按需修改：

```bash
cp .env.example .env
```

最小配置（本地 Ollama）：

```env
REASONING_PROVIDER=ollama
REASONING_MODEL=qwen3.5:9b        # 需支持视觉
TRANSCRIPTION_PROVIDER=local_whisper
TRANSCRIPTION_MODEL=medium

OUTPUT_DIR=D:/output               # 成片输出目录
```

OpenAI 配置：

```env
OPENAI_API_KEY=sk-...
REASONING_PROVIDER=openai
REASONING_MODEL=gpt-4o-mini
TRANSCRIPTION_PROVIDER=openai
TRANSCRIPTION_MODEL=gpt-4o-transcribe
```

### 4. 初始化数据库

```bash
roughcut migrate
```

### 5. 启动各进程

```bash
# API 服务
roughcut api

# 编排器（单独终端）
roughcut orchestrator

# 媒体处理 Worker（单独终端）
roughcut worker --queue media_queue

# LLM Worker（单独终端）
roughcut worker --queue llm_queue

# 目录监听（可选）
roughcut watcher D:/录像
```

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
| `OUTPUT_DIR` | `Y:/EDC系列/AI粗剪` | 成片输出目录 |
| `OUTPUT_NAME_PATTERN` | `{date}_{stem}` | 输出文件名模板 |
| `RENDER_DEBUG_DIR` | `logs/render-debug` | render 调试产物目录 |
| `REASONING_PROVIDER` | `openai` | 推理后端：`openai` / `anthropic` / `minimax` / `ollama` |
| `REASONING_MODEL` | `gpt-4o-mini` | 推理模型名称 |
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
| `MINIMAX_API_KEY` | `""` | MiniMax API Key |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.com/v1` | MiniMax OpenAI 兼容接口地址 |
| `VISION_MODEL` | `""` | 视觉模型（空 = 使用 reasoning_model） |
| `TRANSCRIPTION_PROVIDER` | `openai` | 转写后端：`openai` / `local_whisper` |
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
| `FACT_CHECK_ENABLED` | `false` | 事实核验开关（Phase 2） |

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
│   ├── transcription/   # OpenAI Whisper / local faster-whisper
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
└── storage/             # MinIO/S3 存储层
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
# 运行测试
pytest

# 带覆盖率
pytest --cov=roughcut

# 代码格式化
ruff format src/
ruff check src/
```

---

## 渲染排查

当 render 遇到旋转、S3 下载一致性或 ffmpeg 参数问题时，可直接查看：

- `logs/render-debug/{job_id}_{output_name}/source.integrity.json`：下载源文件 SHA-256 校验
- `logs/render-debug/{job_id}_{output_name}/source.ffprobe.json`：下载源文件的 ffprobe 结果
- `logs/render-debug/{job_id}_{output_name}/render.ffmpeg.txt`：完整渲染命令
- `logs/render-debug/{job_id}_{output_name}/strip.ffmpeg.txt` / `normalize.ffmpeg.txt`：旋转归一化命令
- `logs/render-debug/{job_id}_{output_name}/*.stderr.log`：对应 ffmpeg stderr 输出

---

## Provider 兼容说明

- `MiniMax` 已按官方 OpenAI 兼容接口接入，可直接作为 `reasoning_provider=minimax` 使用。
- `Claude Code` 与 `Codex` 目前在本项目中采用“兼容凭证模式”而不是浏览器内第三方 OAuth 回跳。
- 兼容凭证模式的含义：你可以切到 `claude_code_compat` / `codex_compat`，并配置一个本地 helper 命令，让 RoughCut 在调用模型前获取当前凭证。
- 多模态链路现在默认“主模型优先，本地 Ollama 兜底”。主体识别、封面选帧、旋转判断优先走当前主模型视觉能力。
- 联网搜索链路现在默认 `SEARCH_PROVIDER=auto`。如果配置了 `MODEL_SEARCH_HELPER`，会优先走主模型搜索/MCP；失败后回退到 `SearXNG`。
