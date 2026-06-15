from roughcut.api.schemas import resolve_job_flow_mode_from_execution_mode


def test_explicit_auto_execution_mode_forces_auto_job_flow_mode() -> None:
    assert (
        resolve_job_flow_mode_from_execution_mode(
            "smart_assist",
            "auto",
            execution_mode_explicit=True,
        )
        == "auto"
    )


def test_explicit_plan_first_execution_mode_forces_auto_job_flow_mode() -> None:
    assert (
        resolve_job_flow_mode_from_execution_mode(
            "smart_assist",
            "plan_first",
            execution_mode_explicit=True,
        )
        == "auto"
    )


def test_explicit_smart_assist_execution_mode_forces_smart_assist_job_flow_mode() -> None:
    assert (
        resolve_job_flow_mode_from_execution_mode(
            "auto",
            "smart_assist",
            execution_mode_explicit=True,
        )
        == "smart_assist"
    )


def test_legacy_request_without_execution_mode_keeps_explicit_job_flow_mode() -> None:
    assert (
        resolve_job_flow_mode_from_execution_mode(
            "smart_assist",
            None,
            execution_mode_explicit=False,
        )
        == "smart_assist"
    )
