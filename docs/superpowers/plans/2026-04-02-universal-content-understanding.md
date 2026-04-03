# Universal Content Understanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace RoughCut's rule-first `content_profile` pipeline with a universal LLM-first content understanding framework backed by hybrid online search and internal database verification.

**Architecture:** Introduce a new `content_understanding` schema and split the current monolithic `content_profile` logic into explicit stages: evidence bundle, primary LLM inference, hybrid retrieval verification, conservative finalization, and compatibility mapping. Preserve existing APIs and UI through a compatibility layer while progressively removing legacy rule injections such as hard-coded EDC subject types.

**Tech Stack:** Python, FastAPI, SQLAlchemy, existing reasoning/search providers, React/TypeScript frontend, pytest

---

## Parallelization Note

Execution should be organized as one short serial bootstrap task followed by three parallel tracks:

- Track A: universal schema and compatibility mapping
- Track B: evidence bundle module
- Track C: LLM inference module
- Track D: hybrid verification module

After those merge, finish with API/UI adoption and regression coverage.

### Task 1: Bootstrap Universal Schema

**Files:**
- Create: `src/roughcut/review/content_understanding_schema.py`
- Modify: `src/roughcut/api/schemas.py`
- Modify: `frontend/src/types.ts`
- Test: `tests/test_content_understanding_schema.py`

- [ ] **Step 1: Write the failing schema test**

```python
from roughcut.review.content_understanding_schema import (
    ContentUnderstanding,
    SubjectEntity,
    map_content_understanding_to_legacy_profile,
)


def test_map_content_understanding_to_legacy_profile_keeps_non_product_subjects_sparse():
    understanding = ContentUnderstanding(
        video_type="tutorial",
        content_domain="ai",
        primary_subject="ComfyUI 工作流",
        subject_entities=[
            SubjectEntity(kind="software", name="ComfyUI", brand="", model="工作流")
        ],
        video_theme="ComfyUI 节点编排与工作流实操",
        summary="这条视频主要演示 ComfyUI 工作流搭建和节点编排。",
        hook_line="工作流直接讲透",
        engagement_question="你更想看哪类节点工作流？",
        search_queries=["ComfyUI workflow", "ComfyUI 节点编排"],
        evidence_spans=[],
        uncertainties=[],
        confidence={"overall": 0.82},
        needs_review=False,
        review_reasons=[],
    )

    legacy = map_content_understanding_to_legacy_profile(understanding)

    assert legacy["content_kind"] == "tutorial"
    assert legacy["subject_domain"] == "ai"
    assert legacy["subject_type"] == "ComfyUI 工作流"
    assert legacy["subject_brand"] == ""
    assert legacy["subject_model"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_schema.py::test_map_content_understanding_to_legacy_profile_keeps_non_product_subjects_sparse -v`
Expected: FAIL with `ModuleNotFoundError` or missing symbol errors for `content_understanding_schema`

- [ ] **Step 3: Write the minimal schema and mapping implementation**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SubjectEntity:
    kind: str
    name: str
    brand: str = ""
    model: str = ""


@dataclass(frozen=True)
class ContentUnderstanding:
    video_type: str
    content_domain: str
    primary_subject: str
    subject_entities: list[SubjectEntity] = field(default_factory=list)
    video_theme: str = ""
    summary: str = ""
    hook_line: str = ""
    engagement_question: str = ""
    search_queries: list[str] = field(default_factory=list)
    evidence_spans: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)
    needs_review: bool = True
    review_reasons: list[str] = field(default_factory=list)


