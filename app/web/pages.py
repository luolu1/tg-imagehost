from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.services import bump_views, get_image
from app.telegram_files import download_to_cache

log = logging.getLogger(__name__)
router = APIRouter(tags=["pages"])

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_EXT_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "svg": "image/svg+xml",
    "ico": "image/x-icon",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "avif": "image/avif",
    "heic": "image/heic",
}


def _extract_id(filename: str) -> str:
    return filename.split(".", 1)[0]


@router.get("/", include_in_schema=False)
async def index() -> RedirectResponse:
    return RedirectResponse(url="/upload")


@router.get("/upload", response_class=HTMLResponse, include_in_schema=False)
async def upload_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "upload.html",
        {"max_mb": settings.max_upload_mb, "web_base": settings.web_base},
    )


@router.get("/v/{filename}", response_class=HTMLResponse, include_in_schema=False)
async def view_page(
    filename: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    image_id = _extract_id(filename)
    image = await get_image(session, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片不存在或已删除")

    direct = settings.image_url(image.id, image.ext)
    page = settings.view_url(image.id)
    return templates.TemplateResponse(
        request,
        "view.html",
        {
            "image": image,
            "direct_url": direct,
            "page_url": page,
            "html_code": f'<img src="{direct}" alt="{image.id}">',
            "md_code": f"![image]({direct})",
            "bb_code": f"[img]{direct}[/img]",
            "web_base": settings.web_base,
        },
    )


@router.get("/i/{filename}", include_in_schema=False)
async def serve_image(
    filename: str,
    download: int = Query(0),
    session: AsyncSession = Depends(get_session),
):
    image_id = _extract_id(filename)
    image = await get_image(session, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片不存在或已删除")

    try:
        path = await download_to_cache(image.file_id, image.id, image.ext)
    except Exception as exc:  # noqa: BLE001
        log.exception("failed to fetch image %s from telegram", image.id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "取图失败") from exc

    await bump_views(session, image)

    media_type = image.mime_type or _EXT_MIME.get(image.ext, "application/octet-stream")
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    if download:
        name = image.file_name or f"{image.id}.{image.ext}"
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return FileResponse(path, media_type=media_type, headers=headers)
