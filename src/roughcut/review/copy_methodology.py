from __future__ import annotations

from typing import Any


_GENERIC_ANTI_AI_PHRASES = (
    "方便参考",
    "避免偏差",
    "逐一展开",
    "讲透",
    "写进视频里",
    "从几个维度",
    "重点不只在",
    "帮助快速判断",
)


_ARCHETYPE_METHODS: dict[str, dict[str, Any]] = {
    "comparison_unboxing": {
        "archetype": "双版本开箱对比",
        "click_drivers": ["看差别", "看怎么选", "看值不值往上走"],
        "title_formula": "主体点名 + 对比关系 + 差别/怎么选",
        "body_formula": "先点名这条片子拍了哪两个对象，再说画面里会先看哪些差别，最后补一句实际上手后的直观感受。",
        "voice_anchors": ["像玩家到手后直接开聊", "少摘要，多对象和差别", "不要先解释创作目的"],
        "banned_phrases": list(_GENERIC_ANTI_AI_PHRASES),
    },
    "decor_unboxing": {
        "archetype": "单主体开箱上手",
        "click_drivers": ["看到手第一感觉", "看细节质感", "看上手值不值"],
        "title_formula": "主体点名 + 到手/开箱 + 最值得看的细节",
        "body_formula": "先说这次到手拍了什么，再说镜头里最容易被注意到的细节和上手感觉。",
        "voice_anchors": ["像刚到手就开拍", "少结论，多第一感受", "不要写成完整评测提纲"],
        "banned_phrases": list(_GENERIC_ANTI_AI_PHRASES),
    },
    "tutorial": {
        "archetype": "教程演示",
        "click_drivers": ["看卡点", "看怎么做", "看结果有没有解决"],
        "title_formula": "主体/动作 + 卡点/目标 + 怎么做",
        "body_formula": "先说这条解决什么问题，再说关键步骤或容易卡住的地方。",
        "voice_anchors": ["像刚做完一遍总结经验", "不要空泛铺陈", "直接给步骤和结果"],
        "banned_phrases": list(_GENERIC_ANTI_AI_PHRASES),
    },
    "generic": {
        "archetype": "真实体验分享",
        "click_drivers": ["看这条到底拍了什么", "看值不值得点开", "看有没有具体细节"],
        "title_formula": "主体点名 + 这条最值得看的点",
        "body_formula": "先说这条拍了什么，再补一个具体画面/动作/体验感受。",
        "voice_anchors": ["像创作者刚发片时的自然说明", "不要像提纲", "不要像结案报告"],
        "banned_phrases": list(_GENERIC_ANTI_AI_PHRASES),
    },
}


_PLATFORM_VOICE_OVERRIDES: dict[str, dict[str, Any]] = {
    "bilibili": {
        "voice_goal": "像熟悉题材的 UP 主发片说明，不装专家，不写论文。",
        "title_bias": "允许更长，但必须把主体和差别讲清楚。",
        "body_bias": "像发片时给观众打招呼，先说这条拍了什么，不要先讲方法论。",
    },
    "xiaohongshu": {
        "voice_goal": "像到手分享笔记，保留个人感受和生活化表达。",
        "title_bias": "短一点，有到手感和个人感受。",
        "body_bias": "像刚发笔记，能看到人和物之间的关系。",
    },
    "douyin": {
        "voice_goal": "像短视频发布文案，直给，少解释。",
        "title_bias": "先给最能拉停留的点。",
        "body_bias": "用一句到两句把对象、差别、记忆点抛出来。",
    },
    "kuaishou": {
        "voice_goal": "像当面讲实话，口语化，不端着。",
        "title_bias": "像一句会直接说出口的话。",
        "body_bias": "少包装，直说看到和摸到的东西。",
    },
    "wechat_channels": {
        "voice_goal": "稳一点，但还是要像真人，不要公文腔。",
        "title_bias": "克制，不要网感爆词。",
        "body_bias": "清楚说这条拍了什么，避免空泛总结。",
    },
    "toutiao": {
        "voice_goal": "像资讯型创作者发摘要，但不能像 AI 总结。",
        "title_bias": "判断要前置。",
        "body_bias": "有信息，但别写成分点报告。",
    },
    "youtube": {
        "voice_goal": "像视频描述，不要像 SEO 机器堆字。",
        "title_bias": "清晰可检索。",
        "body_bias": "补足观看预期和关键词，但保留人味。",
    },
    "x": {
        "voice_goal": "像一条可直接发出的短贴文。",
        "title_bias": "短促，单个观察点。",
        "body_bias": "一句观察或判断，不写简介腔。",
    },
}


def build_copy_methodology(*, intent: str, platform_key: str) -> dict[str, Any]:
    base = dict(_ARCHETYPE_METHODS.get(str(intent or "").strip(), _ARCHETYPE_METHODS["generic"]))
    platform = dict(_PLATFORM_VOICE_OVERRIDES.get(str(platform_key or "").strip(), {}))
    return {
        "intent": str(intent or "").strip() or "generic",
        "archetype": base.get("archetype") or "",
        "click_drivers": list(base.get("click_drivers") or []),
        "title_formula": str(base.get("title_formula") or "").strip(),
        "body_formula": str(base.get("body_formula") or "").strip(),
        "voice_anchors": list(base.get("voice_anchors") or []),
        "banned_phrases": list(base.get("banned_phrases") or []),
        "platform_voice_goal": str(platform.get("voice_goal") or "").strip(),
        "platform_title_bias": str(platform.get("title_bias") or "").strip(),
        "platform_body_bias": str(platform.get("body_bias") or "").strip(),
    }


def build_copy_methodology_prompt(*, intent: str, platform_key: str) -> str:
    methodology = build_copy_methodology(intent=intent, platform_key=platform_key)
    lines = [
        f"内容方法论：{methodology['archetype']}",
        f"点击动机：{' / '.join(methodology['click_drivers'])}",
        f"标题公式：{methodology['title_formula']}",
        f"正文公式：{methodology['body_formula']}",
        f"表达锚点：{'；'.join(methodology['voice_anchors'])}",
    ]
    if methodology["platform_voice_goal"]:
        lines.append(f"平台语气目标：{methodology['platform_voice_goal']}")
    if methodology["platform_title_bias"]:
        lines.append(f"平台标题偏置：{methodology['platform_title_bias']}")
    if methodology["platform_body_bias"]:
        lines.append(f"平台正文偏置：{methodology['platform_body_bias']}")
    if methodology["banned_phrases"]:
        lines.append(f"禁用表达：{'、'.join(methodology['banned_phrases'])}")
    return "\n".join(line for line in lines if line)
