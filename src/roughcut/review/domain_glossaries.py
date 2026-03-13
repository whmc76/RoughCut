from __future__ import annotations

from collections import OrderedDict
from typing import Any
import re


GlossaryTermLike = dict[str, Any]


_DOMAIN_TERM_LIBRARY: dict[str, tuple[GlossaryTermLike, ...]] = {
    "gear": (
        {"correct_form": "EDC", "wrong_forms": ["一滴西", "诶滴西", "E D C"], "category": "term", "context_hint": "Everyday Carry"},
        {"correct_form": "FAS", "wrong_forms": ["法斯", "发斯", "F A S"], "category": "term", "context_hint": "圈内缩写"},
        {"correct_form": "潮玩", "wrong_forms": ["朝玩"], "category": "gear", "context_hint": "收藏向内容"},
        {"correct_form": "户外", "wrong_forms": ["户外儿"], "category": "gear", "context_hint": "户外装备"},
        {"correct_form": "战术", "wrong_forms": ["站术"], "category": "gear", "context_hint": "战术风格"},
        {"correct_form": "大佬", "wrong_forms": ["大老"], "category": "slang", "context_hint": "口播称呼"},
        {"correct_form": "贴片", "wrong_forms": ["揭片", "接片"], "category": "process", "context_hint": "装饰件/镶片"},
        {"correct_form": "电镀", "wrong_forms": ["电路", "电渡", "店镀"], "category": "process", "context_hint": "表面处理"},
        {"correct_form": "渐变", "wrong_forms": ["键变", "间变", "见变"], "category": "visual", "context_hint": "颜色过渡"},
        {"correct_form": "图纸", "wrong_forms": ["图指", "图址", "图子"], "category": "design", "context_hint": "设计方案"},
        {"correct_form": "美中不足", "wrong_forms": ["美中部组", "美中不组", "美中布足"], "category": "phrase", "context_hint": "固定表达"},
        {"correct_form": "极致", "wrong_forms": [], "category": "style", "context_hint": "审美表达"},
        {
            "correct_form": "极致华丽",
            "wrong_forms": ["经质的华历", "经质华历", "经致的华历", "精质的华历", "经质的华丽", "经致的华丽"],
            "category": "phrase",
            "context_hint": "固定表达",
        },
        {"correct_form": "阳极", "wrong_forms": ["阳节"], "category": "process", "context_hint": "阳极氧化"},
        {"correct_form": "雾面", "wrong_forms": ["屋面"], "category": "visual", "context_hint": "表面质感"},
        {"correct_form": "涂装", "wrong_forms": ["图装"], "category": "process", "context_hint": "表面工艺"},
        {"correct_form": "盒损", "wrong_forms": ["合损"], "category": "gear", "context_hint": "包装状态"},
        {"correct_form": "可动", "wrong_forms": ["可洞"], "category": "gear", "context_hint": "结构描述"},
        {"correct_form": "关节", "wrong_forms": ["关结"], "category": "gear", "context_hint": "可动结构"},
        {"correct_form": "盲盒", "wrong_forms": ["忙盒"], "category": "gear", "context_hint": "潮玩品类"},
        {"correct_form": "隐藏款", "wrong_forms": ["银藏款"], "category": "gear", "context_hint": "潮玩术语"},
        {"correct_form": "官图", "wrong_forms": ["关图"], "category": "gear", "context_hint": "官方图片"},
        {"correct_form": "原型", "wrong_forms": ["原行"], "category": "gear", "context_hint": "设计打样"},
        {"correct_form": "素体", "wrong_forms": ["速体"], "category": "gear", "context_hint": "结构描述"},
        {"correct_form": "露营", "wrong_forms": ["路营"], "category": "gear", "context_hint": "户外活动"},
        {"correct_form": "徒步", "wrong_forms": ["图步"], "category": "gear", "context_hint": "户外活动"},
        {"correct_form": "营地", "wrong_forms": ["迎地"], "category": "gear", "context_hint": "户外场景"},
        {"correct_form": "战术笔", "wrong_forms": ["站术笔"], "category": "gear", "context_hint": "EDC战术装备"},
        {"correct_form": "快挂", "wrong_forms": ["快卦"], "category": "gear", "context_hint": "挂载配件"},
        {"correct_form": "鞘套", "wrong_forms": ["窍套"], "category": "gear", "context_hint": "收纳配件"},
        {"correct_form": "背夹", "wrong_forms": ["背甲"], "category": "gear", "context_hint": "折刀/工具配件"},
    ),
    "edc": (
        {"correct_form": "大佬", "wrong_forms": ["大老"], "category": "slang", "context_hint": "口播称呼"},
        {"correct_form": "贴片", "wrong_forms": ["揭片", "接片"], "category": "process", "context_hint": "装饰件/镶片"},
        {"correct_form": "电镀", "wrong_forms": ["电路", "电渡", "店镀"], "category": "process", "context_hint": "表面处理"},
        {"correct_form": "渐变", "wrong_forms": ["键变", "间变", "见变"], "category": "visual", "context_hint": "颜色过渡"},
        {"correct_form": "FAS", "wrong_forms": ["法斯", "发斯", "F A S"], "category": "term", "context_hint": "圈内缩写"},
        {"correct_form": "EDC", "wrong_forms": ["一滴西", "诶滴西", "E D C"], "category": "term", "context_hint": "Everyday Carry"},
        {"correct_form": "图纸", "wrong_forms": ["图指", "图址", "图子"], "category": "design", "context_hint": "设计方案"},
        {"correct_form": "美中不足", "wrong_forms": ["美中部组", "美中不组", "美中布足"], "category": "phrase", "context_hint": "固定表达"},
        {"correct_form": "极致", "wrong_forms": [], "category": "style", "context_hint": "审美表达"},
        {
            "correct_form": "极致华丽",
            "wrong_forms": ["经质的华历", "经质华历", "经致的华历", "精质的华历", "经质的华丽", "经致的华丽"],
            "category": "phrase",
            "context_hint": "固定表达",
        },
        {"correct_form": "阳极", "wrong_forms": ["阳节"], "category": "process", "context_hint": "阳极氧化"},
        {"correct_form": "雾面", "wrong_forms": ["屋面"], "category": "visual", "context_hint": "表面质感"},
    ),
    "tech": (
        {"correct_form": "芯片", "wrong_forms": ["新片", "心片"], "category": "tech_term", "context_hint": "硬件术语"},
        {"correct_form": "显卡", "wrong_forms": ["险卡", "显咔"], "category": "tech_term", "context_hint": "硬件术语"},
        {"correct_form": "处理器", "wrong_forms": ["处里器", "处理机"], "category": "tech_term", "context_hint": "CPU"},
        {"correct_form": "续航", "wrong_forms": ["序航", "续行"], "category": "tech_term", "context_hint": "设备体验"},
        {"correct_form": "散热", "wrong_forms": ["散热器儿", "散热儿"], "category": "tech_term", "context_hint": "设备体验"},
        {"correct_form": "传感器", "wrong_forms": ["传感机", "传感其"], "category": "tech_term", "context_hint": "硬件术语"},
        {"correct_form": "分辨率", "wrong_forms": ["分辩率", "分辨律"], "category": "tech_term", "context_hint": "显示参数"},
        {"correct_form": "延迟", "wrong_forms": ["言迟", "延时"], "category": "tech_term", "context_hint": "设备体验"},
        {"correct_form": "快充", "wrong_forms": ["快冲"], "category": "tech_term", "context_hint": "充电术语"},
        {"correct_form": "固件", "wrong_forms": ["顾件"], "category": "tech_term", "context_hint": "固件更新"},
        {"correct_form": "RunningHub", "wrong_forms": ["running hub", "瑞宁哈布", "润宁哈布", "RH"], "category": "tech_brand", "context_hint": "AI创作平台"},
        {"correct_form": "ComfyUI", "wrong_forms": ["comfy ui", "康菲UI", "康飞UI", "咖啡外"], "category": "tech_brand", "context_hint": "AI工作流工具"},
        {"correct_form": "OpenClaw", "wrong_forms": ["open claw", "欧喷扣", "欧喷爪"], "category": "tech_brand", "context_hint": "AI Agent 框架"},
        {"correct_form": "无限画布", "wrong_forms": ["无边画布", "无限画板"], "category": "tech_feature", "context_hint": "创作功能"},
        {"correct_form": "节点编排", "wrong_forms": ["节点排布"], "category": "tech_feature", "context_hint": "工作流设计"},
    ),
    "ai": (
        {"correct_form": "提示词", "wrong_forms": ["提词", "提示辞"], "category": "tech_term", "context_hint": "Prompt"},
        {"correct_form": "工作流", "wrong_forms": ["工作留", "工做流"], "category": "tech_term", "context_hint": "AI流程"},
        {"correct_form": "模型", "wrong_forms": ["磨型"], "category": "tech_term", "context_hint": "AI模型"},
        {"correct_form": "微调", "wrong_forms": ["微条"], "category": "tech_term", "context_hint": "Fine-tuning"},
        {"correct_form": "推理", "wrong_forms": ["推力"], "category": "tech_term", "context_hint": "Inference"},
        {"correct_form": "多模态", "wrong_forms": ["多模太", "多魔态"], "category": "tech_term", "context_hint": "Multimodal"},
        {"correct_form": "智能体", "wrong_forms": ["智能提"], "category": "tech_term", "context_hint": "Agent"},
        {"correct_form": "向量数据库", "wrong_forms": ["向量数局库", "向量数据库儿"], "category": "tech_term", "context_hint": "RAG"},
        {"correct_form": "RAG", "wrong_forms": ["瑞格", "R A G"], "category": "tech_term", "context_hint": "检索增强生成"},
        {"correct_form": "LoRA", "wrong_forms": ["罗拉", "L O R A"], "category": "tech_term", "context_hint": "微调方法"},
        {"correct_form": "Agent", "wrong_forms": ["诶煎特", "A G E N T"], "category": "tech_term", "context_hint": "智能体"},
        {"correct_form": "Token", "wrong_forms": ["头肯", "T O K E N"], "category": "tech_term", "context_hint": "模型计量单位"},
        {"correct_form": "Checkpoint", "wrong_forms": ["check point", "切克坡因特"], "category": "tech_term", "context_hint": "模型权重"},
        {"correct_form": "ControlNet", "wrong_forms": ["control net", "康戳耐特"], "category": "tech_term", "context_hint": "图像控制"},
        {"correct_form": "Flux", "wrong_forms": ["FLUX模型儿"], "category": "tech_term", "context_hint": "图像模型"},
        {"correct_form": "MCP", "wrong_forms": ["M C P"], "category": "tech_term", "context_hint": "模型上下文协议"},
        {"correct_form": "OpenClaw", "wrong_forms": ["open claw", "欧喷扣", "欧喷爪"], "category": "tech_brand", "context_hint": "AI Agent 框架"},
        {"correct_form": "RunningHub", "wrong_forms": ["running hub", "瑞宁哈布", "润宁哈布", "RH"], "category": "tech_brand", "context_hint": "AI创作平台"},
        {"correct_form": "ComfyUI", "wrong_forms": ["comfy ui", "康菲UI", "康飞UI", "咖啡外"], "category": "tech_brand", "context_hint": "AI工作流工具"},
        {"correct_form": "无限画布", "wrong_forms": ["无边画布", "无限画板"], "category": "tech_feature", "context_hint": "创作功能"},
        {"correct_form": "节点编排", "wrong_forms": ["节点排布"], "category": "tech_feature", "context_hint": "工作流设计"},
    ),
    "travel": (
        {"correct_form": "citywalk", "wrong_forms": ["city walk", "city沃克"], "category": "travel", "context_hint": "旅行方式"},
        {"correct_form": "行程", "wrong_forms": ["形成"], "category": "travel", "context_hint": "旅行安排"},
        {"correct_form": "机酒", "wrong_forms": ["积久"], "category": "travel", "context_hint": "机票酒店"},
        {"correct_form": "转机", "wrong_forms": ["转积"], "category": "travel", "context_hint": "航空出行"},
        {"correct_form": "值机", "wrong_forms": ["直机"], "category": "travel", "context_hint": "航空出行"},
        {"correct_form": "登机牌", "wrong_forms": ["登机排"], "category": "travel", "context_hint": "航空出行"},
        {"correct_form": "民宿", "wrong_forms": ["名宿"], "category": "travel", "context_hint": "住宿类型"},
        {"correct_form": "攻略", "wrong_forms": ["工略"], "category": "travel", "context_hint": "旅游规划"},
        {"correct_form": "避雷", "wrong_forms": ["壁垒"], "category": "travel", "context_hint": "避坑表达"},
        {"correct_form": "出片", "wrong_forms": ["出骗"], "category": "travel", "context_hint": "拍照出片"},
    ),
    "food": (
        {"correct_form": "探店", "wrong_forms": ["炭店"], "category": "food", "context_hint": "美食探店"},
        {"correct_form": "口感", "wrong_forms": ["口杆"], "category": "food", "context_hint": "试吃表达"},
        {"correct_form": "锅气", "wrong_forms": ["过气"], "category": "food", "context_hint": "中餐术语"},
        {"correct_form": "回甘", "wrong_forms": ["回肝"], "category": "food", "context_hint": "饮品/甜品表达"},
        {"correct_form": "性价比", "wrong_forms": ["性价笔"], "category": "food", "context_hint": "消费判断"},
        {"correct_form": "招牌", "wrong_forms": ["招排"], "category": "food", "context_hint": "菜品术语"},
        {"correct_form": "爆汁", "wrong_forms": ["爆支"], "category": "food", "context_hint": "口感表达"},
        {"correct_form": "拉花", "wrong_forms": ["拉华"], "category": "food", "context_hint": "咖啡术语"},
        {"correct_form": "挂耳", "wrong_forms": ["挂饵"], "category": "food", "context_hint": "咖啡术语"},
        {"correct_form": "熟成", "wrong_forms": ["熟城"], "category": "food", "context_hint": "餐饮术语"},
    ),
    "finance": (
        {"correct_form": "财经", "wrong_forms": ["财金"], "category": "finance", "context_hint": "财经内容"},
        {"correct_form": "金融", "wrong_forms": ["今融"], "category": "finance", "context_hint": "金融内容"},
        {"correct_form": "利率", "wrong_forms": ["利律"], "category": "finance", "context_hint": "宏观指标"},
        {"correct_form": "汇率", "wrong_forms": ["汇律"], "category": "finance", "context_hint": "外汇市场"},
        {"correct_form": "通胀", "wrong_forms": ["通涨"], "category": "finance", "context_hint": "宏观指标"},
        {"correct_form": "降息", "wrong_forms": ["讲习"], "category": "finance", "context_hint": "货币政策"},
        {"correct_form": "加息", "wrong_forms": ["家息"], "category": "finance", "context_hint": "货币政策"},
        {"correct_form": "美联储", "wrong_forms": ["美联处", "美联楚"], "category": "finance", "context_hint": "央行机构"},
        {"correct_form": "纳斯达克", "wrong_forms": ["纳斯打克"], "category": "finance", "context_hint": "指数名称"},
        {"correct_form": "标普", "wrong_forms": ["标谱"], "category": "finance", "context_hint": "指数简称"},
        {"correct_form": "财报", "wrong_forms": ["财爆"], "category": "finance", "context_hint": "公司披露"},
        {"correct_form": "市盈率", "wrong_forms": ["市赢率"], "category": "finance", "context_hint": "估值指标"},
    ),
    "news": (
        {"correct_form": "国际新闻", "wrong_forms": ["国际新文"], "category": "news", "context_hint": "新闻栏目"},
        {"correct_form": "外媒", "wrong_forms": ["外没"], "category": "news", "context_hint": "消息来源"},
        {"correct_form": "局势", "wrong_forms": ["局事"], "category": "news", "context_hint": "国际局势"},
        {"correct_form": "停火", "wrong_forms": ["停活"], "category": "news", "context_hint": "国际冲突"},
        {"correct_form": "制裁", "wrong_forms": ["制才"], "category": "news", "context_hint": "国际关系"},
        {"correct_form": "峰会", "wrong_forms": ["风会"], "category": "news", "context_hint": "国际会议"},
        {"correct_form": "外交", "wrong_forms": ["外郊"], "category": "news", "context_hint": "国际关系"},
        {"correct_form": "联合国", "wrong_forms": ["联合锅"], "category": "news", "context_hint": "国际组织"},
        {"correct_form": "北约", "wrong_forms": ["北药"], "category": "news", "context_hint": "国际组织"},
        {"correct_form": "欧盟", "wrong_forms": ["欧蒙"], "category": "news", "context_hint": "国际组织"},
        {"correct_form": "总统", "wrong_forms": ["总桶"], "category": "news", "context_hint": "政治人物"},
        {"correct_form": "总理", "wrong_forms": ["总里"], "category": "news", "context_hint": "政治人物"},
    ),
    "sports": (
        {"correct_form": "体育", "wrong_forms": ["体玉"], "category": "sports", "context_hint": "体育内容"},
        {"correct_form": "赛事", "wrong_forms": ["赛式"], "category": "sports", "context_hint": "比赛内容"},
        {"correct_form": "比分", "wrong_forms": ["比份"], "category": "sports", "context_hint": "比赛结果"},
        {"correct_form": "加时", "wrong_forms": ["加十"], "category": "sports", "context_hint": "比赛进程"},
        {"correct_form": "绝杀", "wrong_forms": ["绝沙"], "category": "sports", "context_hint": "比赛结果"},
        {"correct_form": "点球", "wrong_forms": ["点求"], "category": "sports", "context_hint": "足球术语"},
        {"correct_form": "越位", "wrong_forms": ["月位"], "category": "sports", "context_hint": "足球术语"},
        {"correct_form": "三分", "wrong_forms": ["三份"], "category": "sports", "context_hint": "篮球术语"},
        {"correct_form": "篮板", "wrong_forms": ["蓝板"], "category": "sports", "context_hint": "篮球术语"},
        {"correct_form": "助攻", "wrong_forms": ["主攻"], "category": "sports", "context_hint": "篮球术语"},
        {"correct_form": "季后赛", "wrong_forms": ["记后赛"], "category": "sports", "context_hint": "联赛阶段"},
        {"correct_form": "世界杯", "wrong_forms": ["世界悲"], "category": "sports", "context_hint": "国际赛事"},
    ),
    "toy": (
        {"correct_form": "潮玩", "wrong_forms": ["朝玩"], "category": "toy", "context_hint": "玩具收藏"},
        {"correct_form": "盲盒", "wrong_forms": ["忙盒"], "category": "toy", "context_hint": "潮玩品类"},
        {"correct_form": "隐藏款", "wrong_forms": ["银藏款"], "category": "toy", "context_hint": "潮玩术语"},
        {"correct_form": "官图", "wrong_forms": ["关图"], "category": "toy", "context_hint": "官方图片"},
        {"correct_form": "原型", "wrong_forms": ["原行"], "category": "toy", "context_hint": "玩具设计"},
        {"correct_form": "涂装", "wrong_forms": ["图装"], "category": "toy", "context_hint": "表面工艺"},
        {"correct_form": "素体", "wrong_forms": ["速体"], "category": "toy", "context_hint": "玩具结构"},
        {"correct_form": "关节", "wrong_forms": ["关结"], "category": "toy", "context_hint": "可动结构"},
        {"correct_form": "可动", "wrong_forms": ["可洞"], "category": "toy", "context_hint": "玩具结构"},
        {"correct_form": "盒损", "wrong_forms": ["合损"], "category": "toy", "context_hint": "包装状态"},
    ),
}

