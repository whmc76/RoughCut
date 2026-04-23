from roughcut.speech.subtitle_segmentation import normalize_display_numbers


def test_keeps_single_digit_natural_quantities_as_chinese_text() -> None:
    assert normalize_display_numbers("这个是一把刀 一个工具 一堆配件") == "这个是一把刀 一个工具 一堆配件"
    assert normalize_display_numbers("我拿了1把刀 2个配件 3堆东西 4颗糖") == "我拿了一把刀 两个配件 三堆东西 四颗糖"
    assert normalize_display_numbers("还有1套方案 2支笔 3盒耗材") == "还有一套方案 两支笔 三盒耗材"


def test_keeps_spec_counts_numeric_when_followed_by_info_nouns() -> None:
    assert normalize_display_numbers("它有1个接口和2个档位") == "它有1个接口和2个档位"


def test_converts_spoken_digit_sequences_to_arabic_digits() -> None:
    assert normalize_display_numbers("编号零六 零零号 二零二六年") == "编号06 00号 2026年"
    assert normalize_display_numbers("这些东西零零散散放着") == "这些东西零零散散放着"


def test_preserves_vague_quantity_ranges() -> None:
    assert normalize_display_numbers("一两个都行 三四个也可以") == "一两个都行 三四个也可以"
