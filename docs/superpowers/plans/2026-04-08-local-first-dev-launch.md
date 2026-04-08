# RoughCut Local-First Dev Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RoughCut's launcher and docs consistently present local mode as the default development workflow, while keeping Docker for infra and explicit containerized runs.

**Architecture:** Keep the existing launcher structure, but change the contract around it: local mode becomes the clearly recommended path, Docker runtime/full become explicit secondary modes, and tests enforce that wording. Preserve runtime/full implementations to avoid unnecessary deployment churn.

**Tech Stack:** PowerShell, Windows batch, Markdown docs, pytest

---

## File Structure Map

**Primary files to modify**

- `start_roughcut.bat`
- `start_roughcut.ps1`
- `README.md`
- `tests/test_docker_dev_runtime.py`

## Task 1: Lock the local-first contract in tests

**Files:**

- Modify: `tests/test_docker_dev_runtime.py`

- [ ] **Step 1: Write assertions for local-first help and README wording**

```python
def test_batch_help_describes_local_mode_as_primary_entrypoint():
    script_text = Path("start_roughcut.bat").read_text(encoding="utf-8")

    assert "One-click local development launcher" in script_text
    assert "Start local API / orchestrator / workers against local code" in script_text
```

```python
def test_readme_describes_local_first_development_flow():
    readme_text = Path("README.md").read_text(encoding="utf-8")

    assert "现在推荐的日常开发路径是：本地 Python + 本地前端 + 必要时只起 infra" in readme_text
    assert "`start_roughcut.bat` 作为默认开发入口" in readme_text
```

- [ ] **Step 2: Run the focused test file to verify the new expectations fail**

Run: `uv run pytest tests/test_docker_dev_runtime.py -q`

Expected: FAIL because current docs/help still describe Docker runtime/full as the recommended path.

- [ ] **Step 3: Update the tests so they enforce the final wording**

```python
assert "Docker runtime with live source sync" not in script_text
assert "`runtime/full` 仍保留，但属于显式容器模式" in readme_text
```

- [ ] **Step 4: Re-run the focused test file**

Run: `uv run pytest tests/test_docker_dev_runtime.py -q`

Expected: FAIL until launcher/docs are updated.

## Task 2: Reword the launcher around local-first development

**Files:**

- Modify: `start_roughcut.bat`
- Modify: `start_roughcut.ps1`

- [ ] **Step 1: Update batch help text to make local mode primary**

```bat
echo   start_roughcut.bat             One-click local development launcher
echo   start_roughcut.bat infra       Start only PostgreSQL / Redis / MinIO containers
echo   start_roughcut.bat runtime     Start explicit containerized runtime mode
```

- [ ] **Step 2: Tighten local-mode messaging in PowerShell**

```powershell
Write-Host "Starting local RoughCut development stack..." -ForegroundColor Cyan
Write-Host "Docker runtime/full remain available, but local mode is the default development path." -ForegroundColor DarkGray
```

- [ ] **Step 3: Keep the runtime-port guard so stale Docker runtime cannot hijack local startup**

```powershell
$runtimeApiPort = Resolve-ContainerMappedPort -ContainerName "roughcut-api-1" -ContainerPort 8000
if ($null -ne $runtimeApiPort) {
    $usedPorts[$runtimeApiPort] = $true
}
```

- [ ] **Step 4: Run the focused launcher/doc tests**

Run: `uv run pytest tests/test_docker_dev_runtime.py -q`

Expected: PASS

## Task 3: Rewrite README to match the local-first workflow

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Update quickstart to recommend local development with infra-only Docker**

```md
现在推荐的日常开发路径是：本地 Python + 本地前端 + 必要时只起 `postgres` / `redis` / `minio`。
```

- [ ] **Step 2: Rewrite Windows launcher guidance**

```md
- `start_roughcut.bat`
  默认开发入口。启动本地 API / orchestrator / workers，并服务本地构建的 `frontend/dist`。
- `start_roughcut.bat infra`
  只起基础依赖容器。
- `start_roughcut.bat runtime`
  显式容器模式，仅在你明确要跑容器化 runtime 时使用。
```

- [ ] **Step 3: Demote Docker runtime/full wording in Docker sections**

```md
Docker 更适合基础依赖、部署验证和显式容器化运行，而不是默认日常前端/后端开发入口。
```

- [ ] **Step 4: Run the focused doc/launcher tests again**

Run: `uv run pytest tests/test_docker_dev_runtime.py -q`

Expected: PASS

## Task 4: Verify the local-first contract end-to-end

**Files:**

- Modify: `start_roughcut.bat`
- Modify: `start_roughcut.ps1`
- Modify: `README.md`
- Modify: `tests/test_docker_dev_runtime.py`

- [ ] **Step 1: Run the focused regression suite**

Run: `uv run pytest tests/test_docker_dev_runtime.py -q`

Expected: PASS

- [ ] **Step 2: Run one additional launcher-related backend test file**

Run: `uv run pytest tests/test_docker_runtime_refresh_safety.py -q`

Expected: PASS

- [ ] **Step 3: Inspect the final diff for wording consistency**

Run: `git diff -- start_roughcut.bat start_roughcut.ps1 README.md tests/test_docker_dev_runtime.py`

Expected: only local-first wording, safeguards, and aligned tests/docs.

## Self-Review

- Spec coverage: startup contract, docs, launcher wording, and tests each have a dedicated task.
- Placeholder scan: commands, file paths, and wording targets are explicit.
- Type consistency: `local-first`, `infra`, and `explicit containerized runtime` terms are used consistently across tasks.
