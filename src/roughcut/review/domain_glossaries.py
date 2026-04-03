from __future__ import annotations

from collections import OrderedDict
from typing import Any
import re

from roughcut.edit.presets import normalize_workflow_template_name


GlossaryTermLike = dict[str, Any]


_FLASHLIGHT_DOMESTIC_BRANDS: tuple[GlossaryTermLike, ...] = (
    {"correct_form": "FENIX", "wrong_forms": ["菲尼克斯", "飞尼克斯", "Fenix"], "category": "flashlight_brand", "context_hint": "国产手电品牌"},
    {"correct_form": "NITECORE", "wrong_forms": ["奈特科尔", "奈特核心", "Nitecore", "NITE CORE"], "category": "flashlight_brand", "context_hint": "国产手电品牌"},
    {"correct_form": "NEXTORCH", "wrong_forms": ["纳丽德", "Nextorch", "NEXT TORCH"], "category": "flashlight_brand", "context_hint": "国产手电品牌"},
    {"correct_form": "ACEBEAM", "wrong_forms": ["Acebeam", "ACE BEAM"], "category": "flashlight_brand", "context_hint": "国产手电品牌"},
    {"correct_form": "LOOPGEAR", "wrong_forms": ["Loop Gear", "LOOP GEAR", "Loopgear", "Loop露普", "露普"], "category": "flashlight_brand", "context_hint": "国产手电品牌"},
    {"correct_form": "SUPFIRE", "wrong_forms": ["神火", "Supfire", "SUP FIRE"], "category": "flashlight_brand", "context_hint": "国产手电品牌"},
    {"correct_form": "JETBEAM", "wrong_forms": ["Jetbeam", "JET BEAM", "捷特明"], "category": "flashlight_brand", "context_hint": "国产手电品牌"},
    {"correct_form": "KLARUS", "wrong_forms": ["凯瑞兹", "Klarus", "K L A R U S"], "category": "flashlight_brand", "context_hint": "主流手电品牌"},
    {"correct_form": "WUBEN", "wrong_forms": ["务本", "Wuben", "W U B E N"], "category": "flashlight_brand", "context_hint": "主流手电品牌"},
)

_TOOL_DOMESTIC_BRANDS: tuple[GlossaryTermLike, ...] = (
    {"correct_form": "NexTool", "wrong_forms": ["纳拓", "纳特", "Nextool", "NEXT TOOL", "next tool"], "category": "tool_brand", "context_hint": "国产工具钳品牌"},
    {"correct_form": "NEXTORCH", "wrong_forms": ["纳丽德", "Nextorch", "NEXT TORCH"], "category": "tool_brand", "context_hint": "国产工具/照明品牌"},
    {"correct_form": "SATA", "wrong_forms": ["世达", "SATA世达"], "category": "tool_brand", "context_hint": "国产常见工具品牌"},
    {"correct_form": "LAOA", "wrong_forms": ["老A", "老a", "L A O A"], "category": "tool_brand", "context_hint": "国产常见工具品牌"},
    {"correct_form": "WORKPRO", "wrong_forms": ["万克宝", "Workpro", "WORK PRO"], "category": "tool_brand", "context_hint": "国产常见工具品牌"},
    {"correct_form": "SOG", "wrong_forms": ["S O G", "索格"], "category": "tool_brand", "context_hint": "多功能工具钳品牌"},
    {"correct_form": "WARNA", "wrong_forms": ["华尔纳", "WARNA华尔纳", "W A R N A"], "category": "tool_brand", "context_hint": "多功能工具钳品牌"},
    {"correct_form": "SQT顺全作", "wrong_forms": ["顺全", "顺全作", "SQT", "S Q T"], "category": "tool_brand", "context_hint": "多功能工具钳品牌"},
    {"correct_form": "GERBER", "wrong_forms": ["Gerber", "戈博", "G E R B E R"], "category": "tool_brand", "context_hint": "主流多功能工具品牌"},
)

_KNIFE_DOMESTIC_BRANDS: tuple[GlossaryTermLike, ...] = (
    {"correct_form": "NOC", "wrong_forms": ["N O C"], "category": "knife_brand", "context_hint": "国产折刀品牌"},
    {"correct_form": "RUIKE", "wrong_forms": ["锐克", "Ruike"], "category": "knife_brand", "context_hint": "国产折刀品牌"},
    {"correct_form": "SANRENMU", "wrong_forms": ["三刃木", "Sanrenmu"], "category": "knife_brand", "context_hint": "国产折刀品牌"},
    {"correct_form": "KIZER", "wrong_forms": ["凯泽", "Kizer"], "category": "knife_brand", "context_hint": "国产折刀品牌"},
    {"correct_form": "WE Knife", "wrong_forms": ["WE KNIFE", "We Knife", "WEKnife", "威刀"], "category": "knife_brand", "context_hint": "国产折刀品牌"},
    {"correct_form": "CIVIVI", "wrong_forms": ["Civivi", "西维维"], "category": "knife_brand", "context_hint": "国产折刀品牌"},
    {"correct_form": "BESTECH", "wrong_forms": ["Bestech", "贝斯特"], "category": "knife_brand", "context_hint": "国产折刀品牌"},
    {"correct_form": "KUBEY", "wrong_forms": ["Kubey", "库贝"], "category": "knife_brand", "context_hint": "国产折刀品牌"},
    {"correct_form": "REAL STEEL", "wrong_forms": ["RealSteel", "Real Steel", "锐钢"], "category": "knife_brand", "context_hint": "国产折刀品牌"},
    {"correct_form": "CJRB", "wrong_forms": ["C J R B", "Cjrb"], "category": "knife_brand", "context_hint": "国产折刀品牌"},
    {"correct_form": "ARTISAN CUTLERY", "wrong_forms": ["Artisan Cutlery", "Artisan", "阿提森"], "category": "knife_brand", "context_hint": "国产折刀品牌"},
    {"correct_form": "MAXACE", "wrong_forms": ["Maxace", "迈凯斯", "M A X A C E"], "category": "knife_brand", "context_hint": "主流折刀品牌"},
    {"correct_form": "MUNDUS", "wrong_forms": ["Mundus", "世界Mundus", "世界 mundus"], "category": "knife_brand", "context_hint": "主流折刀品牌"},
    {"correct_form": "MICROTECH", "wrong_forms": ["Microtech", "微技术", "M I C R O T E C H"], "category": "knife_brand", "context_hint": "主流折刀品牌"},
)

