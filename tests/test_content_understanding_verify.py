from __future__ import annotations

from types import SimpleNamespace

import pytest

from roughcut.review.content_understanding_verify import build_hybrid_verification_bundle


@pytest.mark.asyncio
async def test_build_hybrid_verification_bundle_keeps_online_and_database_hits():
    async def fake_online(*, search_queries):
        assert search_queries == ["ComfyUI workflow"]
        return [SimpleNamespace(title="ComfyUI 官方文档")]

    async def fake_internal(*, search_queries):
        assert search_queries == ["ComfyUI workflow"]
        return [SimpleNamespace(primary_subject="ComfyUI 工作流")]

    bundle = await build_hybrid_verification_bundle(
        search_queries=["ComfyUI workflow"],
        online_search=fake_online,
        internal_search=fake_internal,
    )

    assert bundle.online_results[0].title == "ComfyUI 官方文档"
    assert bundle.database_results[0].primary_subject == "ComfyUI 工作流"
