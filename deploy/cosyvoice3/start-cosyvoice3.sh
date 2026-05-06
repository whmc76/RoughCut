#!/usr/bin/env bash
set -euo pipefail

MODEL_ID="${COSYVOICE3_MODEL_ID:-FunAudioLLM/Fun-CosyVoice3-0.5B-2512}"
MODEL_DIR="${COSYVOICE3_MODEL_DIR:-/models/cosyvoice3}"

mkdir -p "${MODEL_DIR}"

REQUIRED_MODEL_FILES=(
  "${MODEL_DIR}/cosyvoice3.yaml"
  "${MODEL_DIR}/llm.pt"
  "${MODEL_DIR}/llm.rl.pt"
  "${MODEL_DIR}/flow.pt"
  "${MODEL_DIR}/hift.pt"
  "${MODEL_DIR}/speech_tokenizer_v3.onnx"
  "${MODEL_DIR}/CosyVoice-BlankEN/model.safetensors"
)

NEED_DOWNLOAD=0
for required_file in "${REQUIRED_MODEL_FILES[@]}"; do
  if [ ! -s "${required_file}" ]; then
    NEED_DOWNLOAD=1
    break
  fi
done

if [ "${NEED_DOWNLOAD}" = "1" ]; then
  python3 - <<'PY'
import os

model_id = os.environ.get("COSYVOICE3_MODEL_ID", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
model_dir = os.environ.get("COSYVOICE3_MODEL_DIR", "/models/cosyvoice3")
backend = os.environ.get("COSYVOICE3_DOWNLOAD_BACKEND", "huggingface").lower()

if backend == "modelscope":
    from modelscope import snapshot_download
    snapshot_download(model_id, local_dir=model_dir)
else:
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=model_id, local_dir=model_dir, local_dir_use_symlinks=False)
PY
fi

export COSYVOICE_REPO_DIR="${COSYVOICE_REPO_DIR:-/opt/CosyVoice}"
export PYTHONPATH="/opt/CosyVoice:/opt/CosyVoice/third_party/Matcha-TTS:${PYTHONPATH:-}"

exec python3 /opt/roughcut-cosyvoice3/server.py \
  --host 0.0.0.0 \
  --port 8080 \
  --model_dir "${MODEL_DIR}" \
  ${COSYVOICE3_FP16:+--fp16} \
  ${COSYVOICE3_LOAD_VLLM:+--load_vllm} \
  ${COSYVOICE3_LOAD_TRT:+--load_trt} \
  ${COSYVOICE3_EXTRA_ARGS:-}
