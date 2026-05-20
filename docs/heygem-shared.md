# Shared GPU Services

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

RoughCut now points at the real standalone repositories under `E:/WorkSpace` instead of the old in-repo aggregate stack. HeyGem itself remains the shared service in `E:/WorkSpace/heygem`; do not copy or migrate its compose stack or shared data root into RoughCut-owned directories.

- `http://127.0.0.1:49202` for HeyGem video preview/render
- `http://127.0.0.1:49204` for the optional local voice/training endpoint when IndexTTS2 is explicitly enabled

Files:

- `E:/WorkSpace/heygem/docker-compose.yml`
- `E:/WorkSpace/heygem/.env` for the canonical shared data root, currently `HEYGEM_DATA_DIR=D:/duix_avatar_data/face2face`
- `E:/WorkSpace/indextts2-service/docker-compose.yml` only for legacy/local IndexTTS2 use
- `scripts/start-heygem-shared.ps1` as a launcher wrapper for the shared local services

Shared HeyGem host data roots:

- `D:/duix_avatar_data/face2face`
- `D:/duix_avatar_data/face2face/voice/data`

RoughCut-owned runtime data is limited to its own jobs, output, cache, and render-debug directories. HeyGem inputs, temp files, and results stay under the shared HeyGem data root above.

Start:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-heygem-shared.ps1
```

Projects can point at the shared services with:

```env
AVATAR_API_BASE_URL=http://127.0.0.1:49202
AVATAR_TRAINING_API_BASE_URL=http://127.0.0.1:49204
HEYGEM_DOCKER_ENV_FILE=E:/WorkSpace/heygem/.env
HEYGEM_SHARED_ROOT=D:/duix_avatar_data/face2face
HEYGEM_VOICE_ROOT=D:/duix_avatar_data/face2face/voice/data
VOICE_PROVIDER=runninghub
VOICE_CLONE_API_BASE_URL=https://www.runninghub.cn
VOICE_CLONE_VOICE_ID=2003864334474354690
```

Operational note:

- TTS / voice cloning defaults to RunningHub
- only keep a local IndexTTS2 instance bound to `49204` when `VOICE_PROVIDER=indextts2`
- `deploy/heygem-shared/` is archived deployment material and is no longer the default startup target
- when RoughCut stages presenter video or segment audio for HeyGem, it resolves the public shared directory from `E:/WorkSpace/heygem/.env` / `HEYGEM_DATA_DIR` before falling back to RoughCut environment variables
