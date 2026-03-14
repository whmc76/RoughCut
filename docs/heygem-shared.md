# Shared HeyGem Services

This stack is independent from RoughCut and HydraMatrix. It exposes one shared pair of local services:

- `http://127.0.0.1:49202` for HeyGem video preview/render
- `http://127.0.0.1:49204` for the primary `IndexTTS2 accel` voice synthesis / reference-driven dubbing instance

Files:

- `deploy/heygem-shared/docker-compose.yml`
- `deploy/heygem-shared/.env.example`
- `scripts/start-heygem-shared.ps1`

Default host data roots:

- `D:/heygem-shared/face2face`
- `D:/heygem-shared/voice/data`

Start:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-heygem-shared.ps1
```

Projects can point at the shared services with:

```env
AVATAR_API_BASE_URL=http://127.0.0.1:49202
AVATAR_TRAINING_API_BASE_URL=http://127.0.0.1:49204
HEYGEM_SHARED_ROOT=D:/heygem-shared/face2face
HEYGEM_VOICE_ROOT=D:/heygem-shared/voice/data
VOICE_PROVIDER=indextts2
VOICE_CLONE_API_BASE_URL=http://127.0.0.1:49204
```

Operational note:

- keep only one long-running IndexTTS2 instance bound to `49204`
- the current preferred production shape is `accel`
- do not leave separate `baseline / sage / accel` containers resident on the same GPU
