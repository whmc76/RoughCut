from __future__ import annotations

from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from fastcut.api.router import api_router
from fastcut.config import get_settings

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure MinIO bucket exists on startup
    from fastcut.storage.s3 import get_storage
    try:
        storage = get_storage()
        storage.ensure_bucket()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not initialize S3 storage: {e}")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="FastCut API",
        description="Automated video editing and subtitle review",
        version="0.1.0",
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

    # Serve frontend
    if _STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")

    return app


app = create_app()
