from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from roughcut.review import intelligent_copy_cover_quality as quality


def _request(output_path: Path, *, status: str = "completed") -> dict[str, object]:
    return {
        "status": status,
        "backend": "codex_builtin",
        "created_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        "output_path": str(output_path),
        "target_size": {"width": 1080, "height": 1920},
    }


def _metadata(output_path: Path, *, status: str = "completed") -> dict[str, object]:
    return {
        "image_generation": {
            "status": status,
            "backend": "codex_builtin",
            "output_path": str(output_path),
        }
    }


def test_pending_codex_cover_is_not_publish_ready(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(
        _metadata(output, status="pending_codex_imagegen"),
        _request(output, status="pending_codex_imagegen"),
        output,
    )

    assert result["publish_ready"] is False
    assert "封面等待 Codex 内置 imagegen 执行完成" in result["blocking_reasons"]
    assert f"封面输出文件不存在：{output}" in result["blocking_reasons"]


def test_completed_codex_cover_with_existing_matching_file_is_publish_ready(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(
        _metadata(output),
        _request(output),
        output,
    )

    assert result["publish_ready"] is True
    assert result["blocking_reasons"] == []
    assert result["image_dimensions"] == {"width": 1080, "height": 1920}


def test_cover_quality_accepts_stale_metadata_pending_when_request_completed(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(
        _metadata(output, status="pending_codex_imagegen"),
        _request(output, status="completed"),
        output,
    )

    assert result["publish_ready"] is True
    assert result["blocking_reasons"] == []


def test_reference_cover_fallback_is_never_publish_ready_even_if_file_and_verification_exist(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"fallback")
    request = _request(output, status="pending_codex_imagegen")
    request["bitmap_title_contract_verified_at"] = datetime.now(UTC).isoformat()
    request["bitmap_title_contract_check_unavailable"] = True

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(
        {
            "source": "reference_cover_fallback",
            "image_generation": {
                "status": "pending_codex_imagegen",
                "backend": "codex_builtin",
                "output_path": str(output),
            },
        },
        request,
        output,
    )

    assert result["publish_ready"] is False
    assert "封面当前仅为参考帧占位图，正式生图尚未完成" in result["blocking_reasons"]


def test_cover_group_reuse_inherits_reference_cover_fallback_blocker(tmp_path, monkeypatch) -> None:
    output = tmp_path / "bilibili-cover.jpg"
    output.write_bytes(b"fallback")
    request = _request(output, status="pending_codex_imagegen")
    request["bitmap_title_contract_verified_at"] = datetime.now(UTC).isoformat()

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1600, 900, None))

    result = quality.assess_cover_publish_readiness(
        {
            "source": "cover_group_reuse",
            "group_generation": {
                "source": "reference_cover_fallback",
                "image_generation": {
                    "status": "pending_codex_imagegen",
                    "backend": "codex_builtin",
                    "output_path": str(output),
                },
            },
            "image_generation": {
                "status": "pending_codex_imagegen",
                "backend": "codex_builtin",
                "output_path": str(output),
            },
        },
        request,
        output,
    )

    assert result["publish_ready"] is False
    assert "封面当前仅为参考帧占位图，正式生图尚未完成" in result["blocking_reasons"]


def test_completed_codex_cover_missing_file_is_not_publish_ready(tmp_path, monkeypatch) -> None:
    output = tmp_path / "missing-cover.jpg"

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(
        _metadata(output),
        _request(output),
        output,
    )

    assert result["publish_ready"] is False
    assert result["blocking_reasons"] == [f"封面输出文件不存在：{output}"]


def test_completed_codex_cover_with_bad_aspect_ratio_is_not_publish_ready(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1920, 1080, None))

    result = quality.assess_cover_publish_readiness(
        _metadata(output),
        _request(output),
        output,
    )

    assert result["publish_ready"] is False
    assert result["blocking_reasons"] == [
        "封面尺寸比例与平台目标严重不符：output=1920x1080, target=1080x1920"
    ]