def map_content_understanding_to_legacy_profile(value: ContentUnderstanding) -> dict[str, Any]:
    subject_type = value.primary_subject or (value.subject_entities[0].name if value.subject_entities else "")
    return {
        "content_kind": value.video_type,
        "subject_domain": value.content_domain,
        "subject_brand": "",
        "subject_model": "",
        "subject_type": subject_type,
        "video_theme": value.video_theme,
        "summary": value.summary,
        "hook_line": value.hook_line,
        "engagement_question": value.engagement_question,
        "search_queries": list(value.search_queries),
        "content_understanding": {
            "video_type": value.video_type,
            "content_domain": value.content_domain,
            "primary_subject": value.primary_subject,
            "subject_entities": [entity.__dict__ for entity in value.subject_entities],
            "video_theme": value.video_theme,
            "summary": value.summary,
            "hook_line": value.hook_line,
            "engagement_question": value.engagement_question,
            "search_queries": list(value.search_queries),
            "evidence_spans": list(value.evidence_spans),
            "uncertainties": list(value.uncertainties),
            "confidence": dict(value.confidence),
            "needs_review": value.needs_review,
            "review_reasons": list(value.review_reasons),
        },
    }
```

- [ ] **Step 4: Extend API and frontend types**

```python
class ContentUnderstandingPayload(BaseModel):
    video_type: str = ""
    content_domain: str = ""
    primary_subject: str = ""
    subject_entities: list[dict[str, Any]] = Field(default_factory=list)
    video_theme: str = ""
    summary: str = ""
    hook_line: str = ""
    engagement_question: str = ""
    search_queries: list[str] = Field(default_factory=list)
    evidence_spans: list[dict[str, Any]] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)
    needs_review: bool = True
    review_reasons: list[str] = Field(default_factory=list)
```

```ts
export interface ContentUnderstanding {
  video_type: string;
  content_domain: string;
  primary_subject: string;
  subject_entities: Record<string, any>[];
  video_theme: string;
  summary: string;
  hook_line: string;
  engagement_question: string;
  search_queries: string[];
  evidence_spans: Record<string, any>[];
  uncertainties: string[];
  confidence: Record<string, number>;
  needs_review: boolean;
  review_reasons: string[];
}
```

- [ ] **Step 5: Run tests to verify the bootstrap passes**

Run: `pytest tests/test_content_understanding_schema.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_content_understanding_schema.py src/roughcut/review/content_understanding_schema.py src/roughcut/api/schemas.py frontend/src/types.ts
git commit -m "refactor: add universal content understanding schema"
```

### Task 2: Replace Rule Injection with Evidence Bundle

**Files:**
- Create: `src/roughcut/review/content_understanding_evidence.py`
- Test: `tests/test_content_understanding_evidence.py`

- [ ] **Step 1: Write the failing evidence test**

```python
from roughcut.review.content_understanding_evidence import build_evidence_bundle


def test_build_evidence_bundle_does_not_emit_final_subject_type():
    bundle = build_evidence_bundle(
        source_name="IMG_1234.mp4",
        subtitle_items=[{"text_final": "今天看下这个包的分仓和挂点", "start_time": 0.0, "end_time": 2.0}],
        transcript_excerpt="[0.0-2.0] 今天看下这个包的分仓和挂点",
        visible_text="FXX1",
        ocr_profile={"visible_text": "FXX1"},
        visual_hints={"subject_type": "EDC机能包", "visible_text": "FXX1"},
    )

    assert bundle["transcript_excerpt"]
    assert bundle["visible_text"] == "FXX1"
    assert "subject_type" not in bundle
    assert bundle["candidate_hints"]["visual_hints"]["subject_type"] == "EDC机能包"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_evidence.py::test_build_evidence_bundle_does_not_emit_final_subject_type -v`
Expected: FAIL because `build_evidence_bundle` does not exist

- [ ] **Step 3: Implement the evidence bundle builder**

```python
def build_evidence_bundle(
    *,
    source_name: str,
    subtitle_items: list[dict[str, Any]],
    transcript_excerpt: str,
    visible_text: str,
    ocr_profile: dict[str, Any] | None,
    visual_hints: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "source_name": source_name,
        "transcript_excerpt": transcript_excerpt,
        "subtitle_items": list(subtitle_items),
        "visible_text": visible_text,
        "ocr_profile": dict(ocr_profile or {}),
        "candidate_hints": {
            "visual_hints": dict(visual_hints or {}),
        },
    }
