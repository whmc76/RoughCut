# RoughCut

**Version:** 0.1.5
**Status:** prototype / active development

RoughCut is an automated editing, subtitle review, packaging, and publication
control system for talking-head, unboxing, and product-review videos.

It takes source video through a durable review pipeline:

```text
probe -> extract_audio -> transcribe -> subtitle_postprocess
      -> subtitle_term_resolution -> subtitle_consistency_review
      -> glossary_review -> transcript_review -> subtitle_translation
      -> content_profile -> summary_review -> ai_director
      -> avatar_commentary -> edit_plan -> render
```

The system is optimized for repeatable local production: every job step is
stored in the database, workers can resume interrupted work, render diagnostics
are written to disk, and manual edits are reapplied through the same render
contract instead of becoming browser-only state.

## What It Does

- Automatic video editing: detects low-value ranges, filler, silence, local
  highlight candidates, and product-focused keep segments.
- ASR and subtitle processing: supports local HTTP ASR services, OpenAI
  transcription, FunASR, and faster-whisper.
- Subtitle review: applies segmentation, term resolution, consistency review,
  glossary corrections, translation, and timing projection.
- Content understanding: builds product/topic profiles from transcript,
  visual evidence, OCR, source context, and memory.
- Manual editor: waveform regions, subtitle table editing, timing tools,
  thumbnail strip, revision conflict protection, and subtitle-only rerun paths.
- Packaging: manages intros, outros, watermarks, BGM, creator assets, and
  style templates.
- Digital avatar commentary: can generate avatar commentary plans and render
  picture-in-picture avatar outputs when configured.
- Intelligent copy: creates platform-specific titles, bodies, tags, cover
  requests, and publication material contracts.
- Publication automation: validates browser/profile readiness, runs release
  gates, and supports multi-adapter autopilot flows.
- Recovery and diagnostics: persists step state, render logs, ffprobe output,
  source hashes, quality assessments, and rerun recommendations.

## Architecture

The application is split into two product surfaces:

```text
frontend/        React + Vite operator console
src/roughcut/    FastAPI API, Celery workers, pipeline, providers, media logic
```

FastAPI also serves `frontend/dist` after frontend build.

Long-running production work is not owned by API background tasks. It is
coordinated through durable database state and worker processes:

| Process | Purpose |
| --- | --- |
| `api` | FastAPI API and static frontend serving |
| `orchestrator` | Polls `job_steps` and dispatches the next runnable step |
| `worker-media` | FFmpeg, probe, edit-plan, render, and media-heavy tasks |
| `worker-llm` | ASR post-processing, reasoning, review, copy, and model tasks |
| `worker-agent` | Telegram, ACP, Codex, and remote engineering tasks |
| `watcher` | Watches folders and enqueues new videos |
| `publication-browser-agent` | Optional browser automation bridge for publication |

The React console currently includes:

- Overview
- Jobs and job detail review
- Manual editor
- Watch roots
- Intelligent copy
- Creator cards
- Task strategies
- Visual plans
- Publication management
- Tools: ASR, TTS, avatar
- Memory
- Glossary
- Settings
- Runtime control

## Requirements

- Python 3.11+
- `uv`
- Node.js with Corepack / `pnpm`
- FFmpeg and ffprobe in `PATH`
- Docker and Docker Compose for local infra and optional runtime services
- At least one reasoning backend, such as Zhipu GLM, MiniMax, OpenAI,
  Anthropic, or Ollama
- Optional local AI services for ASR, TTS, avatar, and image generation

When downloading open-source model weights, prefer ModelScope when it provides
the required model, revision, and files. Fall back to Hugging Face only when
ModelScope cannot provide the needed artifact.

## Quick Start

Install package managers:

