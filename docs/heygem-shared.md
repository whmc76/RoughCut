# Shared GPU Services

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

RoughCut now points at the real standalone repositories under `E:/WorkSpace` instead of the old in-repo aggregate stack.

- `http://127.0.0.1:49202` for HeyGem video preview/render
- `http://127.0.0.1:49204` for the optional local voice/training endpoint when IndexTTS2 is explicitly enabled

Files:

- `E:/WorkSpace/heygem/docker-compose.yml`
- `E:/WorkSpace/indextts2-service/docker-compose.yml` only for legacy/local IndexTTS2 use
- `scripts/start-heygem-shared.ps1` as a launcher wrapper for the shared local services

Default host data roots:

- `F:/roughcut_outputs/heygem`
- `F:/roughcut_outputs/voice_refs`

Start:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-heygem-shared.ps1
```

Projects can point at the shared services with:

```env
AVATAR_API_BASE_URL=http://127.0.0.1:49202
AVATAR_TRAINING_API_BASE_URL=http://127.0.0.1:49204
HEYGEM_SHARED_ROOT=F:/roughcut_outputs/heygem
HEYGEM_VOICE_ROOT=F:/roughcut_outputs/voice_refs
VOICE_PROVIDER=runninghub
VOICE_CLONE_API_BASE_URL=https://www.runninghub.cn
VOICE_CLONE_VOICE_ID=2003864334474354690
```

Operational note:

- TTS / voice cloning defaults to RunningHub
- only keep a local IndexTTS2 instance bound to `49204` when `VOICE_PROVIDER=indextts2`
- `deploy/heygem-shared/` is archived deployment material and is no longer the default startup target