def test_completed_codex_cover_with_stale_output_is_not_publish_ready(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"old-generated")
    old_time = datetime.now(UTC) - timedelta(hours=2)
    output.touch()
    output_stat_time = old_time.timestamp()
    import os

    os.utime(output, (output_stat_time, output_stat_time))

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    request = _request(output)
    request["created_at"] = datetime.now(UTC).isoformat()
    result = quality.assess_cover_publish_readiness(_metadata(output), request, output)

    assert result["publish_ready"] is False
    assert result["blocking_reasons"] == ["封面输出文件早于本次 Codex imagegen 请求，可能是旧 stale output"]


def test_cover_hard_contract_blocks_missing_post_overlay_and_signature_drift(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")
    request = _request(output)
    request["cover_hard_contract"] = {
        "preserve_subject_geometry": True,
        "post_title_overlay_required": True,
        "brand_model_title_required": True,
        "config_subtitle_required": True,
        "signature_stability_required": True,
        "required_title_lines": {
            "top": "MAXACE",
            "main": "美杜莎4",
            "bottom": "双版对比",
        },
    }
    metadata = {
        "image_generation": {
            "status": "completed",
            "backend": "codex_builtin",
            "output_path": str(output),
            "deformation_risk": 0.41,
        }
    }

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(metadata, request, output)

    assert result["publish_ready"] is False
    assert "封面标题后叠字未完成，不满足品牌/型号主标题与配置副标题硬合同" in result["blocking_reasons"]
    assert "封面主体几何稳定性不满足硬合同：deformation_risk=0.41" in result["blocking_reasons"]


def test_cover_hard_contract_accepts_matching_overlay_lines(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")
    request = _request(output)
    request["cover_hard_contract"] = {
        "post_title_overlay_required": True,
        "brand_model_title_required": True,
        "config_subtitle_required": True,
        "required_title_lines": {
            "top": "MAXACE",
            "main": "美杜莎4",
            "bottom": "双版对比",
        },
    }
    request["post_title_overlay_applied"] = True
    request["post_title_overlay_lines"] = {
        "top": "MAXACE",
        "main": "美杜莎4",
        "bottom": "双版对比",
    }
    request["post_title_overlay_title_style"] = "edc_cover_battle"

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(_metadata(output), request, output)

    assert result["publish_ready"] is True


def test_cover_hard_contract_blocks_when_local_overlay_bitmap_text_check_is_missing(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")
    request = _request(output)
    request["cover_hard_contract"] = {
        "post_title_overlay_required": True,
        "brand_model_title_required": True,
        "config_subtitle_required": True,
        "required_title_lines": {
            "top": "MAXACE",
            "main": "美杜莎4",
            "bottom": "双版对比",
        },
    }
    request["cover_director_policy"] = {"typography_owner": "local_post_overlay"}
    request["post_title_overlay_applied"] = True
    request["post_title_overlay_lines"] = {
        "top": "MAXACE",
        "main": "美杜莎4",
        "bottom": "双版对比",
    }
    request["post_title_overlay_title_style"] = "edc_cover_battle"

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(_metadata(output), request, output)

    assert result["publish_ready"] is False
    assert any("封面位图额外文字校验未完成" in reason for reason in result["blocking_reasons"])


def test_cover_hard_contract_blocks_oversized_landscape_overlay(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")
    request = _request(output)
    request["target_size"] = {"width": 1280, "height": 720}
    request["cover_hard_contract"] = {
        "post_title_overlay_required": True,
        "brand_model_title_required": True,
        "config_subtitle_required": True,
        "required_title_lines": {
            "top": "MAXACE",
            "main": "美杜莎4",
            "bottom": "顶配vs次顶配",
        },
    }
    request["post_title_overlay_applied"] = True
    request["post_title_overlay_lines"] = {
        "top": "MAXACE",
        "main": "美杜莎4",
        "bottom": "顶配vs次顶配",
    }
    request["post_title_overlay_group_style"] = "edc_cinematic_hero"
    request["post_title_overlay_title_style"] = "edc_cover_battle"

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1280, 720, None))

    result = quality.assess_cover_publish_readiness(_metadata(output), request, output)

    assert result["publish_ready"] is False
    assert any("标题层已压缩主体展示" in reason for reason in result["blocking_reasons"])


def test_cover_hard_contract_blocks_brand_line_drift(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")
    request = _request(output)
    request["cover_hard_contract"] = {
        "post_title_overlay_required": True,
        "brand_model_title_required": True,
        "config_subtitle_required": True,
        "signature_stability_required": True,
        "required_title_lines": {
            "top": "MAXACE",
            "main": "美杜莎4",
            "bottom": "双版对比",
        },
    }
    request["post_title_overlay_applied"] = True
    request["post_title_overlay_lines"] = {
        "top": "FAS",
        "main": "美杜莎4",
        "bottom": "双版对比",
    }
    request["post_title_overlay_title_style"] = "edc_cover_battle"

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(_metadata(output), request, output)

    assert result["publish_ready"] is False
    assert "封面品牌行未稳定锁定" in result["blocking_reasons"][0]


def test_cover_hard_contract_accepts_matching_bitmap_title_contract(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")
    request = _request(output)
    request["cover_hard_contract"] = {
        "full_bitmap_cover_required": True,
        "brand_model_title_required": True,
        "config_subtitle_required": True,
        "required_title_lines": {
            "top": "MAXACE",
            "main": "美杜莎4",
            "bottom": "双版对比",
        },
    }
    request["cover_director_policy"] = {"typography_owner": "codex_full_cover"}
    request["bitmap_title_contract_passed"] = True
    request["bitmap_title_contract_verified_at"] = datetime.now(UTC).isoformat()
    request["bitmap_title_lines"] = {
        "top": "MAXACE",
        "main": "美杜莎4",
        "bottom": "双版对比",
    }
    request["bitmap_title_style_verified"] = True

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(_metadata(output), request, output)

    assert result["publish_ready"] is True


def test_cover_hard_contract_blocks_full_bitmap_cover_when_title_verification_is_missing(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")
    request = _request(output)
    request["cover_hard_contract"] = {
        "full_bitmap_cover_required": True,
        "brand_model_title_required": True,
        "config_subtitle_required": True,
        "required_title_lines": {
            "top": "MAXACE",
            "main": "美杜莎4",
            "bottom": "双版对比",
        },
    }
    request["cover_director_policy"] = {"typography_owner": "codex_full_cover"}
    request["bitmap_title_contract_passed"] = True
    request["bitmap_title_lines"] = {
        "top": "MAXACE",
        "main": "美杜莎4",
        "bottom": "双版对比",
    }
    request["bitmap_title_style_verified"] = True

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(_metadata(output), request, output)

    assert result["publish_ready"] is False
    assert any("完整封面位图标题校验未完成" in reason for reason in result["blocking_reasons"])


def test_cover_hard_contract_does_not_treat_verification_unavailable_as_title_drift(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")
    request = _request(output)
    request["cover_hard_contract"] = {
        "full_bitmap_cover_required": True,
        "brand_model_title_required": True,
        "config_subtitle_required": True,
        "signature_stability_required": True,
        "required_title_lines": {
            "top": "MAXACE",
            "main": "美杜莎4",
            "bottom": "顶配vs次顶配",
        },
    }
    request["cover_director_policy"] = {"typography_owner": "codex_full_cover"}
    request["bitmap_title_contract_passed"] = None
    request["bitmap_title_contract_verified_at"] = datetime.now(UTC).isoformat()
    request["bitmap_title_contract_check_unavailable"] = True

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(_metadata(output), request, output)

    assert result["publish_ready"] is False
    assert not any("未稳定锁定" in reason for reason in result["blocking_reasons"])
    assert any("完整封面位图标题校验未产出有效结论" in reason for reason in result["blocking_reasons"])


def test_cover_hard_contract_blocks_bitmap_title_drift_for_codex_full_cover(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")
    request = _request(output)
    request["cover_hard_contract"] = {
        "full_bitmap_cover_required": True,
        "brand_model_title_required": True,
        "config_subtitle_required": True,
        "required_title_lines": {
            "top": "MAXACE",
            "main": "美杜莎4",
            "bottom": "顶配vs次顶配",
        },
    }
    request["cover_director_policy"] = {"typography_owner": "codex_full_cover"}
    request["bitmap_title_contract_passed"] = False
    request["bitmap_title_contract_verified_at"] = datetime.now(UTC).isoformat()
    request["bitmap_title_contract_reason"] = "ocr mismatch"

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(_metadata(output), request, output)

    assert result["publish_ready"] is False
    assert any("完整封面位图标题不满足硬合同" in reason for reason in result["blocking_reasons"])
