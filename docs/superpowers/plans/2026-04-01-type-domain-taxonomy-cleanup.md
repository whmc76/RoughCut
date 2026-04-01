# Type/Domain Taxonomy Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate `video_type` from `content_domain` and replace the mixed `digital` domain with distinct canonical `tech` and `ai` domains while preserving legacy signal inputs.

**Architecture:** Keep raw domain keywords and legacy aliases as internal signal sources, but expose only canonical `content_domain` values outward. Update domain detection, normalization, builtin glossary packs, and memory compatibility so `workflow_template`, `video_type`, and `content_domain` no longer bleed into one another.

**Tech Stack:** Python, pytest, FastAPI API tests, glossary/memory logic in `src/roughcut/review`

---

### Task 1: Lock Canonical Domain Expectations in Tests

**Files:**
- Modify: `E:/WorkSpace/RoughCut/tests/test_subtitle_memory.py`
- Modify: `E:/WorkSpace/RoughCut/tests/test_pipeline_steps.py`
- Modify: `E:/WorkSpace/RoughCut/tests/test_api_health.py`

- [ ] **Step 1: Write the failing tests**

```python
assert detect_glossary_domains(
    workflow_template="tutorial_standard",
    subtitle_items=[{"text_final": "今天主要讲手机影像、芯片和续航。"}],
) == ["tech"]

assert detect_glossary_domains(
    workflow_template="tutorial_standard",
    subtitle_items=[{"text_final": "今天主要讲工作流、节点编排和模型推理。"}],
) == ["ai"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_subtitle_memory.py tests/test_pipeline_steps.py tests/test_api_health.py -q`
Expected: FAIL because current code still emits `digital`

- [ ] **Step 3: Write minimal implementation**

```python
_CANONICAL_DOMAIN_ALIASES.update({
    "digital": "tech",
    "software": "ai",
    "coding": "ai",
})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_subtitle_memory.py tests/test_pipeline_steps.py tests/test_api_health.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_subtitle_memory.py tests/test_pipeline_steps.py tests/test_api_health.py src/roughcut/review/domain_glossaries.py
git commit -m "refactor: split tech and ai content domains"
```

### Task 2: Update Canonicalization and Compatibility

**Files:**
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/domain_glossaries.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/subtitle_memory.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/content_profile_memory.py`

- [ ] **Step 1: Write the failing test**

```python
assert _infer_subject_domain_for_memory(
    workflow_template="unboxing_standard",
    subtitle_items=[{"text_final": "今天主要演示节点编排、工作流和模型推理。"}],
    content_profile={},
    source_name="demo.mp4",
) == "ai"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_pipeline_steps.py::test_infer_subject_domain_for_memory_uses_current_content_evidence -q`
Expected: FAIL because current code returns `digital`

- [ ] **Step 3: Write minimal implementation**

```python
compatibility = {
    "tech": set(),
    "ai": set(),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_pipeline_steps.py::test_infer_subject_domain_for_memory_uses_current_content_evidence -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/domain_glossaries.py src/roughcut/review/subtitle_memory.py src/roughcut/review/content_profile_memory.py tests/test_pipeline_steps.py
git commit -m "refactor: align memory domains with tech and ai split"
```

### Task 3: Preserve Legacy Signals Without Exposing Mixed Domains

**Files:**
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/domain_glossaries.py`
- Modify: `E:/WorkSpace/RoughCut/tests/test_subtitle_memory.py`

- [ ] **Step 1: Write the failing test**

```python
assert normalize_subject_domain("digital") == "tech"
assert normalize_subject_domain("coding") == "ai"
assert normalize_subject_domain("software") == "ai"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_subtitle_memory.py -q`
Expected: FAIL because current aliases collapse everything into `digital`

- [ ] **Step 3: Write minimal implementation**

```python
_CANONICAL_DOMAIN_SOURCES = {
    "tech": ("tech", "digital"),
    "ai": ("ai", "coding", "software"),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_subtitle_memory.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/domain_glossaries.py tests/test_subtitle_memory.py
git commit -m "refactor: preserve legacy ai and tech signal aliases"
```
