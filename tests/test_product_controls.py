import asyncio

from roughcut.api.schemas import JobInitializeIn
from roughcut.api.schemas import WatchRootCreate
from roughcut.edit.product_controls import (
    build_product_controls_payload,
    extract_product_controls_from_profile,
    normalize_automation_level,
    normalize_edit_mode,
    normalize_material_usage,
    normalize_requested_product_controls,
    strategy_type_for_edit_mode,
    workflow_template_for_edit_mode,
)
from roughcut.edit.strategy_profile import infer_strategy_type
from roughcut.watcher import folder_watcher


def test_product_control_normalizers_accept_common_aliases() -> None:
    assert normalize_edit_mode("commentary") == "talking_head"
    assert normalize_automation_level("balanced") == "standard"
    assert normalize_material_usage("selected") == "selected_uploaded"


def test_workflow_template_for_edit_mode_maps_known_modes() -> None:
    assert workflow_template_for_edit_mode("tutorial") == "tutorial_standard"
    assert workflow_template_for_edit_mode("highlight") == "gameplay_highlight"
    assert workflow_template_for_edit_mode("multi_material") is None


def test_strategy_type_for_edit_mode_maps_runtime_strategy_overrides() -> None:
    assert strategy_type_for_edit_mode("tutorial") == "step_demonstration"
    assert strategy_type_for_edit_mode("highlight") == "event_highlight"
    assert strategy_type_for_edit_mode("auto") is None


def test_build_product_controls_payload_recommends_from_strategy_type() -> None:
    payload = build_product_controls_payload(
        {},
        strategy_type="narrative_assembly",
        content_kind="commentary",
        local_asset_inventory={"multi_material_ready": True, "has_visual_inserts": True, "has_audio_support": True},
        job_flow_mode="auto",
    )

    assert payload["requested"]["edit_mode"] == "auto"
    assert payload["recommended"]["edit_mode"] == "multi_material"
    assert payload["effective"]["edit_mode"] == "multi_material"


def test_extract_product_controls_from_profile_reads_source_context_fallback() -> None:
    controls = extract_product_controls_from_profile(
        {
            "source_context": {
                "product_controls": {
                    "edit_mode": "highlight",
                    "automation_level": "conservative",
                    "material_usage": "selected_uploaded",
                }
            }
        }
    )

    assert controls["edit_mode"] == "highlight"
    assert controls["automation_level"] == "conservative"
    assert controls["material_usage"] == "selected_uploaded"


def test_normalize_requested_product_controls_accepts_effective_only_payload() -> None:
    controls = normalize_requested_product_controls(
        {
            "effective": {
                "edit_mode": "highlight",
                "automation_level": "standard",
                "material_usage": "all_uploaded",
            }
        }
    )

    assert controls == {
        "edit_mode": "highlight",
        "automation_level": "standard",
        "material_usage": "all_uploaded",
    }


def test_infer_strategy_type_honors_explicit_product_control_edit_mode() -> None:
    strategy_type = infer_strategy_type(
        workflow_template="commentary_focus",
        content_profile={
            "content_kind": "commentary",
            "source_context": {
                "product_controls": {
                    "edit_mode": "highlight",
                    "automation_level": "standard",
                    "material_usage": "all_uploaded",
                }
            },
        },
    )

    assert strategy_type == "event_highlight"


def test_job_initialize_in_validates_phase7_product_controls() -> None:
    body = JobInitializeIn(
        language="zh-CN",
        workflow_template=None,
        job_flow_mode="auto",
        workflow_mode="standard_edit",
        enhancement_modes=[],
        edit_mode="commentary",
        automation_level="balanced",
        material_usage="selected",
        video_description="demo",
    )

    assert body.edit_mode == "talking_head"
    assert body.automation_level == "standard"
    assert body.material_usage == "selected_uploaded"


def test_watch_root_create_validates_product_controls() -> None:
    body = WatchRootCreate(
        path="Y:/EDC",
        edit_mode="gameplay",
        automation_level="safe",
        material_usage="primary_only",
    )

    assert body.edit_mode == "highlight"
    assert body.automation_level == "conservative"
    assert body.material_usage == "main_only"


def test_inventory_job_factory_receives_watch_root_product_controls(monkeypatch) -> None:
    calls = []

    async def fake_create_job_for_file(file_path, workflow_template=None, language="zh-CN", **kwargs):
        calls.append({
            "file_path": str(file_path),
            "workflow_template": workflow_template,
            "language": language,
            "product_controls": kwargs.get("product_controls"),
        })
        return "job-1"

    monkeypatch.setattr(folder_watcher, "_create_job_for_file", fake_create_job_for_file)

    results = asyncio.run(
        folder_watcher.create_jobs_for_inventory_paths(
            ["Y:/EDC/demo.mp4"],
            workflow_template="unboxing_standard",
            product_controls={
                "edit_mode": "tutorial",
                "automation_level": "richer",
                "material_usage": "main_only",
            },
        )
    )

    assert results == [{"path": "Y:/EDC/demo.mp4", "job_id": "job-1"}]
    assert calls[0]["product_controls"] == {
        "edit_mode": "tutorial",
        "automation_level": "richer",
        "material_usage": "main_only",
    }
