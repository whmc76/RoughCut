# Docker Sync Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RoughCut's default Docker runtime/full modes use reliable live source sync while preserving explicit watch-and-rebuild entry points.

**Architecture:** `runtime/full` will always include the dev compose overlay so code changes flow through bind mounts and in-container watchers. The legacy host watcher remains available only through `runtime-watch/full-watch`, with docs and tests updated so the two mechanisms no longer overlap ambiguously.

**Tech Stack:** PowerShell launch scripts, Docker Compose overlays, pytest

---

### Task 1: Lock Default Runtime Modes To Live Sync

**Files:**
- Modify: `start_roughcut.ps1`
- Test: `tests/test_docker_dev_runtime.py`

- [ ] **Step 1: Write the failing test**

Add assertions in `tests/test_docker_dev_runtime.py` that `start_roughcut.ps1`:

```python
assert 'Join-Path $RepoRoot "docker-compose.dev.yml"' in script_text
assert '$files += $DevComposeFile' in script_text
assert 'Write-Host "Docker live source sync is active for this runtime."' in script_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest -q tests/test_docker_dev_runtime.py`
Expected: FAIL because the launcher does not yet add `docker-compose.dev.yml` or print live-sync status.

- [ ] **Step 3: Write minimal implementation**

Update `start_roughcut.ps1` so the compose-file resolver includes `docker-compose.dev.yml` for `runtime/full`, and print an explicit live-sync status line after startup.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest -q tests/test_docker_dev_runtime.py`
Expected: PASS

### Task 2: Preserve Explicit Watch-And-Rebuild Modes

**Files:**
- Modify: `tests/test_docker_runtime_refresh_safety.py`
- Modify: `start_roughcut.ps1`

- [ ] **Step 1: Write the failing test**

Add a script-text test proving explicit watch entry points still exist:

```python
assert 'if ($Mode -in @("runtime-watch", "full-watch"))' in script_text
assert 'Start-RoughCutDockerWatchMode -WatchMode $Mode' in script_text
assert 'Start-RoughCutDockerWatch -ComposeMode $Mode' not in script_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest -q tests/test_docker_runtime_refresh_safety.py`
Expected: FAIL because the launcher still auto-starts the host watch for `runtime/full`.

- [ ] **Step 3: Write minimal implementation**

Remove automatic `Start-RoughCutDockerWatch -ComposeMode $Mode` from the default `runtime/full` startup path while leaving explicit watch modes intact.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest -q tests/test_docker_runtime_refresh_safety.py`
Expected: PASS

### Task 3: Align Help Text And README

**Files:**
- Modify: `start_roughcut.bat`
- Modify: `README.md`
- Test: `tests/test_docker_dev_runtime.py`

- [ ] **Step 1: Write the failing test**

Extend `tests/test_docker_dev_runtime.py` so help/docs expectations become:

```python
assert "live source sync" in script_text
assert "auto-refresh Docker runtime" not in script_text
```

and add README assertions that `runtime/full` are described with live source sync while `runtime-watch/full-watch` are described as explicit rebuild-watch modes.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest -q tests/test_docker_dev_runtime.py`
Expected: FAIL because help and README still describe `runtime/full` as automatic refresh/watch modes.

- [ ] **Step 3: Write minimal implementation**

Update launcher help text and README sections so:

- `runtime/full` mean live source sync
- `runtime-watch/full-watch` mean host-side rebuild watch
- warnings make it obvious which mode is suitable for development versus long-running queues

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest -q tests/test_docker_dev_runtime.py`
Expected: PASS

### Task 4: Final Verification

**Files:**
- No code changes

- [ ] **Step 1: Run focused verification**

Run: `uv run python -m pytest -q tests/test_docker_dev_runtime.py tests/test_docker_runtime_refresh_safety.py`
Expected: PASS

- [ ] **Step 2: Run launcher-level inspection**

Run:

```powershell
pwsh -NoProfile -Command "& { . .\start_roughcut.ps1; Get-RoughCutComposeFiles -ComposeMode 'runtime' }"
```

Expected output includes:

```text
docker-compose.infra.yml
docker-compose.runtime.yml
docker-compose.dev.yml
```

- [ ] **Step 3: Commit**

```bash
git add start_roughcut.ps1 start_roughcut.bat README.md tests/test_docker_dev_runtime.py tests/test_docker_runtime_refresh_safety.py docs/superpowers/specs/2026-04-04-docker-sync-design.md docs/superpowers/plans/2026-04-04-docker-sync-reliability.md
git commit -m "fix: stabilize docker sync modes"
```
