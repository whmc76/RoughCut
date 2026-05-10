from roughcut.speech.subtitle_segmentation import normalize_display_numbers
from roughcut.speech.subtitle_segmentation import normalize_display_text


def test_subtitle_numeral_transcription_uses_arabic_for_codes_and_specs() -> None:
    assert normalize_display_numbers("这个EDC幺七和MT三四都在桌上") == "这个EDC17和MT34都在桌上"
    assert normalize_display_numbers("编号零六 零零号 二零二六年") == "编号06 00号 2026年"
    assert normalize_display_numbers("百分之三十 第十七代 三百流明") == "30% 第17代 300流明"
    assert normalize_display_numbers("八千流明 一万流明") == "8000流明 10000流明"
    assert normalize_display_numbers("一百二十八GB 三百毫安 五伏两安") == "128GB 300毫安 5伏2安"
    assert normalize_display_numbers("下午三点半 晚上八点零五分") == "下午3点半 晚上8点05"


def test_subtitle_numeral_transcription_handles_decimals_prices_and_ranges() -> None:
    assert normalize_display_numbers("三点五毫米 二点零版本") == "3.5毫米 2.0版本"
    assert normalize_display_numbers("二十到三十流明 三至五个档位") == "20到30流明 3至5个档位"
    assert normalize_display_numbers("3到5个配件 二到三个选择") == "三到五个配件 二到三个选择"
    assert normalize_display_numbers("十块八 三块五") == "10块8 3块5"


def test_subtitle_numeral_transcription_keeps_natural_chinese_quantities() -> None:
    assert normalize_display_numbers("这个是一把刀 一个工具 一堆配件") == "这个是一把刀 一个工具 一堆配件"
    assert normalize_display_numbers("这就是1个普通产品") == "这就是一个普通产品"
    assert normalize_display_numbers("这是1个功能键和1个参数") == "这是1个功能键和1个参数"
    assert normalize_display_numbers("我拿了1把刀 2个配件 3堆东西 4颗糖") == "我拿了一把刀 两个配件 三堆东西 四颗糖"
    assert normalize_display_numbers("还有1套方案 2支笔 3盒耗材") == "还有一套方案 两支笔 三盒耗材"
    assert normalize_display_numbers("它有1个接口和2个档位") == "它有1个接口和2个档位"
    assert normalize_display_numbers("这些东西零零散散放着") == "这些东西零零散散放着"
    assert normalize_display_numbers("一两个都行 三四个也可以") == "一两个都行 三四个也可以"
    assert normalize_display_numbers("一两天 十来个 几十块") == "一两天 十来个 几十块"


def test_display_text_applies_only_numeral_transcription_not_term_rewrites() -> None:
    assert normalize_display_text("这是EDC幺七的威虎版") == "这是EDC17的威虎版"
