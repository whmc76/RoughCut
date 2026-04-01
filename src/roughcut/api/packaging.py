from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from roughcut.api.schemas import PackagingConfigPatch, PackagingLibraryOut
from roughcut.packaging.library import (
    delete_packaging_asset,
    get_packaging_asset,
    list_packaging_assets,
    reset_packaging_config,
    save_packaging_asset,
    update_packaging_config,
)

router = APIRouter(prefix="/packaging", tags=["packaging"])


@router.get("", response_model=PackagingLibraryOut)
def get_packaging_library():
    return list_packaging_assets()


@router.post("/assets/{asset_type}", response_model=PackagingLibraryOut, status_code=201)
async def upload_packaging_asset(asset_type: str, file: UploadFile = File(...)):
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        save_packaging_asset(
            asset_type=asset_type,
            filename=file.filename or f"{asset_type}.bin",
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return list_packaging_assets()


@router.delete("/assets/{asset_id}", response_model=PackagingLibraryOut)
def remove_packaging_asset(asset_id: str):
    try:
        delete_packaging_asset(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Packaging asset not found") from exc
    return list_packaging_assets()


@router.get("/assets/{asset_id}/file")
def get_packaging_asset_file(asset_id: str):
    try:
        asset = get_packaging_asset(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Packaging asset not found") from exc
    return FileResponse(asset["path"], media_type=asset["content_type"], filename=asset["original_name"])


@router.patch("/config", response_model=PackagingLibraryOut)
def patch_packaging_config(body: PackagingConfigPatch):
    try:
        update_packaging_config(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return list_packaging_assets()


@router.delete("/config", response_model=PackagingLibraryOut)
def delete_packaging_config():
    reset_packaging_config()
    return list_packaging_assets()
