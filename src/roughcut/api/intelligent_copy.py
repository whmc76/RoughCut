from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

from roughcut.api.schemas import (
    IntelligentCopyGenerateIn,
    IntelligentCopyInspectIn,
    IntelligentCopyInspectOut,
    IntelligentCopyResultOut,
    OpenFolderOut,
)
from roughcut.review.intelligent_copy import generate_intelligent_copy, inspect_intelligent_copy_folder

router = APIRouter(prefix="/intelligent-copy", tags=["intelligent-copy"])


@router.post("/inspect", response_model=IntelligentCopyInspectOut)
def inspect_folder(body: IntelligentCopyInspectIn):
    try:
        return inspect_intelligent_copy_folder(body.folder_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generate", response_model=IntelligentCopyResultOut)
async def generate_folder_materials(body: IntelligentCopyGenerateIn):
    try:
        return await generate_intelligent_copy(body.folder_path, copy_style=body.copy_style)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/open-folder", response_model=OpenFolderOut)
def open_folder(body: IntelligentCopyInspectIn):
    target_path = Path(str(body.folder_path or "").strip()).expanduser()
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="目录不存在。")
    try:
        _open_in_file_manager(target_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"打开文件夹失败：{exc}") from exc
    kind = "file" if target_path.is_file() else "folder"
    return OpenFolderOut(path=str(target_path.resolve()), kind=kind)


def _open_in_file_manager(target_path: Path) -> None:
    resolved = target_path.resolve()
    if resolved.is_file():
        subprocess.Popen(["explorer", "/select,", str(resolved)])
        return
    subprocess.Popen(["explorer", str(resolved)])