_CHANNEL_PROFILE_DOMAINS: dict[str, tuple[str, ...]] = {
    "edc_tactical": ("gear",),
    "screen_tutorial": ("tech", "ai"),
    "vlog_daily": ("travel",),
    "talking_head_commentary": ("tech", "ai"),
    "gameplay_highlight": ("tech",),
    "food_explore": ("food",),
    "unboxing_default": ("gear", "tech"),
    "unboxing_limited": ("gear", "tech"),
    "unboxing_upgrade": ("gear", "tech"),
    "news_briefing": ("news", "finance"),
    "market_watch": ("finance", "news"),
    "sports_highlight": ("sports",),
}

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "gear": (
        "EDC", "FAS", "折刀", "刀", "钛", "柄材", "钢材", "背夹", "工具钳", "彩雕", "深雕",
        "潮玩", "盲盒", "隐藏款", "官图", "原型", "涂装", "素体", "关节", "可动", "盒损", "手办",
        "户外", "战术", "露营", "徒步", "营地", "快挂", "鞘套", "战术笔",
    ),
    "edc": ("EDC", "FAS", "折刀", "刀", "钛", "柄材", "钢材", "背夹", "工具钳", "彩雕", "深雕"),
    "tech": ("芯片", "显卡", "处理器", "续航", "屏幕", "相机", "手机", "笔记本", "耳机", "快充", "固件", "RunningHub", "ComfyUI", "OpenClaw", "无限画布", "节点编排"),
    "ai": ("AI", "提示词", "工作流", "模型", "微调", "推理", "多模态", "智能体", "RAG", "LoRA", "Agent", "MCP", "Checkpoint", "ControlNet", "Flux", "RunningHub", "ComfyUI", "OpenClaw", "无限画布", "节点编排"),
    "travel": ("旅行", "出行", "机票", "酒店", "民宿", "值机", "citywalk", "攻略", "景点", "登机"),
    "food": ("探店", "试吃", "口感", "锅气", "回甘", "拉花", "挂耳", "熟成", "奶茶", "火锅", "甜品", "烧烤"),
    "finance": ("财经", "金融", "利率", "汇率", "通胀", "降息", "加息", "美联储", "纳斯达克", "标普", "财报", "市盈率"),
    "news": ("国际新闻", "外媒", "局势", "停火", "制裁", "峰会", "外交", "联合国", "北约", "欧盟", "总统", "总理"),
    "sports": ("体育", "赛事", "比分", "加时", "绝杀", "点球", "越位", "三分", "篮板", "助攻", "季后赛", "世界杯"),
    "toy": ("潮玩", "盲盒", "隐藏款", "官图", "原型", "涂装", "素体", "关节", "可动", "盒损", "手办"),
}