```bash
corepack enable
corepack prepare pnpm@latest --activate
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS / Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install dependencies:

```bash
pnpm bootstrap
```

Create runtime directories and `.env` from `.env.example` if needed:

```bash
pnpm setup
```

Start only local infrastructure:

```bash
pnpm docker:infra:up
```

This starts PostgreSQL, Redis, and MinIO for host-running API and workers.

Review `.env` and `roughcut.ports.env`, then run checks and migrations:

```bash
pnpm doctor
pnpm migrate
```

Start local development:

```bash
pnpm dev
```

Default local URLs are defined in `roughcut.ports.env`:

- Frontend dev server: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:38471`

## Windows One-Click Entry

On Windows, the recommended user-facing entry is:

```powershell
.\start_roughcut.bat
```

Common modes:

| Command | Purpose |
| --- | --- |
| `.\start_roughcut.bat` | Docker full dev stack |
| `.\start_roughcut.bat rebuild` | Full dev stack with forced image rebuild |
| `.\start_roughcut.bat local` | Host Python services plus Vite frontend |
| `.\start_roughcut.bat infra` | Only PostgreSQL, Redis, and MinIO |
| `.\start_roughcut.bat runtime` | Containerized API, orchestrator, and workers |
| `.\start_roughcut.bat test` | Docker stack plus local Vite test port |
| `.\start_roughcut.bat runtime-down` | Stop runtime services |
| `.\start_roughcut.bat full-down` | Stop runtime and automation services |
| `.\start_roughcut.bat install-autostart` | Register Windows login autostart |
| `.\start_roughcut.bat uninstall-autostart` | Remove Windows login autostart |

`start_roughcut.ps1` is the implementation behind the batch file.

## Configuration

Configuration is split intentionally:

- `roughcut.ports.env`: local port assignments and local dependent URLs.
- `.env`: credentials, provider choices, model names, runtime paths, and
  feature flags.

Do not scatter hardcoded ports in scripts or UI code. Add local port changes to
`roughcut.ports.env`.

Minimal local-development shape:

```env
ROUGHCUT_OUTPUT_ROOT=./data/runtime
JOB_STORAGE_DIR=./data/runtime/jobs
OUTPUT_DIR=./data/runtime/output
RENDER_DEBUG_DIR=./data/runtime/render-debug

DATABASE_URL=postgresql+asyncpg://roughcut:roughcut@localhost:25432/roughcut
REDIS_URL=redis://localhost:26379/0
CELERY_BROKER_URL=redis://localhost:26379/0
CELERY_RESULT_BACKEND=redis://localhost:26379/1

REASONING_PROVIDER=zhipu
REASONING_MODEL=glm-5.2
ZHIPU_API_KEY=

TRANSCRIPTION_PROVIDER=local_http_asr
LOCAL_ASR_API_BASE_URL=http://127.0.0.1:30230
LOCAL_ASR_MODEL_NAME=qwen3-asr-1.7b-forced-aligner
LOCAL_ASR_DISPLAY_NAME=Qwen3-ASR 1.7B + ForcedAligner
```

Use `.env.example` as the full reference for supported providers and feature
flags.

### Provider Notes

Supported reasoning/search/provider routes include:

- Zhipu GLM
- MiniMax
- OpenAI
- Anthropic
- Ollama
- SearXNG
- local model search helpers

Supported transcription routes include:

- `local_http_asr`
- `openai`
- `funasr`
- `faster_whisper`

The default local HTTP ASR slot can point to different services. The repository
contains deployment files for Qwen3-ASR, faster-whisper, FunASR, MOSS Audio,
CosyVoice3, and MOSS TTS Local. Host and Docker URLs are separated so container
runtime can call host-managed GPU services through `host.docker.internal`.

## Common Commands

