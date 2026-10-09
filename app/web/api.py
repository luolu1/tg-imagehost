from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import User
from app.services import (
    delete_images,
    effective_quota,
    find_user_images,
    get_image,
    get_user_stats,
    soft_delete_image,
    quota_exceeded,
)
from app.uploads import UploadError, upload_bytes
from app.utils import human_size
from app.web.deps import current_api_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["api"])


def _serialize(image) -> dict:
    return {
        "id": image.id,
        "url": settings.image_url(image.id, image.ext),
        "page": settings.view_url(image.id),
        "file_name": image.file_name,
        "mime_type": image.mime_type,
        "size": image.file_size,
        "width": image.width,
        "height": image.height,
        "views": image.views,
        "created_at": image.created_at.isoformat(),
    }


@router.get("/me")
async def api_me(user: User = Depends(current_api_user), session: AsyncSession = Depends(get_session)):
    count, size = await get_user_stats(session, user.id)
    quota = effective_quota(user)
    return {
        "id": user.id,
        "username": user.username,
        "images": count,
        "used_bytes": size,
        "quota_bytes": quota,
        "quota_custom": user.quota_bytes is not None,
    }


@router.get("/images")
async def api_images(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_api_user),
    session: AsyncSession = Depends(get_session),
):
    images = await find_user_images(session, user.id, limit=limit, offset=offset)
    return {"items": [_serialize(i) for i in images], "limit": limit, "offset": offset}


@router.post("/images/bulk-delete")
async def api_bulk_delete(
    payload: dict,
    user: User = Depends(current_api_user),
    session: AsyncSession = Depends(get_session),
):
    ids = payload.get("ids") or []
    if not isinstance(ids, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ids 必须是数组")
    deleted = await delete_images(session, [str(i) for i in ids], owner_id=None if user.is_admin else user.id)
    return {"ok": True, "deleted": deleted}


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def api_upload(
    file: UploadFile = File(...),
    user: User = Depends(current_api_user),
    session: AsyncSession = Depends(get_session),
):
    data = await file.read()
    if await quota_exceeded(session, user, len(data)):
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"配额已满（{human_size(effective_quota(user))}）",
        )
    try:
        image = await upload_bytes(
            session,
            owner_id=user.id,
            filename=file.filename or "upload",
            mime_type=file.content_type,
            data=data,
            source="api",
        )
    except UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _serialize(image)


@router.delete("/images/{image_id}", status_code=status.HTTP_200_OK)
async def api_delete(
    image_id: str,
    user: User = Depends(current_api_user),
    session: AsyncSession = Depends(get_session),
):
    image = await get_image(session, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片不存在")
    if not (user.is_admin or image.owner_id == user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权限")
    await soft_delete_image(session, image)
    return {"ok": True, "id": image_id}
