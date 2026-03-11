# RoughCut MVP — 设计文档
状态: Confirmed
日期: 2026-03-10
涉及文件: 全项目初始实现

## 问题 / 背景
构建面向口播/开箱视频的"自动剪辑 + 字幕审校"系统。
Phase 1 MVP 不含联网核验，只做：上传/监听 → 转写 → glossary 纠错 → 静音/语气词裁剪 → timeline + 渲染。
Phase 2 再加事实抽取 + SearXNG 核验 + Review UI 证据面板。

## 方案

### 系统架构 (5 进程)
- `api` — FastAPI，上传/查询/glossary CRUD
- `orchestrator` — 状态机，推进 job_steps
- `worker-media` — ffprobe/ffmpeg/渲染 (Celery)
- `worker-llm` — 转写后处理/glossary 匹配 (Celery)
- `watcher` — 目录监听，hash 去重，入库

### 能力接口拆分
- TranscriptionProvider: openai / local_whisper
- ReasoningProvider: openai / anthropic / ollama
- SearchProvider: searxng (Phase 2)
- RenderBackend: ffmpeg

### 数据模型
核心表：jobs, job_steps, artifacts, transcript_segments, subtitle_items, subtitle_corrections, timelines, render_outputs, glossary_terms, watch_roots, channel_profiles
Phase 2 预留：fact_claims, fact_evidence

### Pipeline 步骤顺序
probe → extract_audio → transcribe → subtitle_postprocess → glossary_review → edit_plan → render

## 关键决策
1. 编排状态在 DB (job_steps 表)，不依赖 Celery chain — 支持断点续跑/重试
2. 能力接口分离 (Transcription/Reasoning/Search) — 可按配置切换 provider
3. 时间轴双层模型 (editorial_timeline + render_plan) — 解耦剪辑决策与渲染参数
4. MinIO 用于存储，按 job 隔离 bucket 路径
5. 运行时 LLM 用 OpenAI/Anthropic/Ollama API，不用 Claude Code CLI

## 放弃的备选方案
- 统一 LLMProvider 接口：转写与推理需求差异大，拆分更清晰
- Celery chain 做编排：状态不持久化，断点续跑难

## 实现要点
- pyproject.toml 用 hatch 构建
- docker-compose 包含 PostgreSQL, Redis, MinIO
- Alembic 做数据库迁移
- webrtcvad 静音检测
- opentimelineio OTIO 导出
- click CLI 入口

## 变更历史
- 2026-03-10: 初始实现