| Command | Purpose |
| --- | --- |
| `pnpm bootstrap` | Install Python and frontend dependencies |
| `pnpm setup` | Initialize runtime folders and optional `.env` |
| `pnpm doctor` | Check Python, FFmpeg, ffprobe, and runtime prerequisites |
| `pnpm migrate` | Run Alembic migrations |
| `pnpm dev` | Start frontend, API, orchestrator, and workers |
| `pnpm dev:web` | Start only Vite |
| `pnpm dev:api` | Start only FastAPI |
| `pnpm dev:orchestrator` | Start only orchestrator |
| `pnpm dev:worker:media` | Start only media worker |
| `pnpm dev:worker:llm` | Start only LLM worker |
| `pnpm dev:worker:agent` | Start only agent worker |
| `pnpm dev:watcher` | Start folder watcher |
| `pnpm dev:telegram-agent` | Start Telegram engineering/review agent |
| `pnpm build` | Build frontend |
| `pnpm lint` | Run frontend typecheck, backend ruff, and agent-doc checks |
| `pnpm docker:infra:up` | Start local infrastructure |
| `pnpm docker:infra:down` | Stop local infrastructure |
| `pnpm docker:runtime:up` | Start containerized runtime |
| `pnpm docker:auto:up` | Start full Docker dev stack |

Backend CLI examples:

```bash
uv run roughcut doctor
uv run roughcut migrate
uv run roughcut api --reload
uv run roughcut orchestrator
uv run roughcut worker --queue media_queue
uv run roughcut worker --queue llm_queue
uv run roughcut watcher ./watch
```

## Data and Storage

Runtime state is intentionally outside source code:

```text
data/runtime/jobs           job-local files and artifacts
data/runtime/output         rendered outputs
data/runtime/cache          caches
data/runtime/render-debug   render reproducibility logs
data/runtime/tools          tool outputs
data/runtime/voice_refs     voice references
data/runtime/voice          generated voice assets
watch/                      default watched folder
artifacts/                  local reports and gate outputs
```

Important database tables:

| Table | Purpose |
| --- | --- |
| `jobs` | Job state and source metadata |
| `job_steps` | Durable pipeline step state, attempts, retries, metadata |
| `artifacts` | Step outputs and JSON payloads |
| `transcript_segments` | ASR transcript segments and word timing |
| `subtitle_items` | Display subtitle units |
| `subtitle_corrections` | Glossary and term correction suggestions |
| `timelines` | Editorial timeline and render contract |
| `render_outputs` | Rendered variants |
| `glossary_terms` | User and built-in glossary terms |
| `watch_roots` | Folder watch configuration |
| `publication_attempts` | Publication execution records |

## Manual Editor

The manual editor is documented in
[docs/design/manual-editor-open-source-plan.md](docs/design/manual-editor-open-source-plan.md).

Current behavior:

- Opens once `edit_plan` and earlier prerequisites are available.
- Uses waveform regions for keep segments.
- Projects subtitles from source time to output time.
- Supports subtitle text/timing edits, split, merge, shift, nudge, and
  diagnostics.
- Stores an OTIO-style editorial payload alongside legacy render-compatible
  segments.
- Protects saves with optimistic revision checks.
- Classifies edits as timeline changes, subtitle-only changes, or no material
  change.
- Reruns render through backend contracts instead of persisting UI-only state.

## Publication Flow

Publication is intentionally gated. The recommended order is:

```bash
pnpm dev:publication-browser-agent
pnpm run publication:preflight
pnpm run publication:release-gate
pnpm run publication:release-gate:real --media-path <video>
pnpm run publication:autopilot --media-path <video> --auto-retry --retry-cycles 2
```

Use draft/private visibility modes when validating real platform flows without
public posting.

Detailed publication contracts, browser/profile requirements, adapter choices,
duplicate gates, and recovery playbooks are in
[docs/publication-adapter-autopilot-runbook.md](docs/publication-adapter-autopilot-runbook.md).

## Project Layout

