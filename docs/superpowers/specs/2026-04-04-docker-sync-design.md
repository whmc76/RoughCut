# Docker Sync Design

**Date:** 2026-04-04

**Goal**

Make RoughCut's Docker code-sync behavior reliable by removing ambiguity between the existing host-side refresh watcher and the newer live source sync overlay.

**Problem**

The repository currently contains two competing approaches:

- A host-side watcher that rebuilds `runtime/full` containers after workspace changes.
- A `docker-compose.dev.yml` overlay that bind-mounts source code and uses in-container watchers.

The implementation, tests, and docs have drifted apart. As a result, operators can believe automatic sync is active while running a runtime stack that is actually pinned to an old image.

**Decision**

Keep both mechanisms, but give them distinct roles:

- `runtime` and `full` become the default development-oriented auto-sync modes.
  These modes always include `docker-compose.dev.yml`, so source changes are reflected through bind mounts and in-container watchers.
- `runtime-watch` and `full-watch` remain explicit rebuild-based modes.
  These modes continue to use `scripts/watch-roughcut-docker-runtime.ps1` and `scripts/run-roughcut-docker-refresh-session.ps1`.

**Behavioral Contract**

- Starting `start_roughcut.ps1 -Mode runtime` or `-Mode full` must use the dev overlay and must not rely on a hidden host watch process for code sync.
- Starting `start_roughcut.ps1 -Mode runtime-watch` or `-Mode full-watch` must continue to launch the host-side rebuild watcher.
- User-facing help and README text must describe the split clearly.
- Tests must lock the default mode onto live sync and preserve the explicit rebuild-watch entry points.

**Files In Scope**

- `start_roughcut.ps1`
- `start_roughcut.bat`
- `README.md`
- `tests/test_docker_dev_runtime.py`
- `tests/test_docker_runtime_refresh_safety.py`

**Non-Goals**

- Removing the legacy host-side watch scripts
- Changing production/stable deployment architecture beyond clarifying mode semantics
- Refactoring unrelated Docker services
