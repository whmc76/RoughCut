from __future__ import annotations

from fastapi import APIRouter

from fastcut.api.config import router as config_router
from fastcut.api.glossary import router as glossary_router
from fastcut.api.jobs import router as jobs_router
from fastcut.api.review import router as watch_roots_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(jobs_router)
api_router.include_router(glossary_router)
api_router.include_router(watch_roots_router)
api_router.include_router(config_router)
