# Shared GPU Services

RoughCut now points at the real standalone repositories under `E:/WorkSpace` instead of the old in-repo aggregate stack.

- `http://127.0.0.1:49202` for HeyGem video preview/render
- `http://127.0.0.1:49204` for the primary `IndexTTS2 accel` voice synthesis / reference-driven dubbing instance

Files:

- `E:/WorkSpace/heygem/docker-compose.yml`
- `E:/WorkSpace/indextts2-service/docker-compose.yml`
- `scripts/start-heygem-shared.ps1` as a compatibility wrapper that starts the two real repos above

Default host data roots:

- `E:/WorkSpace/heygem/data`
- `E:/WorkSpace/RoughCut/data/voice_refs`

Start:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-heygem-shared.ps1
```

Projects can point at the shared services with:

```env
AVATAR_API_BASE_URL=http://127.0.0.1:49202
AVATAR_TRAINING_API_BASE_URL=http://127.0.0.1:49204
HEYGEM_SHARED_ROOT=E:/WorkSpace/heygem/data
HEYGEM_VOICE_ROOT=E:/WorkSpace/RoughCut/data/voice_refs
VOICE_PROVIDER=indextts2
VOICE_CLONE_API_BASE_URL=http://127.0.0.1:49204
```

Operational note:

- keep only one long-running IndexTTS2 instance bound to `49204`
- the current preferred production shape is `accel`
- do not leave separate `baseline / sage / accel` containers resident on the same GPU
- `deploy/heygem-shared/` is now legacy compatibility material and is no longer the default startup target