```text
src/roughcut/
  api/                 FastAPI routers and schemas
  avatar/              Avatar material runtime
  creative/            AI director and avatar commentary planning
  db/                  SQLAlchemy models and Alembic migrations
  edit/                Timeline, edit decisions, manual editor contracts
  host/                Host bridge, Codex proxy, file manager helpers
  media/               Probe, audio, scene, subtitles, render, output
  packaging/           Packaging asset library
  pipeline/            Celery tasks, orchestrator, quality, rerun actions
  providers/           Reasoning, transcription, search, voice, avatar, OCR
  recovery/            Stuck step and job index recovery helpers
  remix/               Remix and batch production helpers
  review/              Content profile, glossary, copy, quality, verification
  speech/              Transcribe, alignment, segmentation, subtitle pipeline
  storage/             Runtime cleanup and S3/MinIO storage
  telegram/            Telegram agent, task store, review notifications
  watcher/             Folder watcher

frontend/src/
  api/                 Frontend API clients
  components/          Shared UI components
  features/            Feature workspaces
  pages/               Route-level pages

deploy/                Optional local AI service deployment files
docs/                  Public reusable docs and runbooks
scripts/               Audits, release gates, diagnostics, service helpers
tests/                 Python and frontend regression tests
```

## Verification

Run the standard checks:

```bash
pnpm lint
pnpm build
```

Run targeted backend tests:

```bash
uv run pytest tests/test_pipeline_task_status.py -q
uv run pytest tests/test_manual_editor_session_regressions.py -q
uv run pytest tests/test_publication_release_gate.py -q
```

Open-source readiness checks:

```bash
uv run python scripts/check_open_source_readiness.py
uv run python scripts/check_agent_docs.py
```

For bug fixes, prefer a narrow verification tied to the root cause rather than
a broad smoke test that only proves the symptom disappeared.

## Render Diagnostics

Render failures leave reproducible evidence under:

```text
data/runtime/render-debug/{job_id}_{output_name}/
  source.integrity.json
  source.ffprobe.json
  render.ffmpeg.txt
  strip.ffmpeg.txt
  normalize.ffmpeg.txt
  *.stderr.log
```

Use these files before changing render logic. They capture the input hash,
ffprobe metadata, exact FFmpeg command, and stderr output.

## Open-Source Hygiene

The public repository must only contain reusable code, public docs, sample
configuration, and sanitized examples.

Do not commit:

- `.env`, tokens, API keys, browser profile state, or auth helpers
- real creator profiles, publication accounts, hotword memories, or learned
  private data
- local task state, agent ledgers, real run evidence, screenshots, or debug
  dumps
- filled-in history rewrite path lists or secret rotation records

Release checklist:

- [docs/design/open-source-release-checklist.md](docs/design/open-source-release-checklist.md)

History rewrite helper:

- [scripts/rewrite_open_source_history.ps1](scripts/rewrite_open_source_history.ps1)

Templates:

- [scripts/open_source_history/paths.example.txt](scripts/open_source_history/paths.example.txt)
- [scripts/open_source_history/replace-text.example.txt](scripts/open_source_history/replace-text.example.txt)
- [scripts/open_source_history/secret-rotation.example.md](scripts/open_source_history/secret-rotation.example.md)

## Design Docs

Start from:

- [docs/design/INDEX.md](docs/design/INDEX.md)
- [docs/design/project-build-principles.md](docs/design/project-build-principles.md)
- [docs/design/naming-system.md](docs/design/naming-system.md)
- [docs/design/manual-editor-open-source-plan.md](docs/design/manual-editor-open-source-plan.md)
- [docs/design/open-source-release-checklist.md](docs/design/open-source-release-checklist.md)

`AGENTS.md` is only the short agent entrypoint map. Do not use it as task
memory, issue history, or a platform-specific contract file.

## Troubleshooting

If imports still point to an old project path after moving or renaming the
repository, reinstall the editable package:

```bash
python -m pip uninstall -y fastcut roughcut
python -m pip install -e ".[dev]"
```

If Docker runtime cannot reach local AI services, check that:

- host service ports are in `roughcut.ports.env`
- Docker-facing URLs use `host.docker.internal`
- guard settings in `.env` match the service you expect to auto-start

If publication checks fail, do not continue to real posting until preflight is
green. Most failures are profile binding, missing platform tabs, unavailable
browser-agent, or duplicate publication gates.

If a job is interrupted, restart the orchestrator and workers first. Step state
is in the database, and the orchestrator is responsible for retrying or
recovering stale running steps.
