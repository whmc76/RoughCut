FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /frontend

RUN corepack enable

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json ./frontend/package.json
RUN pnpm install --frozen-lockfile --filter roughcut-frontend...
COPY frontend ./frontend
RUN pnpm --dir frontend build


FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:${PATH}"
ARG ROUGHCUT_PYTHON_EXTRAS=""

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
        fonts-noto-cjk \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY frontend ./frontend
COPY --from=frontend-builder /frontend/frontend/dist ./frontend/dist

RUN if [ -n "${ROUGHCUT_PYTHON_EXTRAS}" ]; then \
        set --; \
        for extra in ${ROUGHCUT_PYTHON_EXTRAS}; do \
            set -- "$@" --extra "${extra}"; \
        done; \
        uv sync --frozen --no-dev "$@"; \
    else \
        uv sync --frozen --no-dev; \
    fi

RUN mkdir -p /app/data/output /app/logs

EXPOSE 8000

CMD ["roughcut", "api", "--host", "0.0.0.0", "--port", "8000"]
