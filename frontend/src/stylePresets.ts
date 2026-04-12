export type StyleGroup = {
  id: string;
  label: string;
  description: string;
};

export type StylePreset = {
  key: string;
  label: string;
  groupId: string;
  summary: string;
  accent: string;
  badge: string;
  sampleTop: string;
  sampleBottom: string;
  sampleFoot: string;
};

export type StyleTemplateBundle = {
  key: string;
  label: string;
  badge: string;
  summary: string;
  previewPath: string;
  comparePreviewPath: string;
  audience: string;
  outcome: string;
  configPatch: {
    subtitle_style: string;
    subtitle_motion_style: string;
    smart_effect_style: string;
    cover_style: string;
    title_style: string;
    copy_style: string;
  };
};

const legacyStyleAliases: Record<string, string> = {
  smart_effect_rhythm: "smart_effect_commercial",
};

export const subtitleStyleGroups: StyleGroup[] = [
  { id: "shortvideo", label: "短视频爆点", description: "高对比、高识别度，适合开箱、强情绪口播和高 CTR 剪法。" },
  { id: "clean", label: "清爽信息流", description: "更克制的阅读型字幕，适合教程、知识流和录屏讲解。" },
  { id: "premium", label: "品牌质感", description: "偏审美和质感表达，适合精品、收藏、生活方式内容。" },
  { id: "documentary", label: "纪实说明", description: "稳定、可信、弱打扰，适合复盘、纪录和说明型视频。" },
  { id: "campaign", label: "促销活动", description: "价格、优惠、活动提醒更强，适合卖货和节点推广。" },
];

export const subtitleTemplateBundles: StyleTemplateBundle[] = [
  {
    key: "impact_commerce",
    label: "爆点带货",
    badge: "高转化",
    summary: "开场就给结论，重点词爆出更狠，适合优惠、卖点、升级型内容。",
    previewPath: "/style-template-previews/impact-commerce.png",
    comparePreviewPath: "/style-template-previews/compare-impact-commerce.png",
    audience: "适合开箱卖点、活动提醒、利益点导向的视频。",
    outcome: "客户会先看到主词爆点，再看到 CTA 词接力出现。",
    configPatch: {
      subtitle_style: "sale_banner",
      subtitle_motion_style: "motion_strobe",
      smart_effect_style: "smart_effect_punch",
      cover_style: "ecommerce_sale",
      title_style: "double_banner",
      copy_style: "attention_grabbing",
    },
  },
  {
    key: "hardcore_specs",
    label: "硬核参数",
    badge: "参数党",
    summary: "型号、参数、接口和结论更清楚，适合测评、教程和硬件拆解。",
    previewPath: "/style-template-previews/hardcore-specs.png",
    comparePreviewPath: "/style-template-previews/compare-hardcore-specs.png",
    audience: "适合数码评测、结构分析、知识流和操作讲解。",
    outcome: "客户会先看到参数主词，再看到补充词弱一档跟进。",
    configPatch: {
      subtitle_style: "keyword_highlight",
      subtitle_motion_style: "motion_glitch",
      smart_effect_style: "smart_effect_glitch",
      cover_style: "clean_lab",
      title_style: "tutorial_blueprint",
      copy_style: "trusted_expert",
    },
  },
  {
    key: "suspense_teaser",
    label: "悬念预告",
    badge: "情绪钩子",
    summary: "先压住信息，再让关键结论补一拍炸出来，适合预告和剧情式展开。",
    previewPath: "/style-template-previews/suspense-teaser.png",
    comparePreviewPath: "/style-template-previews/compare-suspense-teaser.png",
    audience: "适合悬念导向、情绪铺垫、升级揭秘和片段预告。",
    outcome: "客户会看到热橙钩子和后置爆词，明显比普通口播更吊胃口。",
    configPatch: {
      subtitle_style: "teaser_glow",
      subtitle_motion_style: "motion_echo",
      smart_effect_style: "smart_effect_cinematic",
      cover_style: "cinema_teaser",
      title_style: "neon_night",
      copy_style: "emotional_story",
    },
  },
  {
    key: "restrained_explainer",
    label: "克制说明",
    badge: "稳读型",
    summary: "信息优先，但重点词仍然有层级，不会再整句平铺过去。",
    previewPath: "/style-template-previews/restrained-explainer.png",
    comparePreviewPath: "/style-template-previews/compare-restrained-explainer.png",
    audience: "适合教程、工作流、复盘和长口播说明型视频。",
    outcome: "客户会感觉清楚、专业、稳，但重点词仍然能被一眼抓住。",
    configPatch: {
      subtitle_style: "amber_news",
      subtitle_motion_style: "motion_slide",
      smart_effect_style: "smart_effect_minimal",
      cover_style: "tutorial_card",
      title_style: "documentary_stamp",
      copy_style: "balanced",
    },
  },
];

