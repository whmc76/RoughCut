ARG BASE_IMAGE=pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime
FROM ${BASE_IMAGE}

ARG APT_MIRROR=http://mirrors.aliyun.com/ubuntu
ARG HF_ENDPOINT=https://hf-mirror.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    HF_ENDPOINT=${HF_ENDPOINT} \
    HF_HOME=/models/huggingface \
    HUGGINGFACE_HUB_CACHE=/models/huggingface/hub

ARG FASTER_WHISPER_INSTALL_OS_DEPS=false

RUN if [ "${FASTER_WHISPER_INSTALL_OS_DEPS}" = "true" ]; then \
        sed -i "s|http://archive.ubuntu.com/ubuntu|${APT_MIRROR}|g; s|http://security.ubuntu.com/ubuntu|${APT_MIRROR}|g" /etc/apt/sources.list || true; \
        apt-get update -o Acquire::Retries=5 \
        && apt-get install -y --no-install-recommends \
            ca-certificates \
            ffmpeg \
            libsndfile1 \
        && rm -rf /var/lib/apt/lists/*; \
    fi

RUN python -m pip install \
        faster-whisper \
        fastapi \
        python-multipart \
        soundfile \
        uvicorn

COPY deploy/faster-whisper/server.py /opt/faster-whisper-server/server.py

WORKDIR /opt/faster-whisper-server

EXPOSE 30000

ENTRYPOINT ["python", "/opt/faster-whisper-server/server.py"]
