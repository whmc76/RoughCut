# Capability Matrix Content Understanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild RoughCut content understanding into a capability-matrix-driven, multimodal framework where ASR and vision are both primary evidence, resolution is adaptive, and final judgments remain LLM-only.

**Architecture:** Introduce a capability router plus structured evidence/fact layers ahead of final understanding. Default to a three-stage path, only escalate to entity resolution when evidence conflicts or aliases remain unstable, and keep all final user-facing fields derived from LLM outputs with explicit `observed / resolved / conflicts` traceability.

**Tech Stack:** Python 3.11, SQLAlchemy async, pytest, existing RoughCut reasoning/search/OCR/transcription providers, multimodal provider adapters, ffmpeg-based frame extraction

---

### Task 1: Define Capability Matrix Contracts

**Files:**
- Create: `src/roughcut/review/content_understanding_capabilities.py`
- Modify: `src/roughcut/config.py`
- Test: `tests/test_content_understanding_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
from roughcut.review.content_understanding_capabilities import resolve_content_understanding_capabilities


def test_resolve_content_understanding_capabilities_prefers_native_multimodal_over_visual_mcp():
    capabilities = resolve_content_understanding_capabilities(
        reasoning_provider="minimax",
        visual_provider="minimax",
        visual_mcp_provider="mcp:minimax-vision",
    )
    assert capabilities["visual_understanding"]["mode"] == "native_multimodal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_capabilities.py::test_resolve_content_understanding_capabilities_prefers_native_multimodal_over_visual_mcp -v`