export const subtitleMotionGroups: StyleGroup[] = [
  { id: "timing", label: "时间动效", description: "入场/退场更明显，强调节奏感和视觉记忆。"},
  { id: "word", label: "逐词动效", description: "同一行里出现不同的节奏变化，适合情绪口播。"},
  { id: "scene", label: "场景冲击", description: "更夸张的缩放、抖动和跳剪风格，适合强视觉风格内容。"},
];

export const smartEffectGroups: StyleGroup[] = [
  { id: "impact", label: "商业爆点", description: "强调爆点、冲击转场和强结论镜头，适合高能短视频。" },
  { id: "cyber", label: "赛博视觉", description: "色偏、故障、数字感和机械气氛更明显，适合科技和潮流内容。" },
  { id: "atmosphere", label: "氛围推进", description: "强调情绪、层次、光感和镜头推进，适合预告和质感表达。" },
  { id: "restrained", label: "克制表达", description: "保留风格化，但不让特效盖过主体和信息。" },
];

export const coverStyleGroups: StyleGroup[] = [
  { id: "adaptive", label: "平台联动", description: "由平台策略和内容主题自动决定封面包装方向。" },
  { id: "product", label: "产品展示", description: "围绕主体和卖点构图，适合开箱、升级、测评。" },
  { id: "brand", label: "品牌高级感", description: "减少信息噪音，偏品牌海报和精品展示。" },
  { id: "cyber", label: "赛博潮流", description: "高对比、霓虹、机械感，适合数码和硬核装备。" },
  { id: "content", label: "内容分型", description: "按教程、vlog、纪录和生活方式分别包装。" },
  { id: "commerce", label: "卖货转化", description: "强调利益点、价格感和行动动机。" },
  { id: "cinema", label: "海报预告", description: "更像片头海报和预告片视觉，适合情绪表达。" },
];

export const titleStyleGroups: StyleGroup[] = [
  { id: "adaptive", label: "策略自动联动", description: "默认跟随 5 套平台策略切换标题模板，不手动锁死。" },
  { id: "impact", label: "冲击大字", description: "字效更重，适合爆点、升级、强结论表达。" },
  { id: "banner", label: "横幅条幅", description: "更像剪映热门模板，层级强、横幅感明显。" },
  { id: "premium", label: "高级海报", description: "偏收藏、精品、质感表达，少一点喧闹。" },
  { id: "editorial", label: "编辑纪实", description: "像专题封面或纪录片标题，强调信息秩序。" },
];

export const copyStyleGroups: StyleGroup[] = [
  { id: "growth", label: "增长导向", description: "优先点击率、爆点感和传播性，适合默认全局策略。" },
  { id: "balanced", label: "平衡稳妥", description: "兼顾吸引力和自然度，不容易显得过火。" },
  { id: "brand", label: "品牌表达", description: "更像编辑和品牌文案，克制但有质感。" },
  { id: "persona", label: "人设表达", description: "按专家感、玩梗感、情绪叙事区分口吻。" },
];

