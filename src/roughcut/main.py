from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from roughcut.api.router import api_router
from roughcut.config import get_settings
from roughcut.runtime_health import build_readiness_payload


def _resolve_frontend_dist() -> Path:
    candidates: list[Path] = []

    configured = os.getenv("ROUGHCUT_FRONTEND_DIST")
    if configured:
        candidates.append(Path(configured).expanduser())

    module_path = Path(__file__).resolve()
    candidates.extend(parent / "frontend" / "dist" for parent in module_path.parents)
    candidates.append(Path.cwd() / "frontend" / "dist")

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / "index.html").exists():
            return resolved

    return candidates[0].resolve() if candidates else Path.cwd() / "frontend" / "dist"


def _frontend_not_built_response() -> HTMLResponse:
    return HTMLResponse(
        "<h1>RoughCut frontend not built</h1><p>Run <code>npm install && npm run build</code> in <code>frontend/</code>.</p>",
        status_code=503,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure host-backed job storage exists on startup
    from roughcut.storage.s3 import get_storage
    from roughcut.docker_gpu_guard import adopt_running_idle_managed_gpu_services

    try:
        storage = get_storage()
        storage.ensure_bucket()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not initialize S3 storage: {e}")
    try:
        await asyncio.to_thread(adopt_running_idle_managed_gpu_services, reason="api_startup")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not adopt running managed GPU services: {e}")
    yield


def create_app() -> FastAPI:
    get_settings()
    app = FastAPI(
        title="RoughCut API",
        description="Automated video editing and subtitle review",
        version="0.1.5",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        payload = await build_readiness_payload()
        status_code = 200 if payload["status"] == "ready" else 503
        return JSONResponse(payload, status_code=status_code)

    def _index_response():
        frontend_dist = _resolve_frontend_dist()
        index_path = frontend_dist / "index.html"
        if not index_path.exists():
            return _frontend_not_built_response()

        response = FileResponse(index_path)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.get("/", include_in_schema=False)
    async def frontend_root():
        return _index_response()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_app(full_path: str):
        if full_path.startswith("api/") or full_path in {"health", "healthz", "readyz"}:
            return HTMLResponse(status_code=404, content="Not Found")
        frontend_dist = _resolve_frontend_dist()
        candidate = (frontend_dist / full_path).resolve()
        if frontend_dist.exists() and frontend_dist in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        if (frontend_dist / "index.html").exists():
            return _index_response()
        return _frontend_not_built_response()

    return app


app = create_app()
