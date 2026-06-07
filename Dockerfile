FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /frontend

RUN corepack enable

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json ./frontend/package.json
RUN pnpm install --frozen-lockfile --filter roughcut-frontend...
COPY frontend ./frontend
RUN pnpm --dir frontend build


FROM docker:cli AS docker-cli


FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_HTTP_TIMEOUT=300
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV UV_CACHE_DIR=/root/.cache/uv
ENV PATH="/app/.venv/bin:${PATH}"
ENV LD_LIBRARY_PATH="/app/.venv/lib/python3.11/site-packages/nvidia/cublas/lib:/app/.venv/lib/python3.11/site-packages/nvidia/cudnn/lib:${LD_LIBRARY_PATH}"
ARG ROUGHCUT_PYTHON_EXTRAS=""
ARG ROUGHCUT_APT_MIRROR="http://mirrors.aliyun.com/debian"
ARG ROUGHCUT_APT_SECURITY_MIRROR="http://mirrors.aliyun.com/debian-security"

WORKDIR /app

RUN set -eux; \
    rm -f /etc/apt/sources.list.d/debian.sources; \
    printf 'deb %s bookworm main\n' "$ROUGHCUT_APT_MIRROR" > /etc/apt/sources.list; \
    printf 'deb %s bookworm-updates main\n' "$ROUGHCUT_APT_MIRROR" >> /etc/apt/sources.list; \
    printf 'deb %s bookworm-security main\n' "$ROUGHCUT_APT_SECURITY_MIRROR" >> /etc/apt/sources.list; \
    for attempt in 1 2 3; do \
        apt-get -o Acquire::Retries=5 update \
        && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
            curl \
            ffmpeg \
            fonts-noto-cjk \
            libglib2.0-0 \
            libsm6 \
            nodejs \
            npm \
            libxext6 \
            libxrender1 \
        && break; \
        if [ "$attempt" -eq 3 ]; then exit 1; fi; \
        apt-get clean; \
        rm -rf /var/lib/apt/lists/*; \
        sleep 5; \
    done; \
    rm -rf /var/lib/apt/lists/*

RUN npm install -g @z_ai/mcp-server@latest

COPY pyproject.toml uv.lock README.md alembic.ini ./

RUN --mount=type=cache,target=/root/.cache/uv if [ -n "${ROUGHCUT_PYTHON_EXTRAS}" ]; then \
        set --; \
        for extra in ${ROUGHCUT_PYTHON_EXTRAS}; do \
            set -- "$@" --extra "${extra}"; \
        done; \
        uv sync --frozen --no-dev --no-install-project "$@"; \
    else \
        uv sync --frozen --no-dev --no-install-project; \
    fi

COPY src ./src
COPY frontend ./frontend
COPY --from=frontend-builder /frontend/frontend/dist ./frontend/dist
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

RUN --mount=type=cache,target=/root/.cache/uv if [ -n "${ROUGHCUT_PYTHON_EXTRAS}" ]; then \
        set --; \
        for extra in ${ROUGHCUT_PYTHON_EXTRAS}; do \
            set -- "$@" --extra "${extra}"; \
        done; \
        uv sync --frozen --no-dev --no-editable "$@"; \
    else \
        uv sync --frozen --no-dev --no-editable; \
    fi

RUN if echo " ${ROUGHCUT_PYTHON_EXTRAS} " | grep -q " local-asr "; then \
        python -c "from pathlib import Path; libs = [Path('/app/.venv/lib/python3.11/site-packages/nvidia/cublas/lib/libcublas.so.12'), Path('/app/.venv/lib/python3.11/site-packages/nvidia/cudnn/lib/libcudnn.so.9')]; missing = [str(path) for path in libs if not path.exists()]; assert not missing, f'Missing CUDA runtime libs: {missing}'"; \
    fi

RUN mkdir -p /app/data/output /app/logs

ENV ROUGHCUT_API_INTERNAL_PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "roughcut api --host 0.0.0.0 --port ${ROUGHCUT_API_INTERNAL_PORT:-8000}"]