export const subtitleStylePresets: StylePreset[] = [
  { key: "bold_yellow_outline", label: "粗黄描边", groupId: "shortvideo", summary: "经典爆款大字，手机端最稳。", accent: "#f8c94b", badge: "爆点", sampleTop: "开箱爽点", sampleBottom: "大字描边", sampleFoot: "适合情绪口播" },
  { key: "bubble_pop", label: "圆角气泡", groupId: "shortvideo", summary: "轻松亲和，适合 vlog 和轻口播。", accent: "#ff8f6b", badge: "轻松", sampleTop: "今天这一包", sampleBottom: "真能打", sampleFoot: "更像生活内容" },
  { key: "keyword_highlight", label: "关键词高亮", groupId: "shortvideo", summary: "整句稳读，重点词更醒目。", accent: "#f26c6c", badge: "重点", sampleTop: "真正值得看的是", sampleBottom: "升级细节", sampleFoot: "参数词更清楚" },
  { key: "punch_red", label: "爆点红字", groupId: "shortvideo", summary: "强提醒和强结论表达。", accent: "#ff5a4f", badge: "强提醒", sampleTop: "这次真的", sampleBottom: "升级了", sampleFoot: "冲击力最强" },
  { key: "cyber_orange", label: "赛博橙光", groupId: "shortvideo", summary: "热能感和速度感更强。", accent: "#ff8d3a", badge: "赛博", sampleTop: "实测下来", sampleBottom: "够猛", sampleFoot: "适合硬核节奏" },
  { key: "streamer_duo", label: "主播双色", groupId: "shortvideo", summary: "双主色分层，偏直播切片。", accent: "#6fb5ff", badge: "直播感", sampleTop: "这不是普通", sampleBottom: "联名款", sampleFoot: "层级更强" },
  { key: "white_minimal", label: "纯白极简", groupId: "clean", summary: "不抢画面，适合教程和录屏。", accent: "#e8edf7", badge: "极简", sampleTop: "先看这一步", sampleBottom: "设置路径", sampleFoot: "信息更干净" },
  { key: "clean_box", label: "清爽信息框", groupId: "clean", summary: "字幕更整洁，适合工具说明。", accent: "#bde7ff", badge: "说明", sampleTop: "这里建议", sampleBottom: "先校对配置", sampleFoot: "阅读负担更低" },
  { key: "lime_box", label: "荧绿框", groupId: "clean", summary: "亮色框体，适合科技内容。", accent: "#bbf247", badge: "科技", sampleTop: "这一步会", sampleBottom: "直接提速", sampleFoot: "工具感更强" },
  { key: "mint_outline", label: "薄荷描边", groupId: "clean", summary: "更清爽的数码感字幕。", accent: "#75f0cf", badge: "清爽", sampleTop: "先把目录", sampleBottom: "扫一遍", sampleFoot: "适合操作演示" },
  { key: "cobalt_pop", label: "钴蓝跳色", groupId: "clean", summary: "冷色科技风，适合教程和测评。", accent: "#5b84ff", badge: "蓝调", sampleTop: "重点其实在", sampleBottom: "结构调整", sampleFoot: "理性、稳" },
  { key: "sale_banner", label: "活动横条", groupId: "campaign", summary: "像活动字幕条，利益点更醒目。", accent: "#ff7058", badge: "活动", sampleTop: "今天这波", sampleBottom: "确实值", sampleFoot: "适合促销提醒" },
  { key: "coupon_green", label: "优惠绿标", groupId: "campaign", summary: "适合价格、赠品和优惠信息。", accent: "#84d96b", badge: "优惠", sampleTop: "赠品和套装", sampleBottom: "别漏看", sampleFoot: "转化导向" },
  { key: "amber_news", label: "琥珀新闻", groupId: "documentary", summary: "像信息播报字幕，适合说明和复盘。", accent: "#f2ab48", badge: "播报", sampleTop: "这次改动里", sampleBottom: "最关键的是", sampleFoot: "说明感更强" },
  { key: "soft_shadow", label: "柔影白字", groupId: "documentary", summary: "柔和阴影，适合长口播。", accent: "#e5ded0", badge: "柔和", sampleTop: "如果只看一处", sampleBottom: "看这里", sampleFoot: "耐看不抢戏" },
  { key: "slate_caption", label: "石板灰", groupId: "documentary", summary: "稳重克制，适合复盘和观点。", accent: "#c1cad8", badge: "稳重", sampleTop: "真正的问题不是", sampleBottom: "好不好看", sampleFoot: "更像专题片" },
  { key: "doc_gray", label: "纪实灰白", groupId: "documentary", summary: "纪录式冷静表达。", accent: "#c7ced8", badge: "纪实", sampleTop: "我们先看", sampleBottom: "实际变化", sampleFoot: "可信、弱打扰" },
  { key: "archive_type", label: "档案字机", groupId: "documentary", summary: "档案感和资料感更强。", accent: "#d4c7b0", badge: "档案", sampleTop: "回到这个版本", sampleBottom: "再比较一次", sampleFoot: "适合复盘回溯" },
  { key: "cinema_blue", label: "蓝灰电影感", groupId: "premium", summary: "冷调电影感，适合审美向内容。", accent: "#7ca4ff", badge: "电影感", sampleTop: "这套配色", sampleBottom: "很高级", sampleFoot: "审美向更稳" },
  { key: "midnight_magenta", label: "午夜洋红", groupId: "premium", summary: "夜色霓虹感，更有气质。", accent: "#e85aa8", badge: "夜感", sampleTop: "它最迷人的", sampleBottom: "不是参数", sampleFoot: "适合氛围向" },
  { key: "rose_gold", label: "玫瑰金", groupId: "premium", summary: "轻奢感，适合收藏和限定。", accent: "#f0b9a9", badge: "轻奢", sampleTop: "这一版看起来", sampleBottom: "更贵了", sampleFoot: "偏精品调性" },
  { key: "ivory_serif", label: "象牙衬线", groupId: "premium", summary: "更像杂志正文，适合生活方式内容。", accent: "#eadcc2", badge: "杂志感", sampleTop: "设计语言", sampleBottom: "终于统一了", sampleFoot: "更有编辑感" },
  { key: "luxury_caps", label: "奢感大写", groupId: "premium", summary: "品牌感更重，适合高客单视觉。", accent: "#f0d091", badge: "品牌", sampleTop: "限定收藏", sampleBottom: "这次真到位", sampleFoot: "高端感更强" },
  { key: "film_subtle", label: "胶片低调", groupId: "premium", summary: "存在感低，更偏情绪表达。", accent: "#c6b7a5", badge: "胶片", sampleTop: "真正吸引人的", sampleBottom: "是质感", sampleFoot: "适合细腻镜头" },
  { key: "neon_green_glow", label: "荧绿霓虹", groupId: "campaign", summary: "适合高能科技和夜感画面。", accent: "#59f4b0", badge: "霓虹", sampleTop: "这次联名", sampleBottom: "够炸", sampleFoot: "更偏潮流表达" },
  { key: "teaser_glow", label: "预告辉光", groupId: "campaign", summary: "像预告片字幕，适合悬念导向。", accent: "#8de7ff", badge: "预告", sampleTop: "真正的大招", sampleBottom: "还在后面", sampleFoot: "悬念感更强" },
];

