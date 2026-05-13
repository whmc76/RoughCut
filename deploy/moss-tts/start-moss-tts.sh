#!/usr/bin/env bash
set -euo pipefail

MODEL_ID="${MOSS_TTSD_MODEL_ID:-OpenMOSS-Team/MOSS-TTSD-v1.0}"
QUANT_MODEL_ID="${MOSS_TTSD_QUANT_MODEL_ID:-groxaxo/MOSS-TTSD-NF4}"
USE_QUANT="${MOSS_TTSD_USE_QUANT:-false}"
MODEL_DIR="${MOSS_TTSD_MODEL_DIR:-/models/moss-ttsd}"
CODEC_MODEL_ID="${MOSS_TTSD_CODEC_MODEL_ID:-OpenMOSS-Team/MOSS-Audio-Tokenizer}"
MODELSCOPE_MODEL_ID="${MOSS_TTSD_MODELSCOPE_MODEL_ID:-OpenMOSS/MOSS-TTSD-v1.0}"
MODELSCOPE_CODEC_MODEL_ID="${MOSS_TTSD_MODELSCOPE_CODEC_MODEL_ID:-OpenMOSS/MOSS-Audio-Tokenizer}"
CODEC_DIR="${MOSS_TTSD_CODEC_DIR:-/models/moss-audio-tokenizer}"
FUSED_MODEL_DIR="${MOSS_TTSD_FUSED_MODEL_DIR:-/models/moss-ttsd-fused}"
DOWNLOAD_BACKEND="${MOSS_TTSD_DOWNLOAD_BACKEND:-modelscope}"

if [ "${USE_QUANT}" = "true" ]; then
  MODEL_ID="${QUANT_MODEL_ID}"
  MODEL_DIR="${MOSS_TTSD_QUANT_MODEL_DIR:-/models/moss-ttsd-nf4}"
  FUSED_MODEL_DIR="${MOSS_TTSD_QUANT_FUSED_MODEL_DIR:-/models/moss-ttsd-nf4-fused}"
fi

if [ "${DOWNLOAD_BACKEND}" = "modelscope" ] && [ "${USE_QUANT}" != "true" ]; then
  MODEL_ID="${MODELSCOPE_MODEL_ID}"
  CODEC_MODEL_ID="${MODELSCOPE_CODEC_MODEL_ID}"
fi

mkdir -p "${MODEL_DIR}" "${CODEC_DIR}" "$(dirname "${FUSED_MODEL_DIR}")"

download_model() {
  local model_id="$1"
  local model_dir="$2"
  python3 - <<'PY'
import os

model_id = os.environ["ROUGH_CUT_DOWNLOAD_MODEL_ID"]
model_dir = os.environ["ROUGH_CUT_DOWNLOAD_MODEL_DIR"]
backend = os.environ.get("MOSS_TTSD_DOWNLOAD_BACKEND", "huggingface").lower()

if backend == "modelscope":
    from modelscope import snapshot_download
    snapshot_download(model_id, local_dir=model_dir)
else:
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=model_id, local_dir=model_dir, local_dir_use_symlinks=False)
PY
}

if [ ! -s "${MODEL_DIR}/config.json" ]; then
  ROUGH_CUT_DOWNLOAD_MODEL_ID="${MODEL_ID}" ROUGH_CUT_DOWNLOAD_MODEL_DIR="${MODEL_DIR}" download_model "${MODEL_ID}" "${MODEL_DIR}"
fi

if [ ! -s "${CODEC_DIR}/config.json" ]; then
  ROUGH_CUT_DOWNLOAD_MODEL_ID="${CODEC_MODEL_ID}" ROUGH_CUT_DOWNLOAD_MODEL_DIR="${CODEC_DIR}" download_model "${CODEC_MODEL_ID}" "${CODEC_DIR}"
fi

if [ ! -s "${FUSED_MODEL_DIR}/config.json" ]; then
  rm -rf "${FUSED_MODEL_DIR}"
  python3 /opt/MOSS-TTSD/scripts/fuse_moss_tts_delay_with_codec.py \
    --codec-model-path "${CODEC_DIR}" \
    --model-path "${MODEL_DIR}" \
    --save-path "${FUSED_MODEL_DIR}"
fi

exec sglang serve \
  --host 0.0.0.0 \
  --port 30000 \
  --model-path "${FUSED_MODEL_DIR}" \
  --trust-remote-code \
  --delay-pattern \
  ${MOSS_TTSD_EXTRA_ARGS:-}
