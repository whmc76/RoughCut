ARG BASE_IMAGE=pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime
FROM ${BASE_IMAGE}

ARG APT_MIRROR=http://mirrors.aliyun.com/ubuntu
ARG HF_ENDPOINT=https://hf-mirror.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
ARG FUN_ASR_SOURCE_URLS="https://gh.llkk.cc/https://github.com/FunAudioLLM/Fun-ASR/archive/refs/heads/main.zip https://ghfast.top/https://github.com/FunAudioLLM/Fun-ASR/archive/refs/heads/main.zip https://github.com/FunAudioLLM/Fun-ASR/archive/refs/heads/main.zip"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    HF_ENDPOINT=${HF_ENDPOINT} \
    HF_HOME=/models/huggingface \
    HUGGINGFACE_HUB_CACHE=/models/huggingface/hub \
    MODELSCOPE_CACHE=/models/modelscope \
    FUN_ASR_SOURCE_URLS=${FUN_ASR_SOURCE_URLS} \
    FUNASR_NANO_REMOTE_CODE=/opt/Fun-ASR/model.py

ARG FUNASR_INSTALL_OS_DEPS=false

RUN if [ "${FUNASR_INSTALL_OS_DEPS}" = "true" ]; then \
        sed -i "s|http://archive.ubuntu.com/ubuntu|${APT_MIRROR}|g; s|http://security.ubuntu.com/ubuntu|${APT_MIRROR}|g" /etc/apt/sources.list || true; \
        apt-get update -o Acquire::Retries=5 \
        && apt-get install -y --no-install-recommends \
            ca-certificates \
            ffmpeg \
            libsndfile1 \
        && rm -rf /var/lib/apt/lists/*; \
    fi

RUN python -m pip install --no-build-isolation jieba==0.42.1 \
    && python -m pip install --no-build-isolation \
        fastapi \
        funasr==1.3.1 \
        modelscope \
        openai-whisper \
        python-multipart \
        soundfile \
        uvicorn

WORKDIR /opt

RUN python - <<'PY'
import os
import pathlib
import shutil
import urllib.request
import zipfile

archive = pathlib.Path("/tmp/fun-asr-main.zip")
target = pathlib.Path("/opt/Fun-ASR")
shutil.rmtree(target, ignore_errors=True)
errors = []
for url in os.environ.get("FUN_ASR_SOURCE_URLS", "").split():
    try:
        print(f"Downloading Fun-ASR remote code from {url}", flush=True)
        with urllib.request.urlopen(url, timeout=300) as response:
            archive.write_bytes(response.read())
        break
    except Exception as exc:
        errors.append(f"{url}: {exc}")
else:
    raise RuntimeError("Failed to download Fun-ASR source:\n" + "\n".join(errors))
with zipfile.ZipFile(archive) as handle:
    handle.extractall("/opt")
extracted = pathlib.Path("/opt/Fun-ASR-main")
extracted.rename(target)
archive.unlink(missing_ok=True)
PY

COPY deploy/funasr/server.py /opt/funasr-server/server.py

WORKDIR /opt/funasr-server

EXPOSE 30000

ENTRYPOINT ["python", "/opt/funasr-server/server.py"]