export const subtitleMotionPresets: StylePreset[] = [
  { key: "motion_static", label: "静态基准", groupId: "timing", summary: "不做额外动效，适合说明型内容。", accent: "#f5f7fb", badge: "静态", sampleTop: "不做花里胡哨", sampleBottom: "更稳重", sampleFoot: "默认阅读节奏" },
  { key: "motion_typewriter", label: "逐字打字", groupId: "word", summary: "按顺序点亮字符，适合强信息输出。", accent: "#f8c94b", badge: "打字", sampleTop: "每个词都", sampleBottom: "有节奏出现", sampleFoot: "适合硬核口播" },
  { key: "motion_pop", label: "弹跳出现", groupId: "scene", summary: "主语先大后稳，爆点更抓眼。", accent: "#5bd5ff", badge: "弹跳", sampleTop: "这一句先", sampleBottom: "跳进来", sampleFoot: "适合短视频钩子" },
  { key: "motion_wave", label: "波形起伏", groupId: "word", summary: "字形像波浪起伏，信息层次更强。", accent: "#9eff9e", badge: "波形", sampleTop: "节奏起起", sampleBottom: "落落", sampleFoot: "适合评论/观点" },
  { key: "motion_slide", label: "滑入滑出", groupId: "timing", summary: "下方入场上浮消失，适合转场联动。", accent: "#ff84ff", badge: "滑入", sampleTop: "上一秒先", sampleBottom: "后退位，后上", sampleFoot: "适合动态镜头" },
  { key: "motion_glitch", label: "故障闪烁", groupId: "scene", summary: "轻微抖动与色偏，突出爆点。", accent: "#ff6f6f", badge: "故障", sampleTop: "别轻信", sampleBottom: "太平静", sampleFoot: "适合电竞/硬核内容" },
  { key: "motion_ripple", label: "破浪扩散", groupId: "timing", summary: "首词抬头后逐渐回弹，字幕有扩散扩张感。", accent: "#8de8ff", badge: "扩散", sampleTop: "这一下", sampleBottom: "先冲", sampleFoot: "适合观点反转" },
  { key: "motion_strobe", label: "断续闪耀", groupId: "word", summary: "强烈闪烁后回稳，适合制造突刺刺激。", accent: "#fbe45f", badge: "闪耀", sampleTop: "别眨眼", sampleBottom: "马上后悔", sampleFoot: "适合强烈提醒" },
  { key: "motion_echo", label: "重影回响", groupId: "scene", summary: "核心词有明显残影，读段更有记忆点。", accent: "#ff8de3", badge: "重影", sampleTop: "这件事", sampleBottom: "你别错过", sampleFoot: "适合复盘型结论" },
];

