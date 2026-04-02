# Readable Number Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify readable Chinese subtitle number normalization across ASR postprocess and subtitle polish without adding new text tracks.

**Architecture:** Keep `text_raw` unchanged and route `text_norm` / `text_final` through one shared number-normalization strategy in `speech.postprocess`. `content_profile` only reuses that strategy and tightens prompt guidance so the model and fallback path converge on the same output style.

**Tech Stack:** Python, pytest, existing subtitle postprocess and review pipeline

---

### Task 1: Lock readable-number expectations with tests

**Files:**
- Modify: `E:\WorkSpace\RoughCut\tests\test_postprocess.py`
- Modify: `E:\WorkSpace\RoughCut\tests\test_content_profile.py`

- [x] **Step 1: Write the failing tests**

Add regression coverage for:

- natural phrase preservation: `一个`
- vague phrase preservation: `两三个`
- info-style formatting: `2个档位 / 3月5号 / 8点20 / A4`
- subtitle polish prompt guidance and fallback behavior

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_postprocess.py -k "natural_single_count_phrase or vague_quantity_phrase or info_numbers_dates_and_alpha_numeric_tokens" -q
uv run pytest tests/test_content_profile.py -k "display_number_guidance or readable_number_strategy" -q
```

Expected: failures showing current behavior still outputs `1个`, `23个`, and misses date/time / alpha-numeric normalization.

- [x] **Step 3: Write minimal implementation**

Implement shared readable-number helpers in `src/roughcut/speech/postprocess.py`:

- normalize alphanumeric tokens like `a四 -> A4`
- normalize times like `八点二十 -> 8点20`
- preserve natural single-count phrases like `一个`
- preserve vague phrases like `两三个`
- keep numeric conversion for info-style counts like `2个档位`

Update `src/roughcut/review/content_profile.py`:

- reuse shared number normalization in polish cleanup
- expand prompt guidance to mention `字母+数字` and `日期时间`

- [x] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_postprocess.py -k "natural_single_count_phrase or vague_quantity_phrase or info_numbers_dates_and_alpha_numeric_tokens" -q
uv run pytest tests/test_content_profile.py -k "display_number_guidance or readable_number_strategy" -q
```

Expected: all selected tests pass.

### Task 2: Verify nearby regressions

**Files:**
- Modify: `E:\WorkSpace\RoughCut\src\roughcut\speech\postprocess.py`
- Modify: `E:\WorkSpace\RoughCut\src\roughcut\review\content_profile.py`
- Test: `E:\WorkSpace\RoughCut\tests\test_postprocess.py`
- Test: `E:\WorkSpace\RoughCut\tests\test_content_profile.py`

- [ ] **Step 1: Run broader verification**

Run:

```bash
uv run pytest tests/test_postprocess.py -q
uv run pytest tests/test_content_profile.py -k "polish_subtitle_items" -q
```

Expected: existing subtitle postprocess and polish behaviors remain green.
