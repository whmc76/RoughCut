from __future__ import annotations

from fastapi import APIRouter

from roughcut.api.control import router as control_router
from roughcut.api.config import router as config_router
from roughcut.api.glossary import router as glossary_router
from roughcut.api.jobs import router as jobs_router
from roughcut.api.review import router as watch_roots_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(jobs_router)
api_router.include_router(glossary_router)
api_router.include_router(watch_roots_router)
api_router.include_router(config_router)
api_router.include_router(control_router)