export const smartEffectPresets: StylePreset[] = [
  { key: "smart_effect_commercial", label: "商业高能", groupId: "impact", summary: "强化爆点、卖点和结论镜头，转场、字幕和 punch 更像成熟商业短视频。", accent: "#ff8b63", badge: "默认", sampleTop: "卖点要炸出来", sampleBottom: "镜头更有击中感", sampleFoot: "适合作为新默认风格" },
  { key: "smart_effect_punch", label: "爆点冲击", groupId: "impact", summary: "缩放、闪白、重击字幕和强转场更明显，适合开箱、对比和强观点。", accent: "#ff6d57", badge: "高能", sampleTop: "重点来了", sampleBottom: "镜头更炸", sampleFoot: "适合强结论内容" },
  { key: "smart_effect_glitch", label: "故障赛博", groupId: "cyber", summary: "RGB 偏移、故障切换和数字感字幕更明显，适合科技、机能和潮流题材。", accent: "#7d89ff", badge: "赛博", sampleTop: "故障切换", sampleBottom: "记忆点更强", sampleFoot: "适合数码和潮流" },
  { key: "smart_effect_cinematic", label: "电影推进", groupId: "atmosphere", summary: "更偏镜头推进、明暗层次和情绪铺垫，不靠高频抖动。", accent: "#f2b56b", badge: "电影", sampleTop: "情绪先铺开", sampleBottom: "再推到重点", sampleFoot: "适合预告和叙事" },
  { key: "smart_effect_atmosphere", label: "氛围塑形", groupId: "atmosphere", summary: "强调光感、呼吸感和局部氛围变化，适合质感向和生活方式内容。", accent: "#f1c58b", badge: "氛围", sampleTop: "不是炸点", sampleBottom: "是氛围上来", sampleFoot: "适合高级感内容" },
  { key: "smart_effect_minimal", label: "克制轻特效", groupId: "restrained", summary: "保留必要转场和提示，但整体更干净，不抢主体。", accent: "#b6c3d9", badge: "克制", sampleTop: "少一点动效", sampleBottom: "更干净", sampleFoot: "适合说明和教程" },
];