```

- [ ] **Step 4: Add normalization helpers needed by later integration**

```python
def normalize_evidence_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    transcript_excerpt = str(bundle.get("transcript_excerpt") or "").strip()
    visible_text = str(bundle.get("visible_text") or "").strip()
    subtitle_items = [dict(item) for item in bundle.get("subtitle_items") or [] if isinstance(item, dict)]
    return {
        "source_name": str(bundle.get("source_name") or "").strip(),
        "transcript_excerpt": transcript_excerpt,
        "subtitle_items": subtitle_items,
        "visible_text": visible_text,
        "ocr_profile": dict(bundle.get("ocr_profile") or {}),
        "candidate_hints": dict(bundle.get("candidate_hints") or {}),
    }
```

- [ ] **Step 5: Run focused evidence tests**

Run: `pytest tests/test_content_understanding_evidence.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_content_understanding_evidence.py src/roughcut/review/content_understanding_evidence.py
git commit -m "refactor: add content evidence bundle module"
```

### Task 3: Add LLM-First Universal Inference

**Files:**
- Create: `src/roughcut/review/content_understanding_infer.py`
- Test: `tests/test_content_understanding_infer.py`

- [ ] **Step 1: Write the failing inference test**

```python
import pytest

from roughcut.review.content_understanding_infer import infer_content_understanding


@pytest.mark.asyncio
async def test_infer_content_understanding_uses_llm_output_as_primary_result(monkeypatch):
    class DummyProvider:
        async def complete(self, messages, temperature, max_tokens, json_mode):
            class Response:
                def as_json(self):
                    return {
                        "video_type": "tutorial",
                        "content_domain": "ai",
                        "primary_subject": "ComfyUI 工作流",
                        "subject_entities": [{"kind": "software", "name": "ComfyUI"}],
                        "video_theme": "ComfyUI 节点编排与工作流实操",
                        "summary": "这条视频主要演示 ComfyUI 工作流搭建。",
                        "hook_line": "工作流直接讲透",
                        "engagement_question": "你还想看哪类节点编排？",
                        "search_queries": ["ComfyUI workflow", "ComfyUI 节点编排"],
                        "evidence_spans": [{"source": "transcript", "text": "节点编排"}],
                        "uncertainties": [],
                        "confidence": {"overall": 0.87},
                        "needs_review": False,
                        "review_reasons": [],
                    }
            return Response()

    monkeypatch.setattr("roughcut.review.content_understanding_infer.get_reasoning_provider", lambda: DummyProvider())

    result = await infer_content_understanding({"transcript_excerpt": "今天演示 ComfyUI 节点编排"})

    assert result.video_type == "tutorial"
    assert result.content_domain == "ai"
    assert result.primary_subject == "ComfyUI 工作流"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_infer.py::test_infer_content_understanding_uses_llm_output_as_primary_result -v`
Expected: FAIL because `infer_content_understanding` does not exist

- [ ] **Step 3: Implement the LLM-first inference module**

```python
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message
from roughcut.review.content_understanding_schema import ContentUnderstanding, SubjectEntity


async def infer_content_understanding(evidence_bundle: dict[str, Any]) -> ContentUnderstanding:
    provider = get_reasoning_provider()
    prompt = (
        "你是 RoughCut 的通用视频理解中枢。"
        "请基于当前视频证据输出视频形式、内容领域、主体、主题、摘要和检索查询。"
        "不得凭历史记忆或风格模板硬猜具体类型；若证据不足则显式 needs_review=true。"
        f"\n证据包：{json.dumps(evidence_bundle, ensure_ascii=False)}"
    )
    response = await provider.complete(
        [Message(role="system", content="你是严谨的中文视频内容理解助手。"), Message(role="user", content=prompt)],
        temperature=0.1,
        max_tokens=900,
        json_mode=True,
    )
    data = response.as_json()
    return ContentUnderstanding(
        video_type=str(data.get("video_type") or ""),
        content_domain=str(data.get("content_domain") or ""),
        primary_subject=str(data.get("primary_subject") or ""),
        subject_entities=[SubjectEntity(**item) for item in data.get("subject_entities") or []],
        video_theme=str(data.get("video_theme") or ""),
        summary=str(data.get("summary") or ""),
        hook_line=str(data.get("hook_line") or ""),
        engagement_question=str(data.get("engagement_question") or ""),
        search_queries=[str(item).strip() for item in data.get("search_queries") or [] if str(item).strip()],
        evidence_spans=list(data.get("evidence_spans") or []),
        uncertainties=[str(item).strip() for item in data.get("uncertainties") or [] if str(item).strip()],
        confidence=dict(data.get("confidence") or {}),
        needs_review=bool(data.get("needs_review")),
        review_reasons=[str(item).strip() for item in data.get("review_reasons") or [] if str(item).strip()],
    )
