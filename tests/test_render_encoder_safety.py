from roughcut.media.render import (
    _delivery_color_filter_chain,
    _prefer_software_encoder_for_source,
    _source_needs_delivery_color_filter,
    _video_delivery_encode_args,
)


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


def test_leaves_bt709_sdr_sources_without_delivery_color_filter() -> None:
    source_info = {
        "pix_fmt": "yuv420p",
        "color_range": "tv",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
    }

    assert not _source_needs_delivery_color_filter(source_info)
    assert _delivery_color_filter_chain(source_info) == []


def test_builds_hdr_to_bt709_delivery_filter_chain() -> None:
    source_info = {
        "pix_fmt": "yuv420p10le",
        "color_range": "tv",
        "color_space": "bt2020nc",
        "color_transfer": "arib-std-b67",
        "color_primaries": "bt2020",
    }

    filters = _delivery_color_filter_chain(source_info)
    filter_text = ",".join(filters)

    assert "zscale=" in filter_text
    assert "color_trc=arib-std-b67" in filter_text
    assert "transfer=linear" in filter_text
    assert "tonemap=tonemap=hable" in filter_text
    assert "primaries=bt709" in filter_text
    assert "transfer=bt709" in filter_text
    assert "matrix=bt709" in filter_text
    assert filters[-1] == "format=yuv420p"


def test_builds_full_range_sdr_to_limited_bt709_filter_chain() -> None:
    source_info = {
        "pix_fmt": "yuv420p",
        "color_range": "pc",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
    }

    filters = _delivery_color_filter_chain(source_info)
    filter_text = ",".join(filters)

    assert "range=full" in filter_text
    assert "range=limited" in filter_text
    assert "tonemap=" not in filter_text


def test_delivery_encode_args_mark_bt709_limited_range() -> None:
    args = _video_delivery_encode_args(prefer_hardware=False)

    assert "-colorspace" in args
    assert args[args.index("-colorspace") + 1] == "bt709"
    assert args[args.index("-color_trc") + 1] == "bt709"
    assert args[args.index("-color_primaries") + 1] == "bt709"
    assert args[args.index("-color_range") + 1] == "tv"