export const coverStylePresets: StylePreset[] = [
  { key: "preset_default", label: "平台策略联动", groupId: "adaptive", summary: "跟随平台策略自动切换封面包装方向。", accent: "#f0b56c", badge: "自动", sampleTop: "精彩帧优先", sampleBottom: "策略选包装", sampleFoot: "默认推荐" },
  { key: "tech_showcase", label: "科技展示", groupId: "product", summary: "主体居中，强调结构和参数感。", accent: "#75c9ff", badge: "展示", sampleTop: "硬核细节", sampleBottom: "一眼看懂", sampleFoot: "适合数码开箱" },
  { key: "collection_drop", label: "限定收藏", groupId: "brand", summary: "更像收藏海报和限定发布。", accent: "#f2c07c", badge: "收藏", sampleTop: "联名收藏", sampleBottom: "质感拉满", sampleFoot: "适合限定版" },
  { key: "upgrade_spotlight", label: "升级聚焦", groupId: "product", summary: "突出升级点和对比关系。", accent: "#ffa25e", badge: "升级", sampleTop: "这次升级", sampleBottom: "到底值不值", sampleFoot: "适合改版内容" },
  { key: "tactical_neon", label: "战术霓虹", groupId: "cyber", summary: "冷光霓虹和硬核装备感。", accent: "#53d4ff", badge: "战术", sampleTop: "硬核装备", sampleBottom: "夜感更强", sampleFoot: "适合 EDC" },
  { key: "luxury_blackgold", label: "黑金奢感", groupId: "brand", summary: "高客单、精品、礼盒感更强。", accent: "#f2c35b", badge: "黑金", sampleTop: "高级限定", sampleBottom: "一眼就贵", sampleFoot: "品牌视觉更强" },
  { key: "retro_poster", label: "复古海报", groupId: "cinema", summary: "偏复古海报和收藏印刷感。", accent: "#ff9177", badge: "复古", sampleTop: "旧海报感", sampleBottom: "很抓眼", sampleFoot: "情绪更浓" },
  { key: "creator_vlog", label: "创作者 vlog", groupId: "content", summary: "生活化、有人味，适合日常记录。", accent: "#ffb7a0", badge: "vlog", sampleTop: "今天这一套", sampleBottom: "太会了", sampleFoot: "生活感更强" },
  { key: "bold_review", label: "重磅测评", groupId: "content", summary: "像测评视频封面，信息更直接。", accent: "#ff5e66", badge: "测评", sampleTop: "到底强不强", sampleBottom: "直接说结论", sampleFoot: "适合 review" },
  { key: "tutorial_card", label: "教程信息卡", groupId: "content", summary: "更像教程卡片和操作说明封面。", accent: "#7ea7ff", badge: "教程", sampleTop: "三步看懂", sampleBottom: "配置方法", sampleFoot: "适合知识流" },
  { key: "food_magazine", label: "杂志生活感", groupId: "content", summary: "更柔和的编辑质感。", accent: "#f2ae9e", badge: "杂志", sampleTop: "生活方式", sampleBottom: "氛围更足", sampleFoot: "适合轻内容" },
  { key: "street_hype", label: "街头潮流", groupId: "cyber", summary: "潮流、速度和夸张反差更强。", accent: "#ff6c7c", badge: "潮流", sampleTop: "这套真的", sampleBottom: "很炸", sampleFoot: "爆款感更足" },
  { key: "minimal_white", label: "极简白牌", groupId: "brand", summary: "极简留白，更像品牌视觉。", accent: "#f1f3f5", badge: "极简", sampleTop: "少即是多", sampleBottom: "干净到位", sampleFoot: "适合精品展示" },
  { key: "cyber_grid", label: "赛博网格", groupId: "cyber", summary: "带电路和网格氛围的科技感。", accent: "#5fd8ff", badge: "网格", sampleTop: "未来感", sampleBottom: "拉满", sampleFoot: "适合科技内容" },
  { key: "premium_silver", label: "银感质感", groupId: "brand", summary: "比黑金更冷，适合金属和收藏。", accent: "#d6dde8", badge: "银感", sampleTop: "冷调高级", sampleBottom: "更克制", sampleFoot: "适合精品硬件" },
  { key: "comic_pop", label: "漫画爆点", groupId: "cyber", summary: "冲击力强，像短视频爆款封面。", accent: "#ff5ed4", badge: "漫画", sampleTop: "这也太夸张", sampleBottom: "了吧", sampleFoot: "CTR 导向" },
  { key: "studio_red", label: "演播室红", groupId: "content", summary: "像资讯类和演播室封面。", accent: "#ff6358", badge: "演播室", sampleTop: "这期重点", sampleBottom: "先看这个", sampleFoot: "信息导向更强" },
  { key: "documentary_frame", label: "纪录边框", groupId: "content", summary: "带纪实感边框和专题感。", accent: "#d6c8a2", badge: "纪录", sampleTop: "这不是炫技", sampleBottom: "是整理", sampleFoot: "专题感更稳" },
  { key: "pastel_lifestyle", label: "柔和彩度", groupId: "content", summary: "柔和、生活方式、轻情绪。", accent: "#f4b9d8", badge: "柔和", sampleTop: "好看也实用", sampleBottom: "是这种感觉", sampleFoot: "适合生活方式" },
  { key: "industrial_orange", label: "工业橙", groupId: "cyber", summary: "警示和工业工具感更强。", accent: "#ff9348", badge: "工业", sampleTop: "工具属性", sampleBottom: "更明显", sampleFoot: "适合机械感内容" },
  { key: "ecommerce_sale", label: "电商促销", groupId: "commerce", summary: "价格和活动信息位更强。", accent: "#ff6c52", badge: "卖货", sampleTop: "活动力度", sampleBottom: "直接打满", sampleFoot: "转化优先" },
  { key: "price_strike", label: "价格重击", groupId: "commerce", summary: "更像电商主图和强利益点封面。", accent: "#ff5548", badge: "价格", sampleTop: "值不值买", sampleBottom: "一眼给结论", sampleFoot: "适合卖货打法" },
  { key: "trailer_dark", label: "暗调预告", groupId: "cinema", summary: "预告片式暗场和悬念。", accent: "#7a86ff", badge: "预告", sampleTop: "真正的大招", sampleBottom: "刚开始", sampleFoot: "情绪感更强" },
  { key: "festival_redgold", label: "节庆红金", groupId: "commerce", summary: "节点活动、礼盒和节庆导向。", accent: "#f6b94d", badge: "节庆", sampleTop: "限定节点", sampleBottom: "别错过", sampleFoot: "促销节日向" },
  { key: "clean_lab", label: "实验室白蓝", groupId: "product", summary: "更像实验室或工作流演示。", accent: "#9ad7ff", badge: "实验室", sampleTop: "结构拆开看", sampleBottom: "最清楚", sampleFoot: "适合教程和测评" },
  { key: "cinema_teaser", label: "电影预热", groupId: "cinema", summary: "带预告片和片名海报气质。", accent: "#b78dff", badge: "片名", sampleTop: "这次升级", sampleBottom: "有点狠", sampleFoot: "适合情绪引导" },
];

