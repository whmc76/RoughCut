ARG BASE_IMAGE=pytorch/pytorch:2.9.1-cuda12.8-cudnn9-devel
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CUDA_HOME=/usr/local/cuda \
    CUDA_PATH=/usr/local/cuda

WORKDIR /opt

RUN sed -i 's|http://archive.ubuntu.com/ubuntu|https://mirrors.tuna.tsinghua.edu.cn/ubuntu|g; s|http://security.ubuntu.com/ubuntu|https://mirrors.tuna.tsinghua.edu.cn/ubuntu|g' /etc/apt/sources.list \
    && apt-get update -y \
    && apt-get install -y --no-install-recommends git git-lfs ffmpeg libsndfile1 build-essential python3-dev ninja-build \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install

ARG MOSS_TTSD_REPO_URL=https://github.com/OpenMOSS/MOSS-TTSD.git
ARG MOSS_TTSD_SGLANG_REPO_URL=https://github.com/OpenMOSS/sglang.git
ARG MOSS_TTSD_SGLANG_BRANCH=moss-ttsd-v1.0-with-cat

RUN git clone --recursive "${MOSS_TTSD_REPO_URL}" /opt/MOSS-TTSD \
    && git clone -b "${MOSS_TTSD_SGLANG_BRANCH}" "${MOSS_TTSD_SGLANG_REPO_URL}" /opt/sglang

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=20 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --upgrade --retries 20 --timeout 180 pip "setuptools<82" wheel \
    && python3 -m pip install --prefer-binary --retries 20 --timeout 180 --extra-index-url https://download.pytorch.org/whl/cu128 -r /opt/MOSS-TTSD/requirements.txt \
    && python3 -m pip install --prefer-binary --retries 20 --timeout 180 -e "/opt/sglang/python[all]" \
    && python3 -m pip install --prefer-binary --retries 20 --timeout 180 nvidia-cudnn-cu12==9.16.0.29 huggingface_hub modelscope \
    && rm -rf /opt/conda/lib/python3.11/site-packages/deep_gemm

COPY deploy/moss-tts/start-moss-tts.sh /opt/roughcut-moss-tts/start-moss-tts.sh
RUN chmod +x /opt/roughcut-moss-tts/start-moss-tts.sh

EXPOSE 30000

ENTRYPOINT ["bash", "/opt/roughcut-moss-tts/start-moss-tts.sh"]