```

- [ ] **Step 4: Add parser helper for deterministic payload normalization**

```python
def parse_content_understanding_payload(data: dict[str, Any]) -> ContentUnderstanding:
    return ContentUnderstanding(
        video_type=str(data.get("video_type") or ""),
        content_domain=str(data.get("content_domain") or ""),
        primary_subject=str(data.get("primary_subject") or ""),
        subject_entities=[SubjectEntity(**item) for item in data.get("subject_entities") or [] if isinstance(item, dict)],
        video_theme=str(data.get("video_theme") or ""),
        summary=str(data.get("summary") or ""),
        hook_line=str(data.get("hook_line") or ""),
        engagement_question=str(data.get("engagement_question") or ""),
        search_queries=[str(item).strip() for item in data.get("search_queries") or [] if str(item).strip()],
        evidence_spans=[dict(item) for item in data.get("evidence_spans") or [] if isinstance(item, dict)],
        uncertainties=[str(item).strip() for item in data.get("uncertainties") or [] if str(item).strip()],
        confidence={str(key): float(value) for key, value in dict(data.get("confidence") or {}).items()},
        needs_review=bool(data.get("needs_review")),
        review_reasons=[str(item).strip() for item in data.get("review_reasons") or [] if str(item).strip()],
    )
```

- [ ] **Step 5: Run focused inference tests**

Run: `pytest tests/test_content_understanding_infer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_content_understanding_infer.py src/roughcut/review/content_understanding_infer.py
git commit -m "refactor: make content understanding llm-first"
```

### Task 4: Add Hybrid Online and Database Verification

**Files:**
- Create: `src/roughcut/review/content_understanding_verify.py`
- Create: `src/roughcut/review/content_understanding_retrieval.py`
- Test: `tests/test_content_understanding_verify.py`

- [ ] **Step 1: Write the failing hybrid verification test**

```python
import pytest

from roughcut.review.content_understanding_verify import build_hybrid_verification_bundle


@pytest.mark.asyncio
async def test_build_hybrid_verification_bundle_combines_online_and_database_hits(monkeypatch):
    async def fake_online(*args, **kwargs):
        return [{"title": "ComfyUI 官方文档", "url": "https://example.com/comfyui"}]

    async def fake_internal(*args, **kwargs):
        return [{"job_id": "job-1", "primary_subject": "ComfyUI 工作流", "confirmed": True}]

    bundle = await build_hybrid_verification_bundle(
        search_queries=["ComfyUI workflow"],
        online_search=fake_online,
        internal_search=fake_internal,
    )

    assert bundle["online_results"][0]["title"] == "ComfyUI 官方文档"
    assert bundle["database_results"][0]["primary_subject"] == "ComfyUI 工作流"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_verify.py::test_build_hybrid_verification_bundle_combines_online_and_database_hits -v`
Expected: FAIL because `build_hybrid_verification_bundle` does not exist

- [ ] **Step 3: Implement hybrid verification bundle creation**

```python
async def build_hybrid_verification_bundle(
    *,
    search_queries: list[str],
    online_search: Callable[..., Awaitable[list[dict[str, Any]]]],
    internal_search: Callable[..., Awaitable[list[dict[str, Any]]]],
) -> dict[str, Any]:
    online_results = await online_search(search_queries=search_queries)
    database_results = await internal_search(search_queries=search_queries)
    return {
        "queries": list(search_queries),
        "online_results": list(online_results),
        "database_results": list(database_results),
}
```

- [ ] **Step 4: Implement LLM-based verification finalization**

```python
async def verify_content_understanding(
    *,
    understanding: ContentUnderstanding,
    evidence_bundle: dict[str, Any],
    verification_bundle: dict[str, Any],
) -> ContentUnderstanding:
    provider = get_reasoning_provider()
    prompt = (
        "你要验证一条视频理解结果。"
        "联网搜索和数据库结果都只是弱佐证，不能覆盖当前视频直接证据。"
        "如果冲突明显，请清空冲突字段并设置 needs_review=true。"
        f"\n原始理解：{json.dumps(map_content_understanding_to_legacy_profile(understanding), ensure_ascii=False)}"
        f"\n当前视频证据：{json.dumps(evidence_bundle, ensure_ascii=False)}"
        f"\n混合检索结果：{json.dumps(verification_bundle, ensure_ascii=False)}"
    )
    response = await provider.complete(
        [Message(role="system", content="你是严谨的中文视频理解校验助手。"), Message(role="user", content=prompt)],
        temperature=0.1,
        max_tokens=700,
        json_mode=True,
    )
    data = response.as_json()
    return parse_content_understanding_payload(data)
