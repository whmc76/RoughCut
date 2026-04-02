# Observed/Resolved Entity Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an observed/resolved entity understanding layer plus a reusable small-sample product benchmark so generic intelligence upgrades are measured across multiple product videos instead of one case.

**Architecture:** Extend `content_understanding` to carry both raw observed entities and retrieval-grounded resolved entities. Keep final legacy fields mapped from the resolved layer when available, and add benchmark tests that validate extraction, resolution, and conservative fallback behavior across several product families.

**Tech Stack:** Python 3.11, SQLAlchemy async, pytest, existing RoughCut reasoning/search providers, ffmpeg-derived local benchmark fixtures metadata

---

### Task 1: Lock Benchmark Sample Metadata

**Files:**
- Create: `tests/fixtures/content_understanding_benchmark_samples.py`
- Test: `tests/test_content_understanding_benchmark.py`

- [ ] **Step 1: Write the failing test**

```python
from tests.fixtures.content_understanding_benchmark_samples import BENCHMARK_SAMPLES


def test_benchmark_samples_cover_multiple_product_families():
    families = {sample["expected_product_family"] for sample in BENCHMARK_SAMPLES}
    assert len(families) >= 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_benchmark.py::test_benchmark_samples_cover_multiple_product_families -v`
Expected: FAIL with missing fixture module or empty sample set.

- [ ] **Step 3: Write minimal implementation**

```python
BENCHMARK_SAMPLES = [
    {"source_name": "IMG_0041.MOV", "expected_product_family": "bag"},
    {"source_name": "20260209-124735.mp4", "expected_product_family": "flashlight"},
    {"source_name": "20260211-123939.mp4", "expected_product_family": "knife"},
    {"source_name": "20260212-141536.mp4", "expected_product_family": "knife_tool"},
    {"source_name": "20260211-120605.mp4", "expected_product_family": "case"},
    {"source_name": "20260213-133009.mp4", "expected_product_family": "accessory_material"},
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_benchmark.py::test_benchmark_samples_cover_multiple_product_families -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/content_understanding_benchmark_samples.py tests/test_content_understanding_benchmark.py
git commit -m "test: add content understanding benchmark sample set"
```

### Task 2: Add Observed/Resolved Schema

**Files:**
- Modify: `src/roughcut/review/content_understanding_schema.py`
- Test: `tests/test_content_understanding_schema.py`

- [ ] **Step 1: Write the failing test**

```python
def test_map_content_understanding_to_legacy_profile_prefers_resolved_entities():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="gear",
        primary_subject="observed alias",
        resolved_primary_subject="resolved subject",
        observed_entities=[SubjectEntity(kind="product", name="船长联名包")],
        resolved_entities=[SubjectEntity(kind="product", name="HSJUN × BOLTBOAT 游刃机能双肩包", brand="HSJUN × BOLTBOAT", model="游刃")],
    )
    profile = map_content_understanding_to_legacy_profile(understanding)
    assert profile["subject_type"] == "HSJUN × BOLTBOAT 游刃机能双肩包"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_schema.py::test_map_content_understanding_to_legacy_profile_prefers_resolved_entities -v`
Expected: FAIL because schema has no resolved layer yet.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class EntityResolution:
    observed_name: str
    resolved_name: str
    confidence: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class ContentUnderstanding:
    ...
    observed_entities: list[SubjectEntity] = field(default_factory=list)
    resolved_entities: list[SubjectEntity] = field(default_factory=list)
    resolved_primary_subject: str = ""
    entity_resolution_map: list[EntityResolution] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_schema.py::test_map_content_understanding_to_legacy_profile_prefers_resolved_entities -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_understanding_schema.py tests/test_content_understanding_schema.py
