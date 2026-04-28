from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = REPO_ROOT / "start_roughcut.ps1"


def _function_body(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.index(marker)
    next_function = source.find("\nfunction ", start + len(marker))
    if next_function == -1:
        return source[start:]
    return source[start:next_function]


def test_stop_roughcut_process_uses_process_name_guard() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Stop-RoughCutProcess")

    assert "Get-ProcessMatches -Pattern $Pattern" in body
    assert "Get-CimInstance Win32_Process" not in body


def test_process_match_guard_only_targets_roughcut_runtime_processes() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Get-ProcessMatches")

    assert "IsNullOrWhiteSpace($Pattern)" in body
    assert '".*"' in body
    assert '"^.*$"' in body
    assert "Refusing to match RoughCut processes with unsafe pattern" in body
    assert "$_.Name -in" in body
    for process_name in ("python.exe", "pythonw.exe", "roughcut.exe", "celery.exe"):
        assert f'"{process_name}"' in body


def test_worker_celery_fallback_pattern_is_not_split_into_wildcard_entry() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Start-RoughCutWorkerProcess")

    assert '("{0}.*{1}" -f' in body
    assert '[regex]::Escape("celery -A roughcut.pipeline.celery_app:celery_app worker --queues=$Queue") + ".*" + [regex]::Escape($workerNode)' not in body
