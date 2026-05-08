ARG BASE_IMAGE=roughcut-moss-audio:local
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/models/huggingface \
    HUGGINGFACE_HUB_CACHE=/models/huggingface/hub

# Runtime-isolate VibeVoice from the historical mixed ASR image. The base layers
# may still contain old bytes, but imports and service runtime only expose VibeVoice.
RUN python3 -m pip uninstall -y qwen-asr moss-audio || true \
    && rm -rf \
        /opt/MOSS-Audio \
        /opt/moss-audio-server \
        /usr/local/lib/python3.10/dist-packages/qwen_asr \
        /usr/local/lib/python3.10/dist-packages/qwen_asr-* \
        /usr/local/lib/python3.10/dist-packages/moss_audio \
        /usr/local/lib/python3.10/dist-packages/moss_audio-*

WORKDIR /app

ENTRYPOINT []
CMD ["python3", "-c", "import importlib.util; print({'vibevoice': bool(importlib.util.find_spec('vibevoice')), 'qwen_asr': bool(importlib.util.find_spec('qwen_asr')), 'moss_audio': bool(importlib.util.find_spec('moss_audio'))})"]
