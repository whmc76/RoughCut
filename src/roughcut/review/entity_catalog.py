from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from roughcut.review.domain_glossaries import normalize_subject_domain


@dataclass(frozen=True)
class EntityCatalogEntry:
    brand: str = ""
    model: str = ""
    subject_type: str = ""
    subject_domain: str = ""
    brand_aliases: tuple[str, ...] = ()
    model_aliases: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    supporting_keywords: tuple[str, ...] = ()
    source_type: str = "builtin_entity_catalog"


_BUILTIN_ENTITY_CATALOG: tuple[EntityCatalogEntry, ...] = (
    EntityCatalogEntry(
        brand="LEATHERMAN",
        model="ARC",
        subject_type="多功能工具钳",
        subject_domain="tools",
        brand_aliases=("莱德曼", "莱泽曼", "来泽曼", "来着曼", "雷泽曼"),
        model_aliases=("ASC", "AC"),
        phrases=("LEATHERMAN ARC", "ARC 多功能工具钳"),
        supporting_keywords=("工具钳", "多功能钳", "单手开合", "钳口", "锉刀", "MagnaCut"),
    ),
    EntityCatalogEntry(
        brand="LuckyKiss",
        model="KissPod",
        subject_type="益生菌含片",
        subject_domain="food",
        brand_aliases=("LUCKYKISS", "Lucky Kiss"),
        model_aliases=("KISSPORT", "Kiss Pod"),
        phrases=("LuckyKiss KissPod", "KissPod 益生菌含片"),
        supporting_keywords=("益生菌", "含片", "弹射", "口气", "零糖", "入口", "情侣"),
    ),
    EntityCatalogEntry(
        brand="狐蝠工业",
        model="FXX1小副包",
        subject_type="机能副包",
        subject_domain="bag",
        brand_aliases=("FOXBAT", "Foxbat", "鸿福", "狐蝠"),
        model_aliases=("FXX1", "F叉二一小副包", "F21小副包", "F X X 1小副包"),
        phrases=("狐蝠工业 FXX1小副包", "FXX1小副包", "FXX1 小副包"),
        supporting_keywords=("副包", "分仓", "挂点", "收纳", "背负", "容量", "机能包"),
    ),
    EntityCatalogEntry(
        brand="狐蝠工业",
        model="阵风",
        subject_type="机能双肩包",
        subject_domain="bag",
        brand_aliases=("FOXBAT", "Foxbat", "鸿福", "狐蝠"),
        model_aliases=("阵峰",),
        phrases=("狐蝠工业 阵风", "阵风双肩包"),
        supporting_keywords=("双肩包", "分仓", "挂点", "背负", "机能包"),
    ),
    EntityCatalogEntry(
        brand="HSJUN",
        model="游刃",
        subject_type="机能双肩包",
        subject_domain="bag",
        brand_aliases=("赫斯俊", "赫斯郡", "hsjun", "HESIJUN"),
        model_aliases=(),
        phrases=("HSJUN 游刃", "游刃双肩包"),
        supporting_keywords=("双肩包", "轻量化", "机能", "通勤", "背负"),
    ),
    EntityCatalogEntry(
        brand="BOLTBOAT",
        model="游刃",
        subject_type="机能双肩包",
        subject_domain="bag",
        brand_aliases=("船长", "船厂", "Boltboat", "BOLT BOAT"),
        model_aliases=(),
        phrases=("BOLTBOAT 游刃", "联名游刃"),
        supporting_keywords=("联名", "双肩包", "轻量化", "机能", "通勤"),
    ),
    EntityCatalogEntry(
        brand="NexTool",
        model="F12",
        subject_type="多功能工具钳",
        subject_domain="tools",
        brand_aliases=("NEXTOOL", "NEXTOOL", "纳拓", "纳特"),
        model_aliases=("F2", "F 2", "F 12"),
        phrases=("NexTool F12", "F12 多功能工具钳", "NexTool F2"),
        supporting_keywords=("工具钳", "钳子", "剪刀", "小刀", "口袋", "EDC"),
    ),
    EntityCatalogEntry(
        brand="NexTool",
        model="S11 PRO",
        subject_type="多功能工具",
        subject_domain="tools",
        brand_aliases=("NEXTOOL", "NEXTOOL", "纳拓", "纳特"),
        model_aliases=("S11PRO", "S11 Pro"),
        phrases=("NexTool S11 PRO", "S11 PRO"),
        supporting_keywords=("工具", "口袋", "EDC", "小工具"),
    ),
    EntityCatalogEntry(
        brand="OLIGHT",
        model="SLIM2代ULTRA版本",
        subject_type="EDC手电",
        subject_domain="flashlight",
        brand_aliases=("傲雷", "奥雷", "O LIGHT"),
        model_aliases=("SLIM2 ULTRA", "SLIM2代 ULTRA", "Slim2 Ultra"),
        phrases=("OLIGHT SLIM2代ULTRA版本", "SLIM2 ULTRA", "Slim2 Ultra"),
        supporting_keywords=("手电", "流明", "续航", "ULTRA", "PRO版", "EDC23", "SK05"),
    ),
    EntityCatalogEntry(
        brand="OLIGHT",
        model="司令官2Ultra",
        subject_type="EDC手电",
        subject_domain="flashlight",
        brand_aliases=("傲雷", "奥雷", "O LIGHT"),
        model_aliases=("司令官2 Ultra", "Commander2Ultra", "Commander 2 Ultra", "Commander 2Ultra"),
        phrases=("OLIGHT 司令官2Ultra", "傲雷司令官2Ultra", "OLIGHT Commander2Ultra", "Commander 2 Ultra"),
        supporting_keywords=("手电", "流明", "续航", "ULTRA", "EDC", "旗舰"),
    ),
    EntityCatalogEntry(
        brand="MICROTECH",
        model="S0",
        subject_type="锆合金版折刀",
        subject_domain="knife",
        brand_aliases=("Microtech", "微技术"),
        model_aliases=("SO",),
        phrases=("MICROTECH S0", "S0 锆合金版折刀"),
        supporting_keywords=("折刀", "锆合金", "快开", "大宝剑", "背夹"),
    ),
)


def list_builtin_entity_catalog(*, subject_domain: str | None = None) -> list[dict[str, Any]]:
    normalized_subject_domain = normalize_subject_domain(subject_domain)
    rows: list[dict[str, Any]] = []
    for entry in _BUILTIN_ENTITY_CATALOG:
        entry_domain = normalize_subject_domain(entry.subject_domain)
        if normalized_subject_domain and entry_domain and entry_domain != normalized_subject_domain:
            continue
        rows.append(asdict(entry))
    return rows