_BAG_DOMESTIC_BRANDS: tuple[GlossaryTermLike, ...] = (
    {"correct_form": "tomtoc", "wrong_forms": ["Tomtoc", "TOMTOC"], "category": "bag_brand", "context_hint": "国产 EDC 机能包品牌"},
    {"correct_form": "PGYTECH", "wrong_forms": ["Pgytech", "PGY TECH"], "category": "bag_brand", "context_hint": "国产 EDC 机能包品牌"},
    {"correct_form": "NIID", "wrong_forms": ["Niid", "尼德"], "category": "bag_brand", "context_hint": "国产 EDC 机能包品牌"},
    {"correct_form": "COMBACK", "wrong_forms": ["Comback", "COM BACK", "康贝克"], "category": "bag_brand", "context_hint": "国产机能风品牌"},
    {"correct_form": "MADEN", "wrong_forms": ["Maden", "马登"], "category": "bag_brand", "context_hint": "国产机能风品牌"},
    {"correct_form": "LEVEL8", "wrong_forms": ["Level8", "LEVEL 8", "地平线8号"], "category": "bag_brand", "context_hint": "国产通勤包品牌"},
    {"correct_form": "狐蝠工业", "wrong_forms": ["FOXBAT", "Foxbat", "FOXBAT DYNAMICS", "狐蝠", "鸿福"], "category": "bag_brand", "context_hint": "主流机能包品牌", "domain": "bag", "category_scope": "bag", "transcription_seed_templates": ["unboxing_standard", "edc_tactical"]},
    {"correct_form": "头狼工业", "wrong_forms": ["头狼", "头狼工业风", "FIRST WOLF"], "category": "bag_brand", "context_hint": "主流机能包品牌"},
    {"correct_form": "HSJUN", "wrong_forms": ["hesijun", "HESIJUN", "hsjun", "HS JUN", "赫斯郡", "赫斯俊"], "category": "bag_brand", "context_hint": "小众机能包品牌", "domain": "bag", "category_scope": "bag", "transcription_seed_templates": ["unboxing_standard", "edc_tactical"]},
    {"correct_form": "BOLTBOAT", "wrong_forms": ["Boltboat", "BOLT BOAT", "船家"], "category": "bag_brand", "context_hint": "主流机能包品牌", "domain": "bag", "category_scope": "bag", "transcription_seed_templates": ["unboxing_standard", "edc_tactical"]},
    {"correct_form": "PSIGEAR", "wrong_forms": ["PSI GEAR", "PsiGear", "psiger", "混沌装备", "CHAOS GEAR", "Chaos Gear"], "category": "bag_brand", "context_hint": "主流战术/机能包品牌"},
    {"correct_form": "LIIGEAR", "wrong_forms": ["LiiGear", "LII GEAR", "Lii Gear"], "category": "bag_brand", "context_hint": "主流机能包品牌"},
)

_TOOLS_TERMS: tuple[GlossaryTermLike, ...] = (
    *_TOOL_DOMESTIC_BRANDS,
    {"correct_form": "工具钳", "wrong_forms": ["工具前", "工具钱"], "category": "tools", "context_hint": "多功能工具主体"},
    {"correct_form": "多功能工具钳", "wrong_forms": ["多功能工具前"], "category": "tools", "context_hint": "多功能工具主体"},
    {"correct_form": "钳头", "wrong_forms": ["前头"], "category": "tools", "context_hint": "工具钳结构"},
    {"correct_form": "批头", "wrong_forms": ["披头"], "category": "tools", "context_hint": "工具配件"},
    {"correct_form": "螺丝刀", "wrong_forms": ["罗丝刀", "螺四刀"], "category": "tools", "context_hint": "常见工具"},
    {"correct_form": "扳手", "wrong_forms": ["板手"], "category": "tools", "context_hint": "常见工具"},
    {"correct_form": "尖嘴钳", "wrong_forms": ["尖嘴前"], "category": "tools", "context_hint": "常见工具"},
    {"correct_form": "钢丝钳", "wrong_forms": ["钢丝前"], "category": "tools", "context_hint": "常见工具"},
)


