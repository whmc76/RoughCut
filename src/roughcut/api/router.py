from __future__ import annotations

from fastapi import APIRouter

from roughcut.api.avatar_materials import router as avatar_materials_router
from roughcut.api.control import router as control_router
from roughcut.api.config import router as config_router
from roughcut.api.creator_assets import router as creator_assets_router
from roughcut.api.glossary import router as glossary_router
from roughcut.api.health import router as health_router
from roughcut.api.intelligent_copy import router as intelligent_copy_router
from roughcut.api.jobs import router as jobs_router
from roughcut.api.learned_hotwords import router as learned_hotwords_router
from roughcut.api.packaging import router as packaging_router
from roughcut.api.review import router as watch_roots_router
from roughcut.api.tools import router as tools_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(creator_assets_router)
api_router.include_router(avatar_materials_router)
api_router.include_router(jobs_router)
api_router.include_router(glossary_router)
api_router.include_router(learned_hotwords_router)
api_router.include_router(watch_roots_router)
api_router.include_router(packaging_router)
api_router.include_router(intelligent_copy_router)
api_router.include_router(config_router)
api_router.include_router(control_router)
api_router.include_router(health_router)
api_router.include_router(tools_router)
