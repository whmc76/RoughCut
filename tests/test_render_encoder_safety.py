from roughcut.media.render import _prefer_software_encoder_for_source


def test_prefers_software_encoder_for_long_hdr_rotated_source() -> None:
    source_info = {
        "rotation_cw": 270,
        "pix_fmt": "yuv420p10le",
        "color_transfer": "arib-std-b67",
    }

    assert _prefer_software_encoder_for_source(source_info, source_duration_sec=1202.5)


def test_allows_hardware_encoder_for_short_sdr_upright_source() -> None:
    source_info = {
        "rotation_cw": 0,
        "pix_fmt": "yuv420p",
        "color_transfer": "bt709",
    }

    assert not _prefer_software_encoder_for_source(source_info, source_duration_sec=120.0)

