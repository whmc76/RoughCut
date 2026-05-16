ARG BASE_IMAGE=docker.m.daocloud.io/pytorch/pytorch:2.9.1-cuda12.8-cudnn9-devel
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=20

ARG MOSS_TTS_REPO_URL=https://github.com/OpenMOSS/MOSS-TTS.git

WORKDIR /opt

RUN apt-get update -y \
    && apt-get install -y --no-install-recommends git git-lfs ffmpeg sox libsox-dev libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install \
    && git clone --depth 1 "${MOSS_TTS_REPO_URL}" /opt/MOSS-TTS

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade --retries 20 --timeout 180 setuptools wheel \
    && python -m pip install --prefer-binary --retries 20 --timeout 180 --extra-index-url https://download.pytorch.org/whl/cu128 -e /opt/MOSS-TTS \
    && python -m pip install --prefer-binary --retries 20 --timeout 180 --extra-index-url https://download.pytorch.org/whl/cu128 \
        "transformers==5.0.0" "torchcodec==0.8.1" fastapi uvicorn python-multipart huggingface_hub modelscope

COPY deploy/moss-tts-local/server.py /opt/roughcut-moss-tts-local/server.py
COPY deploy/moss-tts-local/start-moss-tts-local.sh /opt/roughcut-moss-tts-local/start-moss-tts-local.sh
RUN chmod +x /opt/roughcut-moss-tts-local/start-moss-tts-local.sh

WORKDIR /opt/MOSS-TTS

EXPOSE 8080

ENTRYPOINT ["bash", "/opt/roughcut-moss-tts-local/start-moss-tts-local.sh"]