_DOMAIN_TERM_LIBRARY: dict[str, tuple[GlossaryTermLike, ...]] = {
    "gear": (
        {"correct_form": "EDC", "wrong_forms": ["一滴西", "诶滴西", "E D C"], "category": "term", "context_hint": "Everyday Carry"},
        {"correct_form": "FAS", "wrong_forms": ["法斯", "发斯", "F A S"], "category": "term", "context_hint": "圈内缩写"},
        {"correct_form": "NOC", "wrong_forms": ["N O C"], "category": "edc_brand", "context_hint": "EDC 品牌"},
        {"correct_form": "REATE", "wrong_forms": ["锐特", "瑞特", "睿特"], "category": "edc_brand", "context_hint": "EDC 品牌"},
        {"correct_form": "LEATHERMAN", "wrong_forms": ["莱泽曼", "来泽曼", "来着曼", "来泽慢", "来自慢", "雷泽曼"], "category": "edc_brand", "context_hint": "EDC 品牌"},
        {"correct_form": "OLIGHT", "wrong_forms": ["傲雷", "奥雷", "O LIGHT"], "category": "edc_brand", "context_hint": "EDC 品牌"},
        {"correct_form": "ZIPPO", "wrong_forms": ["芝宝", "Z I P P O"], "category": "edc_brand", "context_hint": "EDC 品牌"},
        *_FLASHLIGHT_DOMESTIC_BRANDS,
        *_TOOL_DOMESTIC_BRANDS,
        *_KNIFE_DOMESTIC_BRANDS,
        *_BAG_DOMESTIC_BRANDS,
        {"correct_form": "顶配", "wrong_forms": [], "category": "gear", "context_hint": "配置层级"},
        {"correct_form": "次顶配", "wrong_forms": [], "category": "gear", "context_hint": "配置层级"},
        {"correct_form": "标配", "wrong_forms": [], "category": "gear", "context_hint": "配置层级"},
        {"correct_form": "高配", "wrong_forms": [], "category": "gear", "context_hint": "配置层级"},
        {"correct_form": "低配", "wrong_forms": [], "category": "gear", "context_hint": "配置层级"},
        {"correct_form": "钢马", "wrong_forms": [], "category": "gear", "context_hint": "EDC圈内简称"},
        {"correct_form": "锆马", "wrong_forms": [], "category": "gear", "context_hint": "EDC圈内简称"},
        {"correct_form": "钛马", "wrong_forms": [], "category": "gear", "context_hint": "EDC圈内简称"},
        {"correct_form": "铜马", "wrong_forms": [], "category": "gear", "context_hint": "EDC圈内简称"},
        {"correct_form": "大马", "wrong_forms": [], "category": "gear", "context_hint": "EDC圈内简称"},
        {"correct_form": "大马士革", "wrong_forms": [], "category": "gear", "context_hint": "钢材/纹理表达"},
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
        {"correct_form": "镜面", "wrong_forms": ["静面", "净面"], "category": "visual", "context_hint": "表面质感"},
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
        {"correct_form": "K鞘", "wrong_forms": ["K线"], "category": "gear", "context_hint": "户外军品 EDC 常用配件"},
        {"correct_form": "尾绳孔", "wrong_forms": ["背针孔"], "category": "flashlight", "context_hint": "手电结构"},
        {"correct_form": "绳孔", "wrong_forms": ["针孔"], "category": "flashlight", "context_hint": "手电结构"},
        {"correct_form": "四百号", "wrong_forms": ["四百行"], "category": "gear", "context_hint": "砂纸规格/口播"},
        {"correct_form": "胶塞儿", "wrong_forms": ["胶丝"], "category": "flashlight", "context_hint": "手电配件口语"},
        {"correct_form": "即EDC", "wrong_forms": ["即ed"], "category": "term", "context_hint": "圈内缩写"},
        {"correct_form": "手电评测", "wrong_forms": ["手机评测"], "category": "flashlight", "context_hint": "手电内容"},
        {"correct_form": "非常好", "wrong_forms": ["黑金好"], "category": "phrase", "context_hint": "口播表达"},
        {"correct_form": "金光闪闪", "wrong_forms": ["提高山山"], "category": "phrase", "context_hint": "质感表达"},
        {"correct_form": "揣兜儿里", "wrong_forms": ["开袋儿"], "category": "phrase", "context_hint": "北京口语"},
        {"correct_form": "如假包换", "wrong_forms": ["有假包换", "如假包坏"], "category": "phrase", "context_hint": "固定表达"},
        {"correct_form": "微弧版", "wrong_forms": ["V湖眼版", "V湖版", "V湖的"], "category": "flashlight", "context_hint": "手电版本称呼"},
        {"correct_form": "微弧氧化版", "wrong_forms": ["微弧氧化板"], "category": "flashlight", "context_hint": "手电版本称呼"},
    ),
    "edc": (
        {"correct_form": "NOC", "wrong_forms": ["N O C"], "category": "edc_brand", "context_hint": "EDC 品牌"},
        {"correct_form": "REATE", "wrong_forms": ["锐特", "瑞特", "睿特"], "category": "edc_brand", "context_hint": "EDC 品牌"},
        {"correct_form": "LEATHERMAN", "wrong_forms": ["莱泽曼", "来泽曼", "来着曼", "来泽慢", "来自慢", "雷泽曼"], "category": "edc_brand", "context_hint": "EDC 品牌"},
        {"correct_form": "OLIGHT", "wrong_forms": ["傲雷", "奥雷", "O LIGHT"], "category": "edc_brand", "context_hint": "EDC 品牌"},
        {"correct_form": "ZIPPO", "wrong_forms": ["芝宝", "Z I P P O"], "category": "edc_brand", "context_hint": "EDC 品牌"},
        *_FLASHLIGHT_DOMESTIC_BRANDS,
        *_TOOL_DOMESTIC_BRANDS,
        *_KNIFE_DOMESTIC_BRANDS,
        *_BAG_DOMESTIC_BRANDS,
        {"correct_form": "顶配", "wrong_forms": [], "category": "gear", "context_hint": "配置层级"},
        {"correct_form": "次顶配", "wrong_forms": [], "category": "gear", "context_hint": "配置层级"},
        {"correct_form": "标配", "wrong_forms": [], "category": "gear", "context_hint": "配置层级"},
        {"correct_form": "高配", "wrong_forms": [], "category": "gear", "context_hint": "配置层级"},
        {"correct_form": "低配", "wrong_forms": [], "category": "gear", "context_hint": "配置层级"},
        {"correct_form": "钢马", "wrong_forms": [], "category": "gear", "context_hint": "EDC圈内简称"},
        {"correct_form": "锆马", "wrong_forms": [], "category": "gear", "context_hint": "EDC圈内简称"},
        {"correct_form": "钛马", "wrong_forms": [], "category": "gear", "context_hint": "EDC圈内简称"},
        {"correct_form": "铜马", "wrong_forms": [], "category": "gear", "context_hint": "EDC圈内简称"},
        {"correct_form": "大马", "wrong_forms": [], "category": "gear", "context_hint": "EDC圈内简称"},
        {"correct_form": "大马士革", "wrong_forms": [], "category": "gear", "context_hint": "钢材/纹理表达"},
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
        {"correct_form": "镜面", "wrong_forms": ["静面", "净面"], "category": "visual", "context_hint": "表面质感"},
        {"correct_form": "雾面", "wrong_forms": ["屋面"], "category": "visual", "context_hint": "表面质感"},
        {"correct_form": "K鞘", "wrong_forms": ["K线"], "category": "gear", "context_hint": "户外军品 EDC 常用配件"},
        {"correct_form": "尾绳孔", "wrong_forms": ["背针孔"], "category": "flashlight", "context_hint": "手电结构"},
        {"correct_form": "绳孔", "wrong_forms": ["针孔"], "category": "flashlight", "context_hint": "手电结构"},
        {"correct_form": "四百号", "wrong_forms": ["四百行"], "category": "gear", "context_hint": "砂纸规格/口播"},
        {"correct_form": "胶塞儿", "wrong_forms": ["胶丝"], "category": "flashlight", "context_hint": "手电配件口语"},
        {"correct_form": "即EDC", "wrong_forms": ["即ed"], "category": "term", "context_hint": "圈内缩写"},
        {"correct_form": "手电评测", "wrong_forms": ["手机评测"], "category": "flashlight", "context_hint": "手电内容"},
        {"correct_form": "非常好", "wrong_forms": ["黑金好"], "category": "phrase", "context_hint": "口播表达"},
        {"correct_form": "金光闪闪", "wrong_forms": ["提高山山"], "category": "phrase", "context_hint": "质感表达"},
        {"correct_form": "揣兜儿里", "wrong_forms": ["开袋儿"], "category": "phrase", "context_hint": "北京口语"},
        {"correct_form": "如假包换", "wrong_forms": ["有假包换", "如假包坏"], "category": "phrase", "context_hint": "固定表达"},
        {"correct_form": "微弧版", "wrong_forms": ["V湖眼版", "V湖版", "V湖的"], "category": "flashlight", "context_hint": "手电版本称呼"},
        {"correct_form": "微弧氧化版", "wrong_forms": ["微弧氧化板"], "category": "flashlight", "context_hint": "手电版本称呼"},
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
    "coding": (
        {"correct_form": "编程", "wrong_forms": ["边程"], "category": "coding", "context_hint": "软件开发"},
        {"correct_form": "代码", "wrong_forms": ["带码"], "category": "coding", "context_hint": "软件开发"},
        {"correct_form": "函数", "wrong_forms": ["分数"], "category": "coding", "context_hint": "编程概念"},
        {"correct_form": "接口", "wrong_forms": ["借口"], "category": "coding", "context_hint": "编程概念"},
        {"correct_form": "仓库", "wrong_forms": ["仓苦"], "category": "coding", "context_hint": "Git 仓库"},
        {"correct_form": "提交", "wrong_forms": ["题交"], "category": "coding", "context_hint": "代码提交"},
        {"correct_form": "分支", "wrong_forms": ["分之"], "category": "coding", "context_hint": "Git 分支"},
        {"correct_form": "调试", "wrong_forms": ["调事"], "category": "coding", "context_hint": "开发流程"},
        {"correct_form": "报错", "wrong_forms": ["爆错"], "category": "coding", "context_hint": "开发流程"},
        {"correct_form": "部署", "wrong_forms": ["布署"], "category": "coding", "context_hint": "开发流程"},
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
    "knife": (
        *_KNIFE_DOMESTIC_BRANDS,
        {"correct_form": "折刀", "wrong_forms": ["折到"], "category": "knife", "context_hint": "刀具品类"},
        {"correct_form": "主刀", "wrong_forms": ["主到", "主导"], "category": "knife", "context_hint": "刀具结构"},
        {"correct_form": "副刀", "wrong_forms": ["辅刀"], "category": "knife", "context_hint": "刀具结构"},
        {"correct_form": "锁定", "wrong_forms": ["所定"], "category": "knife", "context_hint": "刀具结构"},
        {"correct_form": "开合", "wrong_forms": ["开和", "开盒"], "category": "knife", "context_hint": "刀具动作"},
        {"correct_form": "背夹", "wrong_forms": ["背甲"], "category": "knife", "context_hint": "刀具配件"},
    ),
    "flashlight": (
        *_FLASHLIGHT_DOMESTIC_BRANDS,
        {"correct_form": "NexTool", "wrong_forms": ["纳拓", "纳特", "Nextool", "NEXT TOOL"], "category": "tool_brand", "context_hint": "国产 EDC 工具品牌"},
        {"correct_form": "手电", "wrong_forms": ["手店"], "category": "flashlight", "context_hint": "照明品类"},
        {"correct_form": "手电评测", "wrong_forms": ["手机评测"], "category": "flashlight", "context_hint": "手电内容"},
        {"correct_form": "筒身", "wrong_forms": ["桶身"], "category": "flashlight", "context_hint": "手电结构"},
        {"correct_form": "灯珠", "wrong_forms": ["灯株"], "category": "flashlight", "context_hint": "照明术语"},
        {"correct_form": "色温", "wrong_forms": ["色文"], "category": "flashlight", "context_hint": "照明术语"},
        {"correct_form": "泛光", "wrong_forms": ["反光"], "category": "flashlight", "context_hint": "照明术语"},
        {"correct_form": "聚光", "wrong_forms": ["具光"], "category": "flashlight", "context_hint": "照明术语"},
        {"correct_form": "尾绳孔", "wrong_forms": ["背针孔"], "category": "flashlight", "context_hint": "手电结构"},
        {"correct_form": "绳孔", "wrong_forms": ["针孔"], "category": "flashlight", "context_hint": "手电结构"},
        {"correct_form": "胶塞儿", "wrong_forms": ["胶丝"], "category": "flashlight", "context_hint": "手电配件口语"},
        {"correct_form": "微弧版", "wrong_forms": ["V湖眼版", "V湖版", "V湖的"], "category": "flashlight", "context_hint": "手电版本称呼"},
        {"correct_form": "微弧氧化版", "wrong_forms": ["微弧氧化板"], "category": "flashlight", "context_hint": "手电版本称呼"},
    ),
    "bag": (
        *_BAG_DOMESTIC_BRANDS,
        {"correct_form": "FXX1小副包", "wrong_forms": ["F叉二一小副包", "F X X 1小副包"], "category": "bag_model", "context_hint": "狐蝠工业机能副包型号"},
        {"correct_form": "FXX1", "wrong_forms": ["F叉二一", "F X X 1"], "category": "bag_model", "context_hint": "狐蝠工业机能副包型号"},
        {"correct_form": "游刃", "wrong_forms": [], "category": "bag_model", "context_hint": "机能包产品名", "domain": "bag", "category_scope": "bag", "transcription_seed_templates": ["unboxing_standard", "edc_tactical"]},
        {"correct_form": "阵风", "wrong_forms": ["震风", "阵峰"], "category": "bag_model", "context_hint": "机能双肩包产品名", "domain": "bag", "category_scope": "bag", "transcription_seed_templates": ["unboxing_standard", "edc_tactical"]},
        {"correct_form": "机能包", "wrong_forms": ["机能包儿"], "category": "bag", "context_hint": "EDC 包袋品类"},
        {"correct_form": "双肩包", "wrong_forms": ["双肩抱"], "category": "bag", "context_hint": "EDC 包袋品类"},
        {"correct_form": "通勤包", "wrong_forms": ["通情包"], "category": "bag", "context_hint": "EDC 包袋品类"},
        {"correct_form": "斜挎包", "wrong_forms": ["斜胯包"], "category": "bag", "context_hint": "EDC 包袋品类"},
        {"correct_form": "胸包", "wrong_forms": [], "category": "bag", "context_hint": "EDC 包袋品类"},
        {"correct_form": "快取包", "wrong_forms": [], "category": "bag", "context_hint": "EDC 包袋品类"},
        {"correct_form": "收纳包", "wrong_forms": ["收那包"], "category": "bag", "context_hint": "EDC 包袋品类"},
    ),
    "lighter": (
        {"correct_form": "打火机", "wrong_forms": ["打火鸡"], "category": "lighter", "context_hint": "点火品类"},
        {"correct_form": "火轮", "wrong_forms": ["货轮"], "category": "lighter", "context_hint": "打火机结构"},
        {"correct_form": "内胆", "wrong_forms": ["内单"], "category": "lighter", "context_hint": "打火机结构"},
        {"correct_form": "煤油", "wrong_forms": ["没油"], "category": "lighter", "context_hint": "打火机燃料"},
    ),
    "tactical": (
        {"correct_form": "战术", "wrong_forms": ["站术"], "category": "tactical", "context_hint": "战术风格"},
        {"correct_form": "胸挂", "wrong_forms": ["胸卦"], "category": "tactical", "context_hint": "战术挂载"},
        {"correct_form": "模组", "wrong_forms": ["模块"], "category": "tactical", "context_hint": "战术扩展"},
        {"correct_form": "快拆", "wrong_forms": ["快差"], "category": "tactical", "context_hint": "战术结构"},
        {"correct_form": "尼龙", "wrong_forms": ["泥龙"], "category": "tactical", "context_hint": "战术材质"},
    ),
    "outdoor": (
        {"correct_form": "户外", "wrong_forms": ["户外儿"], "category": "outdoor", "context_hint": "户外领域"},
        {"correct_form": "露营", "wrong_forms": ["路营"], "category": "outdoor", "context_hint": "户外活动"},
        {"correct_form": "徒步", "wrong_forms": ["图步"], "category": "outdoor", "context_hint": "户外活动"},
        {"correct_form": "营地", "wrong_forms": ["迎地"], "category": "outdoor", "context_hint": "户外场景"},
        {"correct_form": "炉头", "wrong_forms": ["驴头"], "category": "outdoor", "context_hint": "户外装备"},
        {"correct_form": "天幕", "wrong_forms": ["天木"], "category": "outdoor", "context_hint": "户外装备"},
    ),
    "functional_wear": (
        {"correct_form": "机能", "wrong_forms": ["肌能"], "category": "wear", "context_hint": "机能风格"},
        {"correct_form": "机能装备", "wrong_forms": ["机能装被"], "category": "wear", "context_hint": "机能穿搭"},
        {"correct_form": "战术裤", "wrong_forms": ["站术裤"], "category": "wear", "context_hint": "机能穿搭"},
        {"correct_form": "通勤包", "wrong_forms": ["通情包"], "category": "wear", "context_hint": "装备穿搭"},
    ),
    "tools": _TOOLS_TERMS,
}

_WORKFLOW_TEMPLATE_DOMAINS: dict[str, tuple[str, ...]] = {
    "edc_tactical": ("gear", "knife", "tactical", "outdoor", "flashlight", "bag", "lighter", "functional_wear", "toy"),
    "tutorial_standard": ("tech", "ai", "coding"),
    "vlog_daily": ("travel",),
    "commentary_focus": ("tech", "ai", "coding"),
    "gameplay_highlight": ("tech",),
    "food_explore": ("food",),
    "unboxing_standard": ("gear", "tech", "bag"),
    "news_briefing": ("news", "finance"),
    "market_watch": ("finance", "news"),
    "sports_highlight": ("sports",),
}

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "gear": (
        "EDC", "FAS", "折刀", "刀", "钛", "柄材", "钢材", "背夹", "工具钳", "彩雕", "深雕",
        "NOC", "REATE", "LEATHERMAN", "OLIGHT", "ZIPPO", "FENIX", "NITECORE", "NEXTORCH", "ACEBEAM", "LOOPGEAR", "SUPFIRE", "JETBEAM", "KLARUS", "WUBEN",
        "NexTool", "SATA", "LAOA", "WORKPRO", "SOG", "WARNA", "SQT顺全作", "GERBER",
        "RUIKE", "SANRENMU", "KIZER", "WE Knife", "CIVIVI", "BESTECH", "KUBEY", "REAL STEEL", "CJRB", "ARTISAN CUTLERY", "MAXACE", "MUNDUS", "MICROTECH",
        "tomtoc", "PGYTECH", "NIID", "COMBACK", "MADEN", "LEVEL8", "狐蝠工业", "头狼工业", "BOLTBOAT", "PSIGEAR", "LIIGEAR",
        "顶配", "次顶配", "标配", "高配", "低配", "钢马", "锆马", "钛马", "铜马", "大马", "大马士革",
        "镜面", "雾面", "潮玩", "盲盒", "隐藏款", "官图", "原型", "涂装", "素体", "关节", "可动", "盒损", "手办",
        "户外", "战术", "露营", "徒步", "营地", "快挂", "鞘套", "战术笔", "K鞘", "四百号", "即EDC", "如假包换",
    ),
    "edc": ("EDC", "FAS", "NOC", "REATE", "LEATHERMAN", "OLIGHT", "ZIPPO", "FENIX", "NITECORE", "NEXTORCH", "ACEBEAM", "LOOPGEAR", "SUPFIRE", "JETBEAM", "KLARUS", "WUBEN", "NexTool", "SATA", "LAOA", "WORKPRO", "SOG", "WARNA", "SQT顺全作", "GERBER", "RUIKE", "SANRENMU", "KIZER", "WE Knife", "CIVIVI", "BESTECH", "KUBEY", "REAL STEEL", "CJRB", "ARTISAN CUTLERY", "MAXACE", "MUNDUS", "MICROTECH", "tomtoc", "PGYTECH", "NIID", "COMBACK", "MADEN", "LEVEL8", "狐蝠工业", "头狼工业", "BOLTBOAT", "PSIGEAR", "LIIGEAR", "折刀", "刀", "钛", "柄材", "钢材", "背夹", "工具钳", "彩雕", "深雕", "顶配", "次顶配", "标配", "高配", "低配", "钢马", "锆马", "钛马", "铜马", "大马", "大马士革", "镜面", "雾面", "K鞘", "四百号", "即EDC"),
    "tech": ("芯片", "显卡", "处理器", "续航", "屏幕", "相机", "手机", "笔记本", "耳机", "快充", "固件"),
    "ai": ("AI", "提示词", "工作流", "模型", "微调", "推理", "多模态", "智能体", "RAG", "LoRA", "Agent", "MCP", "Checkpoint", "ControlNet", "Flux", "RunningHub", "ComfyUI", "OpenClaw", "无限画布", "节点编排"),
    "coding": ("编程", "代码", "函数", "接口", "仓库", "提交", "分支", "调试", "报错", "部署", "脚本", "API"),
    "tools": ("工具钳", "多功能工具钳", "钳头", "批头", "螺丝刀", "扳手", "尖嘴钳", "钢丝钳", "NexTool", "SATA", "LAOA", "WORKPRO", "SOG", "WARNA", "SQT顺全作", "GERBER"),
    "travel": ("旅行", "出行", "机票", "酒店", "民宿", "值机", "citywalk", "攻略", "景点", "登机"),
    "food": ("探店", "试吃", "口感", "锅气", "回甘", "拉花", "挂耳", "熟成", "奶茶", "火锅", "甜品", "烧烤"),
    "finance": ("财经", "金融", "利率", "汇率", "通胀", "降息", "加息", "美联储", "纳斯达克", "标普", "财报", "市盈率"),
    "news": ("国际新闻", "外媒", "局势", "停火", "制裁", "峰会", "外交", "联合国", "北约", "欧盟", "总统", "总理"),
    "sports": ("体育", "赛事", "比分", "加时", "绝杀", "点球", "越位", "三分", "篮板", "助攻", "季后赛", "世界杯"),
    "toy": ("潮玩", "盲盒", "隐藏款", "官图", "原型", "涂装", "素体", "关节", "可动", "盒损", "手办"),
    "knife": ("折刀", "主刀", "副刀", "锁定", "开合", "背夹", "刃型", "柄材", "钢材", "轴锁", "线锁", "NOC", "RUIKE", "SANRENMU", "KIZER", "WE Knife", "CIVIVI", "BESTECH", "KUBEY", "REAL STEEL", "CJRB", "ARTISAN CUTLERY", "MAXACE", "MUNDUS", "MICROTECH"),
    "flashlight": ("手电", "手电评测", "灯珠", "色温", "泛光", "聚光", "流明", "筒身", "尾按", "尾绳孔", "绳孔", "胶塞儿", "微弧版", "微弧氧化版", "UV", "FENIX", "NITECORE", "NEXTORCH", "ACEBEAM", "LOOPGEAR", "SUPFIRE", "JETBEAM", "KLARUS", "WUBEN", "NexTool"),
    "bag": ("机能包", "双肩包", "通勤包", "斜挎包", "胸包", "快取包", "收纳包", "小副包", "阵风", "游刃", "FXX1", "FXX1小副包", "tomtoc", "PGYTECH", "NIID", "COMBACK", "MADEN", "LEVEL8", "狐蝠工业", "头狼工业", "BOLTBOAT", "PSIGEAR", "LIIGEAR"),
    "lighter": ("打火机", "内胆", "火轮", "煤油", "直冲", "火焰"),
    "tactical": ("战术", "胸挂", "快拆", "模组", "尼龙", "挂载"),
    "outdoor": ("户外", "露营", "徒步", "营地", "炉头", "天幕", "野营"),
    "functional_wear": ("机能", "机能装备", "战术裤", "双肩包", "通勤包", "工装", "穿搭", "机能包", "斜挎包", "胸包", "阵风", "游刃", "tomtoc", "PGYTECH", "NIID", "COMBACK", "MADEN", "LEVEL8", "狐蝠工业", "头狼工业", "BOLTBOAT", "PSIGEAR", "LIIGEAR"),
}

_DOMAIN_COMPATIBILITY: dict[str, tuple[str, ...]] = {
    "gear": ("edc", "knife", "flashlight", "bag", "lighter", "tactical", "outdoor", "functional_wear", "toy"),
    "edc": ("gear", "knife", "flashlight", "bag", "lighter", "tactical", "outdoor", "functional_wear", "toy"),
    "knife": ("gear", "edc", "tactical", "outdoor"),
    "flashlight": ("gear", "edc", "outdoor", "tactical"),
    "bag": ("gear", "edc", "functional_wear", "outdoor", "tactical"),
    "lighter": ("gear", "edc", "outdoor"),
    "tactical": ("gear", "edc", "knife", "bag", "outdoor", "functional_wear"),
    "outdoor": ("gear", "edc", "flashlight", "bag", "lighter", "tactical", "functional_wear"),
    "functional_wear": ("gear", "edc", "bag", "tactical", "outdoor"),
    "toy": ("gear", "edc"),
    "tools": ("edc", "outdoor"),
    "functional": ("bag", "functional_wear"),
    "tech": (),
    "ai": ("coding",),
    "coding": ("ai",),
    "finance": ("news",),
    "news": ("finance",),
}

_CANONICAL_DOMAIN_ALIASES: dict[str, str] = {
    "digital": "tech",
    "software": "ai",
    "coding": "ai",
    "gear": "edc",
    "knife": "edc",
    "flashlight": "edc",
    "lighter": "edc",
    "toy": "edc",
    "bag": "functional",
    "functional_wear": "functional",
    "tool": "tools",
}

_CANONICAL_DOMAIN_SOURCES: dict[str, tuple[str, ...]] = {
    "edc": ("edc", "gear", "knife", "flashlight", "lighter", "toy"),
    "outdoor": ("outdoor", "tactical"),
    "tech": ("tech",),
    "ai": ("ai", "coding"),
    "functional": ("bag", "functional_wear"),
    "tools": ("tools",),
    "travel": ("travel",),
    "food": ("food",),
    "finance": ("finance",),
    "news": ("news",),
    "sports": ("sports",),
}

_VISIBLE_DOMAIN_PACKS: tuple[str, ...] = (
    "edc",
    "outdoor",
    "tech",
    "ai",
    "functional",
    "tools",
    "travel",
    "food",
    "finance",
    "news",
    "sports",
)


def _detect_glossary_signal_domains(
    *,
    workflow_template: str | None,
    content_profile: dict[str, Any] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
    source_name: str | None = None,
    include_workflow_template: bool,
) -> list[str]:
    domains: list[str] = []
    normalized_workflow_template = normalize_workflow_template_name(workflow_template)
    if include_workflow_template:
        for domain in _WORKFLOW_TEMPLATE_DOMAINS.get(normalized_workflow_template, ()):
            if domain not in domains:
                domains.append(domain)

    declared_domain = normalize_subject_domain((content_profile or {}).get("subject_domain"))
    if declared_domain and declared_domain not in domains:
        domains.append(declared_domain)

    haystacks: list[str] = []
    if source_name:
        haystacks.append(str(source_name))
    for key in ("subject_brand", "subject_model", "subject_type", "video_theme", "summary", "hook_line"):
        haystacks.append(str((content_profile or {}).get(key) or ""))
    for item in subtitle_items or []:
        haystacks.append(str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or ""))
    joined = " ".join(haystacks).upper()
    scores: dict[str, int] = {}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.upper() in joined:
                score += 1 if len(keyword) <= 2 else 2
        if score > 0:
            scores[domain] = score

    for domain, score in sorted(scores.items(), key=lambda item: (-item[1], item[0])):
        threshold = 1 if domain in {"gear", "edc"} else 2
        if score >= threshold and domain not in domains:
            domains.append(domain)
    return domains


