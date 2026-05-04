ARG BASE_IMAGE=pytorch/pytorch:2.9.1-cuda12.8-cudnn9-devel
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG MOSS_AUDIO_INSTALL_OS_DEPS=true

RUN if [ "${MOSS_AUDIO_INSTALL_OS_DEPS}" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /opt

RUN git clone --depth 1 https://github.com/OpenMOSS/MOSS-Audio.git /opt/MOSS-Audio \
    && PYTHON_BIN="$(command -v python || command -v python3)" \
    && "${PYTHON_BIN}" -m pip install --upgrade pip \
    && "${PYTHON_BIN}" -m pip install -e /opt/MOSS-Audio \
    && "${PYTHON_BIN}" -m pip install python-multipart

COPY deploy/moss-audio/server.py /opt/moss-audio-server/server.py

WORKDIR /opt/MOSS-Audio

EXPOSE 30000

ENTRYPOINT ["python3", "/opt/moss-audio-server/server.py"]
