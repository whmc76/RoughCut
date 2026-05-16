#!/usr/bin/env bash
set -euo pipefail

MODEL_ID="${MOSS_TTS_LOCAL_MODEL_ID:-OpenMOSS-Team/MOSS-TTS-Local-Transformer}"
MODELSCOPE_MODEL_ID="${MOSS_TTS_LOCAL_MODELSCOPE_MODEL_ID:-OpenMOSS/MOSS-TTS-Local-Transformer}"
MODEL_DIR="${MOSS_TTS_LOCAL_MODEL_DIR:-/models/moss-tts-local-transformer}"
DOWNLOAD_BACKEND="${MOSS_TTS_LOCAL_DOWNLOAD_BACKEND:-huggingface}"

mkdir -p "${MODEL_DIR}"

REQUIRED_MODEL_FILES=(
  "${MODEL_DIR}/config.json"
  "${MODEL_DIR}/model.safetensors.index.json"
  "${MODEL_DIR}/model-00001-of-00002.safetensors"
  "${MODEL_DIR}/model-00002-of-00002.safetensors"
)

NEED_DOWNLOAD=0
for required_file in "${REQUIRED_MODEL_FILES[@]}"; do
  if [ ! -s "${required_file}" ]; then
    NEED_DOWNLOAD=1
    break
  fi
done

if [ "${NEED_DOWNLOAD}" = "1" ]; then
  python - <<'PY'
import os

model_id = os.environ.get("MOSS_TTS_LOCAL_MODEL_ID", "OpenMOSS-Team/MOSS-TTS-Local-Transformer")
modelscope_model_id = os.environ.get("MOSS_TTS_LOCAL_MODELSCOPE_MODEL_ID", "OpenMOSS/MOSS-TTS-Local-Transformer")
model_dir = os.environ.get("MOSS_TTS_LOCAL_MODEL_DIR", "/models/moss-tts-local-transformer")
backend = os.environ.get("MOSS_TTS_LOCAL_DOWNLOAD_BACKEND", "huggingface").lower()

if backend == "modelscope":
    from modelscope import snapshot_download
    snapshot_download(modelscope_model_id, local_dir=model_dir)
else:
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=model_id, local_dir=model_dir, local_dir_use_symlinks=False)
PY
fi

export PYTHONPATH="/opt/MOSS-TTS:${PYTHONPATH:-}"

exec python /opt/roughcut-moss-tts-local/server.py \
  --host 0.0.0.0 \
  --port 8080 \
  --model_dir "${MODEL_DIR}" \
  ${MOSS_TTS_LOCAL_EXTRA_ARGS:-}