def normalize_subject_domain(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    return _CANONICAL_DOMAIN_ALIASES.get(normalized, normalized)


def canonicalize_domains(domains: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for domain in domains or []:
        canonical = normalize_subject_domain(domain)
        if canonical and canonical not in seen:
            seen.add(canonical)
            ordered.append(canonical)
    if "functional" in seen:
        ordered = [domain for domain in ordered if domain != "edc"]
        seen.discard("edc")
    if "tools" in seen:
        ordered = [domain for domain in ordered if domain != "edc"]
        seen.discard("edc")
    return ordered


def select_primary_subject_domain(domains: list[str] | tuple[str, ...] | set[str] | None) -> str | None:
    scores: dict[str, int] = {}
    for domain in domains or []:
        normalized = str(domain or "").strip().lower()
        canonical = normalize_subject_domain(normalized)
        if not canonical:
            continue
        weight = 1
        if normalized in {"bag", "functional_wear"}:
            weight = 4
        elif normalized in {"tools", "tool"}:
            weight = 4
        elif normalized in {"ai", "coding", "software"}:
            weight = 4
        elif normalized in {"tech", "digital"}:
            weight = 4
        elif normalized in {"outdoor", "tactical"}:
            weight = 3
        elif normalized in {"knife", "flashlight", "lighter", "toy", "edc"}:
            weight = 3
        elif normalized == "gear":
            weight = 1
        scores[canonical] = scores.get(canonical, 0) + weight

    if not scores:
        canonical = canonicalize_domains(domains)
        return canonical[0] if canonical else None

    priority = {
        "functional": 6,
        "tools": 5,
        "ai": 4,
        "tech": 3,
        "edc": 3,
        "outdoor": 2,
        "food": 1,
        "travel": 1,
        "finance": 1,
        "news": 1,
        "sports": 1,
    }
    ranked = sorted(scores.items(), key=lambda item: (-item[1], -priority.get(item[0], 0), item[0]))
    return ranked[0][0]


def resolve_builtin_glossary_terms(
    *,
    workflow_template: str | None,
    content_profile: dict[str, Any] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
    source_name: str | None = None,
) -> list[GlossaryTermLike]:
    normalized_workflow_template = normalize_workflow_template_name(workflow_template)
    domains = _detect_glossary_signal_domains(
        workflow_template=workflow_template,
        content_profile=content_profile,
        subtitle_items=subtitle_items,
        source_name=source_name,
        include_workflow_template=False,
    )
    merged: list[GlossaryTermLike] = []
    for domain in _expand_compatible_domains(domains):
        for term in _DOMAIN_TERM_LIBRARY.get(domain, ()):
            merged.append({**term, "domain": domain})
    if normalized_workflow_template:
        for domain, terms in _DOMAIN_TERM_LIBRARY.items():
            for term in terms:
                templates = {
                    normalize_workflow_template_name(item) or str(item or "").strip()
                    for item in (term.get("transcription_seed_templates") or [])
                    if str(item or "").strip()
                }
                if normalized_workflow_template in templates:
                    merged.append({**term, "domain": domain})
    return merge_glossary_terms([], merged)


def filter_scoped_glossary_terms(
    terms: list[GlossaryTermLike] | None,
    *,
    workflow_template: str | None,
    content_profile: dict[str, Any] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
    source_name: str | None = None,
) -> list[GlossaryTermLike]:
    raw_detected_domains = detect_glossary_domains(
        workflow_template=workflow_template,
        content_profile=content_profile,
        subtitle_items=subtitle_items,
        source_name=source_name,
    )
    detected_domains = set(raw_detected_domains)
    detected_domains.update(canonicalize_domains(raw_detected_domains))
    filtered: list[GlossaryTermLike] = []
    for term in terms or []:
        scope_type = str(term.get("scope_type") or "global").strip() or "global"
        scope_value = str(term.get("scope_value") or "").strip()
        if scope_type == "global":
            filtered.append(term)
            continue
        if scope_type == "domain" and (
            scope_value in detected_domains
            or (normalize_subject_domain(scope_value) or "") in detected_domains
        ):
            filtered.append(term)
            continue
    return filtered


def merge_glossary_terms(
    base_terms: list[GlossaryTermLike] | None,
    extra_terms: list[GlossaryTermLike] | None,
) -> list[GlossaryTermLike]:
    passthrough_keys = (
        "category",
        "context_hint",
        "domain",
        "category_scope",
        "transcription_seed_templates",
        "scope_type",
        "scope_value",
    )
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
            for key in passthrough_keys:
                value = raw.get(key)
                if value and not current.get(key):
                    current[key] = value
            merged[correct_form] = current
    return list(merged.values())


def detect_glossary_domains(
    *,
    workflow_template: str | None,
    content_profile: dict[str, Any] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
    source_name: str | None = None,
) -> list[str]:
    return canonicalize_domains(
        _detect_glossary_signal_domains(
            workflow_template=workflow_template,
            content_profile=content_profile,
            subtitle_items=subtitle_items,
            source_name=source_name,
            include_workflow_template=False,
        )
    )


def build_domain_signal_summary(domains: list[str]) -> str:
    ordered = [domain for domain in canonicalize_domains(domains) if domain]
    return ", ".join(ordered)


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(text or "")))


def list_builtin_glossary_packs() -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    for domain in _VISIBLE_DOMAIN_PACKS:
        terms = merge_glossary_terms(
            [],
            [
                term
                for expanded in _expand_compatible_domains([domain])
                for term in _DOMAIN_TERM_LIBRARY.get(expanded, ())
            ],
        )
        presets = sorted(
            preset
            for preset, domains in _WORKFLOW_TEMPLATE_DOMAINS.items()
            if domain in canonicalize_domains(domains)
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


def _expand_compatible_domains(domains: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    queue: list[str] = []
    for domain in domains if domains else []:
        normalized = str(domain or "").strip().lower()
        if not normalized:
            continue
        queue.extend(_CANONICAL_DOMAIN_SOURCES.get(normalize_subject_domain(normalized) or normalized, (normalized,)))
    while queue:
        domain = queue.pop(0)
        if domain in seen:
            continue
        seen.add(domain)
        ordered.append(domain)
        for related in _DOMAIN_COMPATIBILITY.get(domain, ()):
            if related not in seen:
                queue.append(related)
    return ordered