export const titleStylePresets: StylePreset[] = [
  { key: "preset_default", label: "跟随策略自动联动", groupId: "adaptive", summary: "默认按小红书 / B站 / YouTube / CTR / 品牌策略自动切模板。", accent: "#f0b56c", badge: "自动", sampleTop: "平台策略", sampleBottom: "自动切换", sampleFoot: "推荐默认" },
  { key: "cyber_logo_stack", label: "未来 logo 叠层", groupId: "impact", summary: "适合 logo 感标题和霓虹描边。", accent: "#55d7ff", badge: "霓虹", sampleTop: "品牌主标题", sampleBottom: "未来感爆字", sampleFoot: "类似科技潮流封面" },
  { key: "chrome_impact", label: "镀铬冲击", groupId: "impact", summary: "更像 YouTube 开箱大字。", accent: "#dce7ff", badge: "镀铬", sampleTop: "版本升级", sampleBottom: "直接拉满", sampleFoot: "国际化开箱感" },
  { key: "festival_badge", label: "节庆徽章", groupId: "banner", summary: "适合活动、限定、节点主题。", accent: "#f5bf54", badge: "徽章", sampleTop: "马年限定版", sampleBottom: "一眼就到位", sampleFoot: "适合节庆和礼盒" },
  { key: "double_banner", label: "双横幅爆字", groupId: "banner", summary: "上下一组横幅，最像剪映热门封面字效。", accent: "#ff6f6f", badge: "横幅", sampleTop: "城六崩卫版", sampleBottom: "定制化全面升级", sampleFoot: "层级最强" },
  { key: "comic_boom", label: "漫画爆炸字", groupId: "impact", summary: "强对比、强描边、强冲击。", accent: "#ff55cb", badge: "漫画", sampleTop: "这波升级", sampleBottom: "太夸张了", sampleFoot: "CTR 导向" },
  { key: "luxury_gold", label: "奢感金字", groupId: "premium", summary: "适合精品、收藏、礼盒和品牌向内容。", accent: "#f0cb7c", badge: "奢感", sampleTop: "收藏限定", sampleBottom: "气质拉满", sampleFoot: "高级感更强" },
  { key: "tutorial_blueprint", label: "教程蓝图", groupId: "editorial", summary: "信息层级清晰，适合 B 站和教程风格。", accent: "#78b8ff", badge: "蓝图", sampleTop: "版本区别", sampleBottom: "一次看懂", sampleFoot: "知识流更合适" },
  { key: "magazine_clean", label: "杂志清排", groupId: "premium", summary: "标题更克制，像编辑式封面。", accent: "#f1d9bb", badge: "杂志", sampleTop: "不是堆料", sampleBottom: "是设计统一", sampleFoot: "适合审美向" },
  { key: "documentary_stamp", label: "纪录印章", groupId: "editorial", summary: "像专题片标题和档案印章。", accent: "#d8ccb4", badge: "纪录", sampleTop: "这次改版", sampleBottom: "真正变了什么", sampleFoot: "专题感更强" },
  { key: "neon_night", label: "夜霓虹", groupId: "impact", summary: "夜感、潮流和发光字效。", accent: "#8f7cff", badge: "夜感", sampleTop: "夜场质感", sampleBottom: "直接拉满", sampleFoot: "适合赛博和潮流画面" },
];

