from roughcut.media.subtitles import _select_keyword_highlight_spans


def _highlighted_parts(text: str) -> list[str]:
    return [
        text[start:end]
        for start, end in _select_keyword_highlight_spans(
            text,
            unit_role="focus",
            explicit_terms=[],
        )
    ]


def test_version_highlight_expands_to_model_prefix() -> None:
    assert "Ultra版本" in _highlighted_parts("是他家新出的这个Ultra版本")


def test_colorway_highlight_expands_to_descriptive_prefix() -> None:
    assert "黑绿配色" in _highlighted_parts("今年主打的黑绿配色")


def test_product_demo_terms_are_highlighted() -> None:
    parts = _highlighted_parts("这里是锁定细节和快拆结构")

    assert "锁定" in parts
    assert "快拆" in parts
