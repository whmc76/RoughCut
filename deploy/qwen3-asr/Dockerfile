ARG BASE_IMAGE=pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime
FROM ${BASE_IMAGE}
ARG QWEN3_ASR_INSTALL_DEPS=true

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/models/huggingface \
    HUGGINGFACE_HUB_CACHE=/models/huggingface/hub

RUN if [ "${QWEN3_ASR_INSTALL_DEPS}" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends ffmpeg libsndfile1 sox \
        && rm -rf /var/lib/apt/lists/* \
        && python3 -m pip install --no-cache-dir \
            qwen-asr==0.0.6 \
            fastapi \
            uvicorn \
            python-multipart \
            soundfile; \
    fi

WORKDIR /app

COPY deploy/qwen3-asr/server.py /app/server.py

ENTRYPOINT []
CMD ["python3", "/app/server.py"]