git commit -m "feat: add observed and resolved entity layers"
```

### Task 3: Extend Inference To Emit Observed Entities

**Files:**
- Modify: `src/roughcut/review/content_understanding_infer.py`
- Test: `tests/test_content_understanding_infer.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_infer_content_understanding_preserves_observed_entities_from_video_language(monkeypatch):
    ...
    assert result.observed_entities[0].name == "船长"
    assert result.resolved_entities == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_infer.py::test_infer_content_understanding_preserves_observed_entities_from_video_language -v`
Expected: FAIL because observed layer is not parsed.

- [ ] **Step 3: Write minimal implementation**

```python
def parse_content_understanding_payload(data: Any) -> ContentUnderstanding:
    observed_entities = _parse_entity_list(payload.get("observed_entities"))
    resolved_entities = _parse_entity_list(payload.get("resolved_entities"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_infer.py::test_infer_content_understanding_preserves_observed_entities_from_video_language -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_understanding_infer.py tests/test_content_understanding_infer.py
git commit -m "feat: preserve observed entities in content understanding"
```

### Task 4: Add Retrieval-Grounded Resolution

**Files:**
- Modify: `src/roughcut/review/content_understanding_verify.py`
- Test: `tests/test_content_understanding_verify.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_verify_content_understanding_can_promote_resolved_entity_over_observed_alias():
    ...
    assert result.resolved_primary_subject == "HSJUN × BOLTBOAT 游刃机能双肩包"
    assert result.primary_subject == "HSJUN × BOLTBOAT 游刃机能双肩包"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_verify.py::test_verify_content_understanding_can_promote_resolved_entity_over_observed_alias -v`
Expected: FAIL because verify currently only preserves base understanding.

- [ ] **Step 3: Write minimal implementation**

```python
candidate = parse_content_understanding_payload(response.as_json())
resolved_subject = candidate.resolved_primary_subject or candidate.primary_subject
return replace(
    base,
    primary_subject=resolved_subject or base.primary_subject,
    resolved_primary_subject=resolved_subject,
    resolved_entities=candidate.resolved_entities or base.resolved_entities,
    entity_resolution_map=candidate.entity_resolution_map or base.entity_resolution_map,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_verify.py::test_verify_content_understanding_can_promote_resolved_entity_over_observed_alias -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_understanding_verify.py tests/test_content_understanding_verify.py
git commit -m "feat: resolve observed entities through hybrid verification"
```

### Task 5: Keep Weak Resolution Conservative

**Files:**
- Modify: `src/roughcut/review/content_understanding_verify.py`
- Test: `tests/test_content_understanding_verify.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_verify_content_understanding_keeps_observed_entity_when_resolution_is_weak():
    ...
    assert result.primary_subject == "船长联名包"
    assert result.needs_review is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_verify.py::test_verify_content_understanding_keeps_observed_entity_when_resolution_is_weak -v`
Expected: FAIL because weak resolution is not distinguished yet.

- [ ] **Step 3: Write minimal implementation**

```python
if candidate.confidence.get("resolution", 0.0) < 0.7:
    resolved_subject = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_verify.py::test_verify_content_understanding_keeps_observed_entity_when_resolution_is_weak -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_understanding_verify.py tests/test_content_understanding_verify.py
git commit -m "fix: keep weak entity resolution in review state"
```

### Task 6: Integrate Legacy Mapping And Cache Bust

**Files:**
- Modify: `src/roughcut/review/content_profile.py`
- Test: `tests/test_content_profile.py`
- Test: `tests/test_pipeline_steps.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_content_profile_cache_fingerprint_bumps_when_resolution_framework_changes():
    fingerprint = build_content_profile_cache_fingerprint(...)
    assert fingerprint["version"].startswith("2026-04-03.infer.v8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_profile.py::test_build_content_profile_cache_fingerprint_bumps_when_resolution_framework_changes -v`
Expected: FAIL because cache version is older.

- [ ] **Step 3: Write minimal implementation**

```python
_CONTENT_PROFILE_INFER_CACHE_VERSION = "2026-04-03.infer.v8"
_CONTENT_PROFILE_ENRICH_CACHE_VERSION = "2026-04-03.enrich.v8"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_profile.py::test_build_content_profile_cache_fingerprint_bumps_when_resolution_framework_changes -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_profile.py tests/test_content_profile.py tests/test_pipeline_steps.py
git commit -m "refactor: map content profile from resolved entities"
```

### Task 7: Add Benchmark Comparison Test

**Files:**
- Create: `tests/test_content_understanding_benchmark.py`
- Modify: `tests/fixtures/content_understanding_benchmark_samples.py`

- [ ] **Step 1: Write the failing test**

```python
def test_benchmark_expected_families_are_distinguishable():
    assert summarize_benchmark_families(BENCHMARK_SAMPLES) == {
        "bag", "flashlight", "knife", "knife_tool", "case", "accessory_material"
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_benchmark.py -v`
Expected: FAIL because helper or sample metadata is incomplete.

- [ ] **Step 3: Write minimal implementation**

```python
def summarize_benchmark_families(samples):
    return {sample["expected_product_family"] for sample in samples}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_benchmark.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_content_understanding_benchmark.py tests/fixtures/content_understanding_benchmark_samples.py
git commit -m "test: add product benchmark comparison coverage"
```

### Task 8: Full Regression And Live Recheck

**Files:**
- Modify: none
- Test: `tests/test_content_understanding_infer.py`
- Test: `tests/test_content_understanding_verify.py`
- Test: `tests/test_content_profile.py`
- Test: `tests/test_pipeline_steps.py`
- Test: `tests/test_content_understanding_benchmark.py`

- [ ] **Step 1: Run focused regression**

Run:

```bash
pytest tests/test_content_understanding_infer.py tests/test_content_understanding_verify.py tests/test_content_profile.py tests/test_pipeline_steps.py tests/test_content_understanding_benchmark.py -k "content_understanding or content_profile or benchmark" -v
```

Expected: all selected tests PASS.

- [ ] **Step 2: Re-run live sample**

Run the isolated `content_profile -> summary_review` rerun flow for `1dbbbf9e-5e7c-4bc7-b014-43bd2668f981` and confirm the API returns non-empty `observed_entities`, `resolved_entities`, and `content_understanding`.

- [ ] **Step 3: Record benchmark comparison result**

Capture for each benchmark sample:

```text
source_name
expected_product_family
observed_entities
resolved_entities
resolved_primary_subject
video_theme
needs_review
```

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "feat: add observed resolved entity benchmark framework"
```
