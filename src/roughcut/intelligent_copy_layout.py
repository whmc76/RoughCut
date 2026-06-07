from pathlib import Path

MATERIAL_DIR_NAME = "smart-copy"
SMART_COPY_META_DIRNAME = "_meta"
SMART_COPY_COPY_DIRNAME = "_copy"
SMART_COPY_COVER_DIRNAME = "_cover"


def smart_copy_meta_dir(material_dir: Path) -> Path:
    return material_dir / SMART_COPY_META_DIRNAME


def smart_copy_copy_dir(material_dir: Path) -> Path:
    return material_dir / SMART_COPY_COPY_DIRNAME


def smart_copy_cover_dir(material_dir: Path) -> Path:
    return material_dir / SMART_COPY_COVER_DIRNAME


def smart_copy_material_root(path: Path) -> Path:
    parent = path.parent if path.suffix else path
    if parent.name in {SMART_COPY_META_DIRNAME, SMART_COPY_COPY_DIRNAME, SMART_COPY_COVER_DIRNAME}:
        return parent.parent
    return parent


def smart_copy_material_json_path(material_dir: Path) -> Path:
    return smart_copy_meta_dir(material_dir) / "smart-copy.json"


def smart_copy_platform_packaging_json_path(material_dir: Path) -> Path:
    return smart_copy_meta_dir(material_dir) / "platform-packaging.json"


def smart_copy_platform_packaging_markdown_path(material_dir: Path) -> Path:
    return smart_copy_meta_dir(material_dir) / "platform-packaging.md"


def resolve_smart_copy_material_json_path(material_dir: Path) -> Path:
    preferred = smart_copy_material_json_path(material_dir)
    legacy = material_dir / "smart-copy.json"
    return preferred if preferred.exists() else legacy


def resolve_smart_copy_platform_packaging_json_path(material_dir: Path) -> Path:
    preferred = smart_copy_platform_packaging_json_path(material_dir)
    legacy = material_dir / "platform-packaging.json"
    return preferred if preferred.exists() else legacy


def resolve_smart_copy_platform_packaging_markdown_path(material_dir: Path) -> Path:
    preferred = smart_copy_platform_packaging_markdown_path(material_dir)
    legacy = material_dir / "platform-packaging.md"
    return preferred if preferred.exists() else legacy


def smart_copy_cover_source_image_path(material_dir: Path) -> Path:
    return smart_copy_cover_dir(material_dir) / "00-highlight-cover-source.jpg"


def smart_copy_cover_source_manifest_path(material_dir: Path) -> Path:
    return smart_copy_cover_dir(material_dir) / "00-highlight-cover-source.json"


def smart_copy_cover_candidates_sheet_path(material_dir: Path) -> Path:
    return smart_copy_cover_dir(material_dir) / "00-highlight-candidates-sheet.jpg"


def smart_copy_cover_reference_image_path(material_dir: Path, index: int) -> Path:
    safe_index = max(1, int(index or 1))
    return smart_copy_cover_dir(material_dir) / f"00-highlight-reference-{safe_index}.jpg"


def resolve_smart_copy_cover_source_image_path(material_dir: Path) -> Path:
    preferred = smart_copy_cover_source_image_path(material_dir)
    legacy = material_dir / "00-highlight-cover-source.jpg"
    return preferred if preferred.exists() else legacy


def resolve_smart_copy_cover_source_manifest_path(material_dir: Path) -> Path:
    preferred = smart_copy_cover_source_manifest_path(material_dir)
    legacy = material_dir / "00-highlight-cover-source.json"
    return preferred if preferred.exists() else legacy


def resolve_smart_copy_cover_candidates_sheet_path(material_dir: Path) -> Path:
    preferred = smart_copy_cover_candidates_sheet_path(material_dir)
    legacy = material_dir / "00-highlight-candidates-sheet.jpg"
    return preferred if preferred.exists() else legacy


def resolve_smart_copy_cover_reference_image_paths(material_dir: Path) -> list[Path]:
    preferred = sorted(smart_copy_cover_dir(material_dir).glob("00-highlight-reference-*.*"))
    if preferred:
        return preferred
    fallback = resolve_smart_copy_cover_source_image_path(material_dir)
    return [fallback] if fallback.exists() else []


def smart_copy_cover_group_output_path(material_dir: Path, group_key: str) -> Path:
    return smart_copy_cover_dir(material_dir) / f"00-cover-{str(group_key or '').strip()}.jpg"


def resolve_smart_copy_cover_group_output_path(material_dir: Path, group_key: str) -> Path:
    preferred = smart_copy_cover_group_output_path(material_dir, group_key)
    legacy = material_dir / f"00-cover-{str(group_key or '').strip()}.jpg"
    return preferred if preferred.exists() else legacy


def smart_copy_cover_group_request_path(material_dir: Path, group_key: str) -> Path:
    return smart_copy_cover_group_output_path(material_dir, group_key).with_suffix(".codex-imagegen.json")


def resolve_smart_copy_cover_group_request_path(material_dir: Path, group_key: str) -> Path:
    preferred = smart_copy_cover_group_request_path(material_dir, group_key)
    legacy = (material_dir / f"00-cover-{str(group_key or '').strip()}.jpg").with_suffix(".codex-imagegen.json")
    return preferred if preferred.exists() else legacy


def smart_copy_cover_group_reference_path(material_dir: Path, group_key: str) -> Path:
    return smart_copy_cover_group_output_path(material_dir, group_key).with_suffix(".codex-imagegen-reference.jpg")


def smart_copy_platform_cover_path(material_dir: Path, index: int, platform_key: str) -> Path:
    return material_dir / f"{index:02d}-{str(platform_key or '').strip()}-cover.jpg"


def smart_copy_platform_markdown_path(material_dir: Path, index: int, platform_key: str) -> Path:
    return material_dir / f"{index:02d}-{str(platform_key or '').strip()}.md"


def smart_copy_platform_titles_path(material_dir: Path, index: int, platform_key: str) -> Path:
    return smart_copy_copy_dir(material_dir) / f"{index:02d}-{str(platform_key or '').strip()}-titles.txt"


def smart_copy_platform_body_path(material_dir: Path, index: int, platform_key: str) -> Path:
    return smart_copy_copy_dir(material_dir) / f"{index:02d}-{str(platform_key or '').strip()}-body.txt"


def smart_copy_platform_tags_path(material_dir: Path, index: int, platform_key: str) -> Path:
    return smart_copy_copy_dir(material_dir) / f"{index:02d}-{str(platform_key or '').strip()}-tags.txt"


def resolve_smart_copy_platform_titles_path(material_dir: Path, index: int, platform_key: str) -> Path:
    preferred = smart_copy_platform_titles_path(material_dir, index, platform_key)
    legacy = material_dir / f"{index:02d}-{str(platform_key or '').strip()}-titles.txt"
    return preferred if preferred.exists() else legacy


def resolve_smart_copy_platform_body_path(material_dir: Path, index: int, platform_key: str) -> Path:
    preferred = smart_copy_platform_body_path(material_dir, index, platform_key)
    legacy = material_dir / f"{index:02d}-{str(platform_key or '').strip()}-body.txt"
    return preferred if preferred.exists() else legacy


def resolve_smart_copy_platform_tags_path(material_dir: Path, index: int, platform_key: str) -> Path:
    preferred = smart_copy_platform_tags_path(material_dir, index, platform_key)
    legacy = material_dir / f"{index:02d}-{str(platform_key or '').strip()}-tags.txt"
    return preferred if preferred.exists() else legacy