export const copyStylePresets: StylePreset[] = [
  { key: "attention_grabbing", label: "吸引眼球", groupId: "growth", summary: "默认推荐。爆点、反差、结果感更强。", accent: "#ff7a59", badge: "默认", sampleTop: "这功能强得离谱", sampleBottom: "点击欲最强", sampleFoot: "适合大多数短视频" },
  { key: "balanced", label: "平衡稳妥", groupId: "balanced", summary: "有吸引力但不过火，适合泛用内容。", accent: "#7fb6ff", badge: "稳", sampleTop: "核心流程讲清了", sampleBottom: "信息和情绪都在线", sampleFoot: "泛用性最好" },
  { key: "premium_editorial", label: "高级编辑感", groupId: "brand", summary: "像编辑和品牌文案，更克制、更有质感。", accent: "#f0c77d", badge: "编辑", sampleTop: "这次很值得看", sampleBottom: "更像杂志导语", sampleFoot: "适合品牌和精品" },
  { key: "trusted_expert", label: "专业可信", groupId: "persona", summary: "像经验分享和专家拆解，强调判断和方法。", accent: "#86d6c3", badge: "专业", sampleTop: "关键差异讲明白", sampleBottom: "更像可靠建议", sampleFoot: "适合教程和评测" },
  { key: "playful_meme", label: "轻松玩梗", groupId: "persona", summary: "更网感、更口语、更有梗。", accent: "#d777ff", badge: "玩梗", sampleTop: "这波真的杀疯了", sampleBottom: "更像会玩的账号", sampleFoot: "适合年轻化内容" },
  { key: "emotional_story", label: "情绪叙事", groupId: "persona", summary: "强调等待、惊喜、失望、情绪弧线。", accent: "#ff9cb4", badge: "情绪", sampleTop: "这次真的等太久了", sampleBottom: "更像个人故事", sampleFoot: "适合经历型表达" },
];

export function findStylePreset(presets: StylePreset[], key: string): StylePreset | undefined {
  const normalizedKey = legacyStyleAliases[key] ?? key;
  return presets.find((preset) => preset.key === normalizedKey);
}

export function styleLabel(presets: StylePreset[], key: string): string {
  return findStylePreset(presets, key)?.label ?? key;
}
