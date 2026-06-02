from __future__ import annotations

from roughcut.review.platform_body_quality import assess_platform_body


def test_ai_fallback_body_blocks_publish() -> None:
    result = assess_platform_body(
        "douyin",
        "这条视频主要围绕傲雷手电开箱体验展开，建议发布前人工核对品牌型号和参数后再发布。",
        content_profile={"subject_brand": "傲雷", "subject_model": "掠夺者2 mini", "subject_type": "手电"},
    )

    assert result["publish_ready"] is False
    assert any("AI 兜底" in reason for reason in result["blocking_reasons"])
    assert any("人工核对" in hint or "兜底" in hint for hint in result["repair_hints"])


def test_generic_body_without_specific_experience_blocks_publish() -> None:
    result = assess_platform_body(
        "bilibili",
        "这期内容丰富，信息量很大，全面展示了产品亮点，感兴趣的朋友不要错过。",
        content_profile={"subject_brand": "NITECORE", "subject_model": "EDC17", "subject_type": "手电"},
    )

    assert result["publish_ready"] is False
    assert "正文空泛，缺少视频里的具体动作或体验细节" in result["blocking_reasons"]
    assert "正文缺少主体锚点" in result["blocking_reasons"]


def test_body_with_subject_anchor_and_experience_detail_passes() -> None:
    result = assess_platform_body(
        "xiaohongshu",
        "NITECORE EDC17 这次上手最明显的是侧灯切换很顺，按下去阻尼不虚。"
        "镜头里能看到泛光铺得比较开，塞进口袋也没有坠手，适合当随身备用灯。",
        content_profile={"subject_brand": "NITECORE", "subject_model": "EDC17", "subject_type": "EDC手电"},
        fact_sheet={"verified": True},
    )

    assert result["publish_ready"] is True
    assert result["blocking_reasons"] == []


def test_unverified_parameter_risk_blocks_without_fact_sheet() -> None:
    result = assess_platform_body(
        "wechat_channels",
        "NITECORE EDC17 上手按键很清楚，画面里点亮后光斑铺开很快，"
        "这支有 1500 流明和 40 小时续航，是同尺寸最强选择。",
        content_profile={"subject_brand": "NITECORE", "subject_model": "EDC17", "subject_type": "手电"},
    )

    assert result["publish_ready"] is False
    assert any("未核验参数" in reason for reason in result["blocking_reasons"])
    assert any("高风险事实" in reason for reason in result["blocking_reasons"])


def test_standalone_first_is_not_blocked_as_absolute_fact() -> None:
    result = assess_platform_body(
        "xiaohongshu",
        "MAXACE 美杜莎4 这次第一眼看过去，顶配和次顶配的质感差别挺明显。"
        "上手以后主要能感到刀柄纹理、开合阻尼和细节处理不太一样。",
        content_profile={"subject_brand": "MAXACE", "subject_model": "美杜莎4", "subject_type": "折刀"},
    )

    assert result["publish_ready"] is True
    assert not any("高风险事实" in reason for reason in result["blocking_reasons"])


def test_soft_unverified_parameter_gets_warning_not_blocking() -> None:
    result = assess_platform_body(
        "douyin",
        "NITECORE EDC17 我手上这只上手按键很清楚，点亮后光斑铺得开，"
        "体感大概有 1500 流明那种亮度。",
        content_profile={"subject_brand": "NITECORE", "subject_model": "EDC17", "subject_type": "手电"},
    )

    assert result["publish_ready"] is True
    assert result["blocking_reasons"] == []
    assert any("参数" in warning for warning in result["warnings"])
