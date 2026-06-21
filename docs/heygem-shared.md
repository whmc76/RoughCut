# Shared GPU Services

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

RoughCut now points at a standalone shared-service workspace instead of the old in-repo aggregate stack. HeyGem itself remains an external shared service; do not copy or migrate its compose stack or shared data root into RoughCut-owned directories.

- `http://127.0.0.1:49202` for HeyGem video preview/render
- `http://127.0.0.1:49204` for the optional local voice/training endpoint when IndexTTS2 is explicitly enabled

Files:

- `HEYGEM_DOCKER_COMPOSE_FILE`
- `HEYGEM_DOCKER_ENV_FILE` for the canonical shared data root
- `INDEXTTS2_DOCKER_COMPOSE_FILE` only for legacy/local IndexTTS2 use
- `scripts/start-heygem-shared.ps1` as a launcher wrapper for the shared local services

Shared HeyGem host data roots:

- `HEYGEM_SHARED_ROOT`
- `HEYGEM_VOICE_ROOT`

RoughCut-owned runtime data is limited to its own jobs, output, cache, and render-debug directories. HeyGem inputs, temp files, and results stay under the shared HeyGem data root above.

Start:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-heygem-shared.ps1
```

Projects can point at the shared services with:

```env
AVATAR_API_BASE_URL=http://127.0.0.1:49202
AVATAR_TRAINING_API_BASE_URL=http://127.0.0.1:49204
HEYGEM_DOCKER_ENV_FILE=../heygem/.env
HEYGEM_SHARED_ROOT=./data/heygem-shared
HEYGEM_VOICE_ROOT=./data/heygem-shared/voice/data
VOICE_PROVIDER=runninghub
VOICE_CLONE_API_BASE_URL=https://www.runninghub.cn
VOICE_CLONE_VOICE_ID=2003864334474354690
```

Operational note:

- TTS / voice cloning defaults to RunningHub
- only keep a local IndexTTS2 instance bound to `49204` when `VOICE_PROVIDER=indextts2`
- `deploy/heygem-shared/` is archived deployment material and is no longer the default startup target
- when RoughCut stages presenter video or segment audio for HeyGem, it resolves the public shared directory from `HEYGEM_DOCKER_ENV_FILE` / `HEYGEM_DATA_DIR` before falling back to RoughCut environment variables
