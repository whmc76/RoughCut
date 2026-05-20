ARG BASE_IMAGE=pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime
FROM ${BASE_IMAGE}

ARG APT_MIRROR=http://mirrors.aliyun.com/ubuntu
ARG HF_ENDPOINT=https://hf-mirror.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
ARG MOSS_AUDIO_SOURCE_URLS="https://gh.llkk.cc/https://github.com/OpenMOSS/MOSS-Audio/archive/refs/heads/main.zip https://ghfast.top/https://github.com/OpenMOSS/MOSS-Audio/archive/refs/heads/main.zip https://github.com/OpenMOSS/MOSS-Audio/archive/refs/heads/main.zip"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    HF_ENDPOINT=${HF_ENDPOINT} \
    MOSS_AUDIO_SOURCE_URLS=${MOSS_AUDIO_SOURCE_URLS}

ARG MOSS_AUDIO_INSTALL_OS_DEPS=false

RUN if [ "${MOSS_AUDIO_INSTALL_OS_DEPS}" = "true" ]; then \
        sed -i "s|http://archive.ubuntu.com/ubuntu|${APT_MIRROR}|g; s|http://security.ubuntu.com/ubuntu|${APT_MIRROR}|g" /etc/apt/sources.list || true; \
        apt-get update -o Acquire::Retries=5 \
        && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /opt

RUN PYTHON_BIN="$(command -v python || command -v python3)" \
    && "${PYTHON_BIN}" - <<'PY'
import pathlib
import shutil
import urllib.request
import zipfile
import os

archive = pathlib.Path("/tmp/moss-audio-main.zip")
target = pathlib.Path("/opt/MOSS-Audio")
shutil.rmtree(target, ignore_errors=True)
errors = []
for url in os.environ.get("MOSS_AUDIO_SOURCE_URLS", "").split():
    try:
        print(f"Downloading MOSS-Audio from {url}", flush=True)
        with urllib.request.urlopen(url, timeout=300) as response:
            archive.write_bytes(response.read())
        break
    except Exception as exc:
        errors.append(f"{url}: {exc}")
else:
    raise RuntimeError("Failed to download MOSS-Audio source:\n" + "\n".join(errors))
with zipfile.ZipFile(archive) as handle:
    handle.extractall("/opt")
extracted = pathlib.Path("/opt/MOSS-Audio-main")
extracted.rename(target)
archive.unlink(missing_ok=True)
PY

RUN PYTHON_BIN="$(command -v python || command -v python3)" \
    && "${PYTHON_BIN}" -m pip install -e /opt/MOSS-Audio \
    && "${PYTHON_BIN}" -m pip install --upgrade bitsandbytes \
    && "${PYTHON_BIN}" -m pip install python-multipart

COPY deploy/moss-audio/server.py /opt/moss-audio-server/server.py

WORKDIR /opt/MOSS-Audio

EXPOSE 30000

ENTRYPOINT ["python3", "/opt/moss-audio-server/server.py"]