```

- [ ] **Step 5: Add internal database retrieval helper**

```python
async def search_confirmed_content_entities(
    session: AsyncSession,
    *,
    search_queries: list[str],
) -> list[dict[str, Any]]:
    normalized = [str(item).strip().lower() for item in search_queries if str(item).strip()]
    if not normalized:
        return []
    rows = await session.execute(
        select(ContentProfileEntity)
        .where(ContentProfileEntity.subject_type.is_not(None))
        .limit(20)
    )
    results: list[dict[str, Any]] = []
    for entity in rows.scalars():
        haystack = " ".join(
            part for part in (
                str(entity.brand or ""),
                str(entity.model or ""),
                str(entity.subject_type or ""),
            ) if part
        ).lower()
        if any(query in haystack for query in normalized):
            results.append(
                {
                    "entity_id": str(entity.id),
                    "brand": str(entity.brand or ""),
                    "model": str(entity.model or ""),
                    "subject_type": str(entity.subject_type or ""),
                    "confirmed": True,
                }
            )
    return results
```

- [ ] **Step 6: Run verification tests**

Run: `pytest tests/test_content_understanding_verify.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tests/test_content_understanding_verify.py src/roughcut/review/content_understanding_verify.py src/roughcut/review/content_understanding_retrieval.py
git commit -m "feat: add hybrid verification for content understanding"
```

### Task 5: Adopt Compatibility Layer in API, UI, and Regression Tests

**Files:**
- Modify: `src/roughcut/review/content_profile.py`
- Modify: `src/roughcut/api/jobs.py`
- Modify: `frontend/src/features/jobs/JobContentProfileSection.tsx`
- Modify: `frontend/src/features/jobs/constants.ts`
- Modify: `frontend/src/i18n.tsx`
- Modify: `tests/test_content_profile.py`
- Modify: `tests/test_api_health.py`
- Modify: `tests/test_usage.py`
- Modify: `tests/test_telegram_review_bot.py`

- [ ] **Step 1: Write the failing API regression test**

```python
async def test_content_profile_endpoint_returns_content_understanding_payload(client: AsyncClient):
    response = await client.get(f"/jobs/{job_id}/content-profile")
    assert response.status_code == 200
    payload = response.json()
    assert "content_understanding" in payload["draft"]
    assert payload["draft"]["content_understanding"]["video_type"] == "tutorial"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_health.py::test_content_profile_endpoint_returns_content_understanding_payload -v`
Expected: FAIL because `content_understanding` is absent from the response

- [ ] **Step 3: Return compatibility payload from API**

```python
draft = apply_current_content_profile_review_policy(draft, settings=settings)
if isinstance(draft, dict) and "content_understanding" not in draft:
    draft["content_understanding"] = {
        "video_type": str(draft.get("content_kind") or ""),
        "content_domain": str(draft.get("subject_domain") or ""),
        "primary_subject": str(draft.get("subject_type") or ""),
        "subject_entities": [],
        "video_theme": str(draft.get("video_theme") or ""),
        "summary": str(draft.get("summary") or ""),
        "hook_line": str(draft.get("hook_line") or ""),
        "engagement_question": str(draft.get("engagement_question") or ""),
        "search_queries": list(draft.get("search_queries") or []),
        "evidence_spans": [],
        "uncertainties": [],
        "confidence": {},
        "needs_review": bool(draft.get("review_required")),
        "review_reasons": list(draft.get("review_reasons") or []),
    }
