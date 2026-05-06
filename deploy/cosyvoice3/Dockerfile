ARG BASE_IMAGE=roughcut-moss-audio:local
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

WORKDIR /opt

RUN apt-get update -y \
    && apt-get install -y --no-install-recommends git git-lfs unzip sox libsox-dev ffmpeg g++ python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install

RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice

RUN grep -v -E '^(openai-whisper|tensorrt|tensorrt-cu12|tensorrt-cu12-bindings|tensorrt-cu12-libs|tensorrt_cu12|tensorrt_cu12_bindings|tensorrt_cu12_libs|deepspeed|gradio|fastapi-cli|tensorboard|pyarrow|numpy|onnxruntime-gpu|torch|torchaudio)([=<>!~].*)?(;.*)?$' \
        /opt/CosyVoice/requirements.txt > /tmp/cosyvoice-runtime-requirements.txt

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=20 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --upgrade --retries 20 --timeout 180 "setuptools<82" wheel \
    && python3 -m pip install --no-deps --prefer-binary --retries 20 --timeout 180 -i https://pypi.tuna.tsinghua.edu.cn/simple numpy==1.26.4 \
    && python3 -m pip install --prefer-binary --retries 20 --timeout 180 -i https://pypi.tuna.tsinghua.edu.cn/simple onnxruntime==1.18.0 \
    && python3 -m pip install --prefer-binary --retries 20 --timeout 180 -r /tmp/cosyvoice-runtime-requirements.txt \
    && python3 -m pip install --no-deps --no-build-isolation --retries 20 --timeout 180 openai-whisper==20231117 \
    && python3 -m pip install --prefer-binary --retries 20 --timeout 180 fastapi uvicorn python-multipart torchcodec

COPY deploy/cosyvoice3/server.py /opt/roughcut-cosyvoice3/server.py
COPY deploy/cosyvoice3/start-cosyvoice3.sh /opt/roughcut-cosyvoice3/start-cosyvoice3.sh
RUN chmod +x /opt/roughcut-cosyvoice3/start-cosyvoice3.sh

WORKDIR /opt/CosyVoice

EXPOSE 8080

ENTRYPOINT ["bash", "/opt/roughcut-cosyvoice3/start-cosyvoice3.sh"]