_DOMAIN_BUNDLES: dict[str, tuple[str, ...]] = {
    "gear": ("gear", "edc", "toy"),
}

_VISIBLE_DOMAIN_PACKS: tuple[str, ...] = (
    "gear",
    "tech",
    "ai",
    "travel",
    "food",
    "finance",
    "news",
    "sports",
)


def resolve_builtin_glossary_terms(
    *,
    channel_profile: str | None,
    content_profile: dict[str, Any] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
    source_name: str | None = None,
) -> list[GlossaryTermLike]:
    domains = detect_glossary_domains(
        channel_profile=channel_profile,
        content_profile=content_profile,
        subtitle_items=subtitle_items,
        source_name=source_name,
    )
    merged: list[GlossaryTermLike] = []
    for domain in domains:
        expanded_domains = _DOMAIN_BUNDLES.get(domain, (domain,))
        for expanded in expanded_domains:
            merged.extend(_DOMAIN_TERM_LIBRARY.get(expanded, ()))
    return merge_glossary_terms([], merged)


def merge_glossary_terms(
    base_terms: list[GlossaryTermLike] | None,
    extra_terms: list[GlossaryTermLike] | None,
) -> list[GlossaryTermLike]:
    merged: OrderedDict[str, GlossaryTermLike] = OrderedDict()
    for collection in (base_terms or [], extra_terms or []):
        for raw in collection:
            correct_form = str(raw.get("correct_form") or "").strip()
            if not correct_form:
                continue
            current = merged.get(correct_form, {"correct_form": correct_form, "wrong_forms": []})
            wrong_forms = list(current.get("wrong_forms") or [])
            seen = {str(item).strip() for item in wrong_forms if str(item).strip()}
            for wrong in raw.get("wrong_forms") or []:
                token = str(wrong or "").strip()
                if token and token != correct_form and token not in seen:
                    seen.add(token)
                    wrong_forms.append(token)
            current["wrong_forms"] = wrong_forms
            if raw.get("category") and not current.get("category"):
                current["category"] = raw.get("category")
            if raw.get("context_hint") and not current.get("context_hint"):
                current["context_hint"] = raw.get("context_hint")
            merged[correct_form] = current
    return list(merged.values())


