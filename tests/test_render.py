from __future__ import annotations

import pytest

from roughcut.media.render import (
    _can_bake_rotation,
    _describe_stream,
    _is_expected_output,
    _rotation_filter_for_cw,
)


def test_describe_stream_uses_display_matrix_rotation():
    info = _describe_stream(
        {
            "width": 1920,
            "height": 1080,
            "side_data_list": [
                {
                    "side_data_type": "Display Matrix",
                    "rotation": -90,
                }
            ],
        }
    )

    assert info["rotation_raw"] == -90
    assert info["rotation_cw"] == 270
    assert info["display_width"] == 1080
    assert info["display_height"] == 1920
    assert info["has_display_matrix"] is True


def test_describe_stream_falls_back_to_rotate_tag():
    info = _describe_stream(
        {
            "width": 1080,
            "height": 1920,
            "tags": {"rotate": "90"},
        }
    )

    assert info["rotation_raw"] == 90
    assert info["rotation_cw"] == 90
    assert info["display_width"] == 1920
    assert info["display_height"] == 1080


def test_is_expected_output_requires_physical_landscape_and_zero_rotation():
    assert _is_expected_output(
        {
            "width": 1920,
            "height": 1080,
            "rotation_cw": 0,
        },
        1920,
        1080,
    )
    assert not _is_expected_output(
        {
            "width": 1920,
            "height": 1080,
            "rotation_cw": 270,
        },
        1920,
        1080,
    )


def test_can_bake_rotation_only_when_display_is_right_but_pixels_are_not():
    assert _can_bake_rotation(
        {
            "width": 1080,
            "height": 1920,
            "display_width": 1920,
            "display_height": 1080,
            "rotation_cw": 270,
        },
        1920,
        1080,
    )
    assert not _can_bake_rotation(
        {
            "width": 1920,
            "height": 1080,
            "display_width": 1080,
            "display_height": 1920,
            "rotation_cw": 270,
        },
        1920,
        1080,
    )


def test_rotation_filter_for_cw():
    assert _rotation_filter_for_cw(90) == "transpose=1"
    assert _rotation_filter_for_cw(180) == "hflip,vflip"
    assert _rotation_filter_for_cw(270) == "transpose=2"

    with pytest.raises(ValueError):
        _rotation_filter_for_cw(0)