```

- [ ] **Step 4: Integrate evidence, inference, and verification into `content_profile.py`**

```python
transcript_excerpt = build_transcript_excerpt(subtitle_items)
evidence_bundle = build_evidence_bundle(
    source_name=source_name,
    subtitle_items=subtitle_items,
    transcript_excerpt=transcript_excerpt,
    visible_text=str(initial_profile.get("visible_text") or ""),
    ocr_profile=initial_profile.get("ocr_profile") if isinstance(initial_profile.get("ocr_profile"), dict) else {},
    visual_hints=initial_profile.get("visual_cluster_hints") if isinstance(initial_profile.get("visual_cluster_hints"), dict) else {},
)
understanding = await infer_content_understanding(evidence_bundle)
verification_bundle = await build_hybrid_verification_bundle(
    search_queries=understanding.search_queries,
    online_search=_online_search_content_understanding,
    internal_search=_database_search_content_understanding,
)
understanding = await verify_content_understanding(
    understanding=understanding,
    evidence_bundle=evidence_bundle,
    verification_bundle=verification_bundle,
)
profile = map_content_understanding_to_legacy_profile(understanding)
profile["transcript_excerpt"] = transcript_excerpt
```

- [ ] **Step 5: Surface universal fields in UI without breaking legacy labels**

```tsx
const understanding = profile.content_understanding;
const videoType = understanding?.video_type || profile.content_kind || "";
const contentDomain = understanding?.content_domain || profile.subject_domain || "";
const primarySubject = understanding?.primary_subject || profile.subject_type || "";
```

- [ ] **Step 6: Update regression tests away from hard-coded rule-injection expectations**

```python
def test_seed_profile_from_text_no_longer_forces_edc_flashlight_subject_type():
    profile = map_content_understanding_to_legacy_profile(
        ContentUnderstanding(
            video_type="mixed",
            content_domain="lifestyle",
            primary_subject="背包收纳展示",
            subject_entities=[],
            video_theme="背包分仓与挂点展示",
            summary="这条视频主要展示背包分仓和挂点。",
            hook_line="分仓挂点直接看",
            engagement_question="你更看重分仓还是挂点？",
            search_queries=[],
            evidence_spans=[],
            uncertainties=["缺少品牌型号直证"],
            confidence={"overall": 0.41},
            needs_review=True,
            review_reasons=["当前视频没有足够品牌型号证据"],
        )
    )
    assert profile.get("content_understanding", {}).get("primary_subject", "") != "EDC手电"
```

- [ ] **Step 7: Run focused regression suites**

Run: `pytest tests/test_content_profile.py tests/test_api_health.py tests/test_usage.py tests/test_telegram_review_bot.py -v`
Expected: PASS

- [ ] **Step 8: Run a final integration slice**

Run: `pytest tests/test_content_understanding_schema.py tests/test_content_understanding_evidence.py tests/test_content_understanding_infer.py tests/test_content_understanding_verify.py tests/test_content_profile.py tests/test_api_health.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/roughcut/review/content_profile.py src/roughcut/api/jobs.py frontend/src/features/jobs/JobContentProfileSection.tsx frontend/src/features/jobs/constants.ts frontend/src/i18n.tsx tests/test_content_profile.py tests/test_api_health.py tests/test_usage.py tests/test_telegram_review_bot.py
git commit -m "refactor: adopt universal content understanding across api and ui"
```