Expected: FAIL because the capability resolver module does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def resolve_content_understanding_capabilities(
    *,
    reasoning_provider: str,
    visual_provider: str,
    visual_mcp_provider: str | None = None,
):
    if provider_supports_native_multimodal(visual_provider):
        visual_mode = {"provider": visual_provider, "mode": "native_multimodal"}
    elif visual_mcp_provider:
        visual_mode = {"provider": visual_mcp_provider, "mode": "mcp"}
    else:
        visual_mode = {"provider": "", "mode": "unavailable"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_capabilities.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_understanding_capabilities.py src/roughcut/config.py tests/test_content_understanding_capabilities.py
git commit -m "feat: add content understanding capability matrix"
```

### Task 2: Promote Visual Understanding From Hints To Evidence

**Files:**
- Modify: `src/roughcut/review/content_profile.py`
- Modify: `src/roughcut/review/content_understanding_evidence.py`
- Test: `tests/test_content_understanding_evidence.py`

- [ ] **Step 1: Write the failing test**

```python
def test_normalize_evidence_bundle_keeps_visual_semantic_evidence_separate_from_hint_fields():
    bundle = normalize_evidence_bundle(
        {
            "source_name": "demo.mp4",
            "visual_semantic_evidence": {"object_categories": ["backpack"]},
            "visual_hints": {"subject_type": "EDC机能包"},
        }
    )
    assert bundle["visual_semantic_evidence"]["object_categories"] == ["backpack"]
    assert bundle["candidate_hints"]["visual_hints"]["subject_type"] == "EDC机能包"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_evidence.py::test_normalize_evidence_bundle_keeps_visual_semantic_evidence_separate_from_hint_fields -v`
Expected: FAIL because the bundle has no dedicated visual evidence layer yet.

- [ ] **Step 3: Write minimal implementation**

```python
normalized["visual_semantic_evidence"] = _as_dict(raw.get("visual_semantic_evidence"))
normalized["candidate_hints"] = candidate_hints
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_evidence.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_profile.py src/roughcut/review/content_understanding_evidence.py tests/test_content_understanding_evidence.py
git commit -m "refactor: separate visual evidence from visual hints"
```

### Task 3: Add Visual Capability Routing To Frame Understanding

**Files:**
- Create: `src/roughcut/review/content_understanding_visual.py`
- Modify: `src/roughcut/review/content_profile.py`
- Test: `tests/test_content_understanding_visual.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_infer_visual_semantic_evidence_uses_native_multimodal_provider_when_available():
    capabilities = {"visual_understanding": {"provider": "minimax", "mode": "native_multimodal"}}
    result = await infer_visual_semantic_evidence(
        frame_paths=[Path("frame_01.jpg")],
        capabilities=capabilities,
    )
    assert result["mode"] == "native_multimodal"
    assert "object_categories" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_visual.py::test_infer_visual_semantic_evidence_uses_native_multimodal_provider_when_available -v`
Expected: FAIL because the visual router module does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
async def infer_visual_semantic_evidence(frame_paths, capabilities):
    if capabilities["visual_understanding"]["mode"] == "native_multimodal":
        return await _infer_with_native_multimodal(frame_paths, capabilities)
    if capabilities["visual_understanding"]["mode"] == "mcp":
        return await _infer_with_visual_mcp(frame_paths, capabilities)
    return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_visual.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_understanding_visual.py src/roughcut/review/content_profile.py tests/test_content_understanding_visual.py
git commit -m "feat: route visual understanding by provider capability"
```

### Task 4: Expand Evidence Bundle Into Primary Evidence Graph

**Files:**
- Modify: `src/roughcut/review/content_understanding_evidence.py`
- Modify: `src/roughcut/review/content_understanding_schema.py`
- Test: `tests/test_content_understanding_evidence.py`

- [ ] **Step 1: Write the failing test**

```python
def test_normalize_evidence_bundle_builds_audio_visual_ocr_primary_evidence_sections():
    bundle = normalize_evidence_bundle(
        {
            "source_name": "demo.mp4",
            "transcript_excerpt": "这是 HSJUN 的包",
            "visual_semantic_evidence": {"object_categories": ["backpack"]},
            "ocr_profile": {"visible_text": "BOLTBOAT"},
        }
    )
    assert bundle["audio_semantic_evidence"]["transcript_text"] == "这是 HSJUN 的包"
    assert bundle["visual_semantic_evidence"]["object_categories"] == ["backpack"]
    assert bundle["ocr_semantic_evidence"]["visible_text"] == "BOLTBOAT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_evidence.py::test_normalize_evidence_bundle_builds_audio_visual_ocr_primary_evidence_sections -v`
Expected: FAIL because only a flattened evidence bundle exists.

- [ ] **Step 3: Write minimal implementation**

```python
normalized["audio_semantic_evidence"] = {"transcript_text": transcript_excerpt, "subtitle_lines": subtitle_lines}
normalized["ocr_semantic_evidence"] = {"visible_text": visible_text, "ocr_profile": ocr_profile}
normalized["visual_semantic_evidence"] = visual_semantic_evidence
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_evidence.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_understanding_evidence.py src/roughcut/review/content_understanding_schema.py tests/test_content_understanding_evidence.py
git commit -m "feat: build primary evidence graph for content understanding"
```

### Task 5: Split Fact Extraction Out Of Final Understanding

**Files:**
- Modify: `src/roughcut/review/content_understanding_infer.py`
- Create: `src/roughcut/review/content_understanding_facts.py`
- Test: `tests/test_content_understanding_infer.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_infer_content_understanding_runs_fact_extraction_before_final_understanding():
    evidence_bundle = {"source_name": "demo.mp4", "transcript_excerpt": "这是 HSJUN 的游刃"}
    result = await infer_content_understanding(evidence_bundle)
    assert result.semantic_facts.entity_candidates == ["HSJUN", "游刃"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_infer.py::test_infer_content_understanding_runs_fact_extraction_before_final_understanding -v`
Expected: FAIL because fact extraction is still embedded and not explicitly staged.

- [ ] **Step 3: Write minimal implementation**

```python
semantic_facts = await infer_content_semantic_facts(provider, evidence_bundle)
understanding = await infer_final_understanding(provider, evidence_bundle, semantic_facts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_infer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_understanding_infer.py src/roughcut/review/content_understanding_facts.py tests/test_content_understanding_infer.py
git commit -m "refactor: stage fact extraction before final understanding"
```

### Task 6: Add Conditional Entity Resolution Stage

**Files:**
- Modify: `src/roughcut/review/content_understanding_verify.py`
- Create: `src/roughcut/review/content_understanding_resolution.py`
- Test: `tests/test_content_understanding_verify.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_verify_content_understanding_only_runs_resolution_when_conflicts_exist():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="gear",
        primary_subject="船长联名包",
        observed_entities=[SubjectEntity(kind="product", name="船长联名包")],
        subject_entities=[SubjectEntity(kind="product", name="船长联名包")],
    )
    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={"transcript_excerpt": "这是船长联名的包"},
        verification_bundle=HybridVerificationBundle(
            search_queries=["船长 游刃 双肩包"],
            online_results=[{"title": "HSJUN × BOLTBOAT 游刃机能双肩包"}],
            database_results=[{"primary_subject": "HSJUN × BOLTBOAT 游刃机能双肩包"}],
        ),
    )
    assert result.entity_resolution_map
    assert result.resolved_primary_subject == "HSJUN × BOLTBOAT 游刃机能双肩包"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_verify.py::test_verify_content_understanding_only_runs_resolution_when_conflicts_exist -v`
Expected: FAIL because resolution is not conditionally orchestrated.

- [ ] **Step 3: Write minimal implementation**

```python
if should_run_entity_resolution(understanding, evidence_bundle, verification_bundle):
    candidate = await resolve_entities(
        understanding=understanding,
        evidence_bundle=evidence_bundle,
        verification_bundle=verification_bundle,
    )
else:
    candidate = understanding
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_verify.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_understanding_verify.py src/roughcut/review/content_understanding_resolution.py tests/test_content_understanding_verify.py
git commit -m "feat: add conditional entity resolution stage"
```

### Task 7: Persist Capability Matrix And Orchestration Trace

**Files:**
- Modify: `src/roughcut/review/content_understanding_schema.py`
- Modify: `src/roughcut/review/content_profile.py`
- Test: `tests/test_content_understanding_schema.py`

- [ ] **Step 1: Write the failing test**

```python
def test_map_content_understanding_to_legacy_profile_exposes_capability_matrix_and_trace():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="gear",
        primary_subject="demo subject",
        capability_matrix={"visual_understanding": {"provider": "minimax", "mode": "native_multimodal"}},
        orchestration_trace=["capability_resolution", "fact_extraction", "final_understanding"],
    )
    profile = map_content_understanding_to_legacy_profile(understanding)
    assert "capability_matrix" in profile["content_understanding"]
    assert "orchestration_trace" in profile["content_understanding"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_schema.py::test_map_content_understanding_to_legacy_profile_exposes_capability_matrix_and_trace -v`
Expected: FAIL because these fields are not persisted.

- [ ] **Step 3: Write minimal implementation**

```python
content_understanding_payload["capability_matrix"] = value.capability_matrix
content_understanding_payload["orchestration_trace"] = value.orchestration_trace
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_understanding_schema.py src/roughcut/review/content_profile.py tests/test_content_understanding_schema.py
git commit -m "feat: persist capability matrix in content understanding artifacts"
```

### Task 8: Rebuild Benchmark Around Capability Matrix Outputs

**Files:**
- Modify: `scripts/run_content_understanding_benchmark.py`
- Modify: `tests/fixtures/content_understanding_benchmark_samples.py`
- Modify: `tests/test_content_understanding_benchmark.py`

- [ ] **Step 1: Write the failing test**

```python
def test_benchmark_report_contract_includes_observed_resolved_conflicts_and_capabilities():
    report = build_console_summary(
        {
            "sample_count": 1,
            "success_count": 1,
            "failed_count": 0,
            "reports": [
                {
                    "source_name": "demo.mp4",
                    "expected_product_family": "bag",
                    "observed_entities": [],
                    "resolved_entities": [],
                    "resolved_primary_subject": "",
                    "conflicts": [],
                    "capability_matrix": {"visual_understanding": {"mode": "native_multimodal"}},
                    "status": "done",
                    "elapsed_seconds": 1.0,
                    "error": "",
                }
            ],
        }
    )
    assert "capability_matrix" in report["reports"][0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_understanding_benchmark.py::test_benchmark_report_contract_includes_observed_resolved_conflicts_and_capabilities -v`
Expected: FAIL because benchmark output is still too thin.

- [ ] **Step 3: Write minimal implementation**

```python
compact_report["capability_matrix"] = item["capability_matrix"]
compact_report["conflicts"] = item["conflicts"]
compact_report["observed_entities"] = item["observed_entities"]
compact_report["resolved_entities"] = item["resolved_entities"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_understanding_benchmark.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/run_content_understanding_benchmark.py tests/fixtures/content_understanding_benchmark_samples.py tests/test_content_understanding_benchmark.py
git commit -m "feat: extend benchmark output for capability matrix tracing"
```

### Task 9: End-To-End Regression And Live Benchmark

**Files:**
- Modify: `docs/superpowers/plans/2026-04-03-capability-matrix-content-understanding.md`
- Output: `output/test/content-understanding-benchmark/*.json`

- [ ] **Step 1: Run focused regression**

Run: `pytest tests/test_content_understanding_capabilities.py tests/test_content_understanding_evidence.py tests/test_content_understanding_visual.py tests/test_content_understanding_infer.py tests/test_content_understanding_verify.py tests/test_content_understanding_schema.py tests/test_content_profile.py tests/test_content_understanding_benchmark.py -v`
Expected: PASS

- [ ] **Step 2: Run curated four-sample benchmark**

Run: `python scripts/run_content_understanding_benchmark.py --source-dir "Y:\\EDC系列\\未剪辑视频" --samples 20260301-171443.mp4 20260211-120605.mp4 20260211-123939.mp4 20260213-133009.mp4 --limit 4`
Expected: Generate a JSON/Markdown benchmark report under `output/test/content-understanding-benchmark/`.

- [ ] **Step 3: Manually inspect benchmark deltas**

Check:
- whether `observed_entities` are populated
- whether `resolved_entities` stay empty on weak evidence
- whether `needs_review` remains true instead of misclassifying into a hard-coded type

- [ ] **Step 4: Commit benchmark evidence and doc update**

```bash
git add docs/superpowers/plans/2026-04-03-capability-matrix-content-understanding.md
git commit -m "docs: record capability matrix benchmark validation"
```

## Self-Review

- Spec coverage:
  - capability matrix: covered by Task 1
  - visual evidence promotion: covered by Tasks 2-4
  - adaptive orchestration: covered by Tasks 5-6
  - traceability and artifacts: covered by Task 7
  - benchmark-first validation: covered by Tasks 8-9
- Placeholder scan:
  - no placeholder markers or vague implementation notes remain
- Type consistency:
  - `observed_entities / resolved_entities / resolved_primary_subject / entity_resolution_map / capability_matrix / orchestration_trace` naming is consistent across tasks

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-03-capability-matrix-content-understanding.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
