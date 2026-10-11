from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.services import bump_views, get_image, recent_images
from app.telegram_files import download_to_cache
from app.uploads import UploadError, upload_bytes

log = logging.getLogger(__name__)
router = APIRouter(tags=["pages"])

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Brand mark used as the browser favicon (inline SVG, no external asset needed).
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#818cf8"/>'
    "</linearGradient></defs>"
    '<rect width="64" height="64" rx="14" fill="#06080c"/>'
    '<rect x="10" y="10" width="44" height="44" rx="10" fill="none" '
    'stroke="url(#g)" stroke-width="4"/>'
    '<circle cx="24" cy="24" r="5" fill="url(#g)"/>'
    '<path d="M16 46l12-13 8 8 7-7 7 8v4a2 2 0 0 1-2 2H18a2 2 0 0 1-2-2z" '
    'fill="url(#g)"/></svg>'
)

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


@router.get("/favicon.svg", include_in_schema=False)
async def favicon_svg() -> Response:
    return Response(
        content=FAVICON_SVG,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon_ico() -> Response:
    # Browsers that request .ico get the same SVG mark.
    return Response(
        content=FAVICON_SVG,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/tos", response_class=HTMLResponse, include_in_schema=False)
async def tos_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "tos.html", {})


@router.get("/api-docs", response_class=HTMLResponse, include_in_schema=False)
async def api_docs_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "api_docs.html",
        {
            "api_base": f"{settings.web_base}/api",
            "max_mb": settings.max_upload_mb,
        },
    )


@router.get("/upload", response_class=HTMLResponse, include_in_schema=False)
async def upload_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    recent = await recent_images(session, limit=12)
    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "max_mb": settings.max_upload_mb,
            "web_base": settings.web_base,
            "image_base": settings.image_base,
            "recent": recent,
        },
    )


@router.post("/upload", include_in_schema=False)
async def guest_upload(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Public upload: anyone visiting the site can upload without a token.

    The image is stored with no owner and tagged as a ``guest`` upload.
    """
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"文件过大，上限 {settings.max_upload_mb} MB",
        )
    try:
        image = await upload_bytes(
            session,
            owner_id=None,
            filename=file.filename or "upload",
            mime_type=file.content_type,
            data=data,
            source="guest",
        )
    except UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return JSONResponse(
        {
            "id": image.id,
            "url": settings.image_url(image.id, image.ext),
            "page": settings.view_url(image.id),
            "file_name": image.file_name,
            "size": image.file_size,
        },
        status_code=status.HTTP_201_CREATED,
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
