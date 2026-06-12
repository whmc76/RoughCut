from __future__ import annotations

from scripts import run_two_full_tasks_direct as two


def test_configure_local_event_loop_policy_does_not_force_selector_by_default(monkeypatch) -> None:
    calls: list[object] = []

    class DummyPolicy:
        pass

    def fake_set_event_loop_policy(policy: object) -> None:
        calls.append(policy)

    monkeypatch.delenv("ROUGHCUT_FORCE_SELECTOR_EVENT_LOOP", raising=False)
    monkeypatch.setattr(two.sys, "platform", "win32")
    monkeypatch.setattr(two.asyncio, "WindowsSelectorEventLoopPolicy", DummyPolicy)
    monkeypatch.setattr(two.asyncio, "set_event_loop_policy", fake_set_event_loop_policy)
    two._configure_local_event_loop_policy()
    assert calls == []


def test_configure_local_event_loop_policy_forces_selector_when_enabled(monkeypatch) -> None:
    calls: list[object] = []

    class DummyPolicy:
        pass

    def fake_set_event_loop_policy(policy: object) -> None:
        calls.append(policy)

    monkeypatch.setenv("ROUGHCUT_FORCE_SELECTOR_EVENT_LOOP", "1")
    monkeypatch.setattr(two.sys, "platform", "win32")
    monkeypatch.setattr(two.asyncio, "WindowsSelectorEventLoopPolicy", DummyPolicy)
    monkeypatch.setattr(two.asyncio, "set_event_loop_policy", fake_set_event_loop_policy)
    two._configure_local_event_loop_policy()
    assert len(calls) == 1
    assert isinstance(calls[0], DummyPolicy)


def test_run_full_chain_marks_step_timeout_as_failed(monkeypatch) -> None:
    calls: list[tuple[str, str, str | None, bool]] = []

    def fake_mark_step(job_id: str, step_name: str, status: str, error: str | None = None, terminal_failure: bool = False) -> None:
        calls.append((step_name, status, error, terminal_failure))

    monkeypatch.setattr(two, "PIPELINE_STEPS", ["render"])
    monkeypatch.setattr(two, "mark_step", fake_mark_step)
    monkeypatch.setattr(
        two,
        "_run_step_sync_with_timeout",
        lambda step_name, job_id, timeout_seconds: (_ for _ in ()).throw(TimeoutError("阶段超时")),
    )
    monkeypatch.setattr(two, "read_step_detail", lambda job_id, step_name: "")

    step_runs, status = two.run_full_chain("job-timeout")

    assert status == "failed"
    assert len(step_runs) == 1
    assert step_runs[0].status == "failed"
    assert step_runs[0].error == "TimeoutError: 阶段超时"
    assert ("render", "failed", "TimeoutError: 阶段超时", True) in calls