def detect_glossary_domains(
    *,
    channel_profile: str | None,
    content_profile: dict[str, Any] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
    source_name: str | None = None,
) -> list[str]:
    domains: list[str] = []
    for domain in _CHANNEL_PROFILE_DOMAINS.get(str(channel_profile or "").strip(), ()):
        if domain not in domains:
            domains.append(domain)

    haystacks: list[str] = []
    if source_name:
        haystacks.append(str(source_name))
    for key in ("subject_brand", "subject_model", "subject_type", "video_theme", "summary", "hook_line"):
        haystacks.append(str((content_profile or {}).get(key) or ""))
    for item in subtitle_items or []:
        haystacks.append(str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or ""))
    joined = " ".join(haystacks).upper()

    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(keyword.upper() in joined for keyword in keywords) and domain not in domains:
            domains.append(domain)

    if any(domain in domains for domain in ("gear", "edc", "toy")):
        domains = ["gear", *[domain for domain in domains if domain not in {"gear", "edc", "toy"}]]

    if not domains:
        domains.append("tech")
    return domains


def build_domain_signal_summary(domains: list[str]) -> str:
    ordered = [domain for domain in domains if domain in _DOMAIN_TERM_LIBRARY]
    return ", ".join(ordered)


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(text or "")))


def list_builtin_glossary_packs() -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    for domain in _VISIBLE_DOMAIN_PACKS:
        expanded_domains = _DOMAIN_BUNDLES.get(domain, (domain,))
        terms = merge_glossary_terms(
            [],
            [
                term
                for expanded in expanded_domains
                for term in _DOMAIN_TERM_LIBRARY.get(expanded, ())
            ],
        )
        presets = sorted(
            preset
            for preset, domains in _CHANNEL_PROFILE_DOMAINS.items()
            if domain in domains
        )
        packs.append(
            {
                "domain": domain,
                "presets": presets,
                "term_count": len(terms),
                "terms": terms,
            }
        )
    return packs
