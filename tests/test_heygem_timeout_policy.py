from types import SimpleNamespace

from roughcut.providers.avatar import heygem


def test_heygem_no_progress_timeout_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        heygem,
        "get_settings",
        lambda: SimpleNamespace(avatar_render_no_progress_timeout_sec=0),
    )

    assert heygem._resolve_task_no_progress_timeout_seconds() is None


def test_heygem_no_progress_timeout_has_minimum(monkeypatch) -> None:
    monkeypatch.setattr(
        heygem,
        "get_settings",
        lambda: SimpleNamespace(avatar_render_no_progress_timeout_sec=30),
    )

    assert heygem._resolve_task_no_progress_timeout_seconds() == 60.0
