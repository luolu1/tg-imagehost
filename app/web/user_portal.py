from __future__ import annotations

import math
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import User
from app.services import (
    delete_images,
    effective_quota,
    find_user_images,
    get_user_by_token,
    get_user_stats,
    rotate_api_token,
    uploads_per_day,
)
from app.uploads import UploadError, upload_bytes
from app.utils import human_size
from app.web.user_auth import (
    COOKIE_MAX_AGE,
    COOKIE_NAME,
    require_web_user,
    resolve_web_user,
)

router = APIRouter(prefix="/my", tags=["portal"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

PAGE_SIZE = 24


def _serialize(image) -> dict:
    return {
        "id": image.id,
        "url": settings.image_url(image.id, image.ext),
        "page": settings.view_url(image.id),
        "file_name": image.file_name,
        "size": image.file_size,
        "width": image.width,
        "height": image.height,
        "views": image.views,
        "created_at": image.created_at.isoformat(),
    }


def _quota_ctx(user: User, used: int) -> dict:
    quota = effective_quota(user)
    pct = 0.0
    if quota > 0:
        pct = min(100.0, used * 100.0 / quota)
    return {
        "quota_bytes": quota,
        "quota_h": human_size(quota) if quota > 0 else "不限",
        "quota_pct": round(pct, 1),
        "quota_custom": user.quota_bytes is not None,
        "used_bytes": used,
        "used_h": human_size(used),
    }


def _set_login_cookie(resp: RedirectResponse, token: str) -> RedirectResponse:
    resp.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return resp


# ------------------------------------------------------------------ auth


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    if await resolve_web_user(request, session) is not None:
        return RedirectResponse(url="/my", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "my_login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_submit(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()
    token = str(form.get("token", "")).strip()
    if not token:
        return templates.TemplateResponse(
            request, "my_login.html", {"error": "请输入 Token。"}, status_code=400
        )
    user = await get_user_by_token(session, token)
    if user is None:
        return templates.TemplateResponse(
            request, "my_login.html", {"error": "Token 无效。"}, status_code=401
        )
    if user.is_banned:
        return templates.TemplateResponse(
            request, "my_login.html", {"error": "账号已被封禁。"}, status_code=403
        )
    resp = RedirectResponse(url="/my", status_code=status.HTTP_303_SEE_OTHER)
    return _set_login_cookie(resp, token)


@router.get("/logout", include_in_schema=False)
async def logout() -> RedirectResponse:
    resp = RedirectResponse(url="/my/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@router.post("/token/regenerate", include_in_schema=False)
async def regenerate_token(
    user: User = Depends(require_web_user),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    token = await rotate_api_token(session, user)
    resp = RedirectResponse(url="/my", status_code=status.HTTP_303_SEE_OTHER)
    return _set_login_cookie(resp, token)


# ---------------------------------------------------------------- pages


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(
    request: Request,
    user: User = Depends(require_web_user),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    count, size = await get_user_stats(session, user.id)
    recent = await find_user_images(session, user.id, limit=8)
    series = await uploads_per_day(session, days=14, owner_id=user.id)
    chart_max = max((p["count"] for p in series), default=0) or 1
    return templates.TemplateResponse(
        request,
        "my.html",
        {
            "view": "dashboard",
            "me": user,
            "count": count,
            "recent": recent,
            "series": series,
            "chart_max": chart_max,
            "chart_total": sum(p["count"] for p in series),
            "image_base": settings.image_base,
            "format_size": human_size,
            "token": user.api_token or "",
            **_quota_ctx(user, size),
        },
    )


@router.get("/images", response_class=HTMLResponse, include_in_schema=False)
async def images_page(
    request: Request,
    page: int = Query(1, ge=1),
    q: str | None = None,
    user: User = Depends(require_web_user),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    offset = (page - 1) * PAGE_SIZE
    # find_user_images has no search; use list_images on this owner for filtering.
    from app.services import list_images

    images, total = await list_images(
        session,
        limit=PAGE_SIZE,
        offset=offset,
        owner_id=user.id,
        include_deleted=False,
        search=q,
    )
    _, size = await get_user_stats(session, user.id)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    return templates.TemplateResponse(
        request,
        "my.html",
        {
            "view": "images",
            "me": user,
            "images": images,
            "q": q or "",
            "pager": {"page": page, "pages": pages, "total": total},
            "image_base": settings.image_base,
            "format_size": human_size,
            "token": user.api_token or "",
            **_quota_ctx(user, size),
        },
    )


# --------------------------------------------------------------- actions


@router.post("/images/bulk-delete", include_in_schema=False)
async def bulk_delete(
    request: Request,
    user: User = Depends(require_web_user),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    ids = [str(v) for v in form.getlist("image_ids")]
    await delete_images(session, ids, owner_id=user.id)
    return RedirectResponse(url="/my/images", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/images/{image_id}/delete", include_in_schema=False)
async def delete_one(
    image_id: str,
    user: User = Depends(require_web_user),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    await delete_images(session, [image_id], owner_id=user.id)
    return RedirectResponse(url="/my/images", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/upload")
async def portal_upload(
    file: UploadFile = File(...),
    user: User = Depends(require_web_user),
    session: AsyncSession = Depends(get_session),
):
    from app.services import quota_exceeded

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
            source="web",
        )
    except UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return JSONResponse(_serialize(image), status_code=status.HTTP_201_CREATED)
