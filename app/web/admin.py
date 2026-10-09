from __future__ import annotations

import math
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.services import (
    delete_images,
    delete_user_images,
    effective_quota,
    get_image,
    get_user_stats,
    global_stats,
    list_images,
    list_users,
    set_admin,
    set_banned,
    set_user_quota,
    soft_delete_image,
    source_breakdown,
    top_uploaders,
    uploads_per_day,
)
from app.utils import human_size
from app.web.auth import (
    get_admin_username,
    is_custom,
    reset_admin_credentials,
    set_admin_credentials,
    verify_admin,
)

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic(auto_error=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

PAGE_SIZE = 25


def _parse_quota_mb(raw: str) -> int | None:
    """Return quota bytes, or None meaning 'inherit global default'.

    ``0`` means unlimited (stored as 0 bytes). Empty / 'default' -> None.
    """
    raw = (raw or "").strip().lower()
    if raw in ("", "default", "inherit", "-"):
        return None
    value = float(raw)
    if value < 0:
        raise ValueError("negative")
    return int(value * 1024 * 1024)


async def admin_auth(
    credentials: HTTPBasicCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> str:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin authentication required",
        headers={"WWW-Authenticate": "Basic"},
    )
    if credentials is None:
        raise unauthorized
    if not await verify_admin(session, credentials.username, credentials.password):
        raise unauthorized
    return credentials.username


def _page_links(page: int, total: int) -> dict:
    pages = max(1, math.ceil(total / PAGE_SIZE))
    return {"page": page, "pages": pages, "total": total}


def _settings_context(
    request: Request,
    username: str,
    custom: bool,
    *,
    message: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "view": "settings",
            "admin_username": username,
            "custom": custom,
            "message": message,
            "error": error,
        },
    )


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(
    request: Request,
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    stats = await global_stats(session)
    images, _total = await list_images(session, limit=8, include_deleted=False)
    series = await uploads_per_day(session, days=14)
    chart_max = max((p["count"] for p in series), default=0) or 1
    sources = await source_breakdown(session)
    source_total = sum(s["count"] for s in sources) or 1
    palette = ["#4f8cff", "#22d3a6", "#a970ff", "#ffb020", "#ff5c6c", "#63d4ff"]
    cursor = 0.0
    for i, s in enumerate(sources):
        s["pct"] = round(s["count"] * 100 / source_total, 1)
        s["color"] = palette[i % len(palette)]
        s["start"] = round(cursor, 2)
        cursor += s["pct"]
        s["end"] = round(cursor, 2)
    donut = (
        "conic-gradient("
        + ", ".join(f"{s['color']} {s['start']}% {s['end']}%" for s in sources)
        + ")"
        if sources
        else "var(--panel-3)"
    )
    leaders = await top_uploaders(session, limit=5)
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "view": "dashboard",
            "stats": stats,
            "total_size_h": human_size(stats.total_size),
            "images": images,
            "image_base": settings.image_base,
            "format_size": human_size,
            "series": series,
            "chart_max": chart_max,
            "chart_total": sum(p["count"] for p in series),
            "sources": sources,
            "donut": donut,
            "leaders": leaders,
        },
    )


@router.get("/images", response_class=HTMLResponse, include_in_schema=False)
async def images_page(
    request: Request,
    page: int = Query(1, ge=1),
    q: str | None = None,
    owner: int | None = None,
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    offset = (page - 1) * PAGE_SIZE
    images, total = await list_images(
        session,
        limit=PAGE_SIZE,
        offset=offset,
        owner_id=owner,
        include_deleted=True,
        search=q,
    )
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "view": "images",
            "images": images,
            "q": q or "",
            "owner": owner,
            "pager": _page_links(page, total),
            "image_base": settings.image_base,
            "format_size": human_size,
        },
    )


@router.post("/images/{image_id}/delete", include_in_schema=False)
async def delete_image(
    image_id: str,
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    image = await get_image(session, image_id, include_deleted=True)
    if image is not None:
        await soft_delete_image(session, image)
    return RedirectResponse(url="/admin/images", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/images/bulk-delete", include_in_schema=False)
async def bulk_delete_images(
    request: Request,
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    ids = [str(v) for v in form.getlist("image_ids")]
    await delete_images(session, ids)
    return RedirectResponse(url="/admin/images", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/users", response_class=HTMLResponse, include_in_schema=False)
async def users_page(
    request: Request,
    page: int = Query(1, ge=1),
    q: str | None = None,
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    offset = (page - 1) * PAGE_SIZE
    users, total = await list_users(session, limit=PAGE_SIZE, offset=offset, search=q)

    rows = []
    for u in users:
        count, size = await get_user_stats(session, u.id)
        quota = effective_quota(u)
        rows.append(
            {
                "user": u,
                "count": count,
                "size_h": human_size(size),
                "quota_h": human_size(quota) if quota > 0 else "不限",
                "quota_custom": u.quota_bytes is not None,
            }
        )

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "view": "users",
            "rows": rows,
            "q": q or "",
            "pager": _page_links(page, total),
            "super_admin_ids": sorted(settings.admin_id_set),
            "format_size": human_size,
        },
    )


@router.post("/users/{user_id}/ban", include_in_schema=False)
async def ban_user(
    user_id: int,
    unban: int = Query(0),
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    # Never allow banning a super admin (from .env).
    if not unban and user_id in settings.admin_id_set:
        return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)
    await set_banned(session, user_id, not bool(unban))
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/admin", include_in_schema=False)
async def toggle_admin(
    user_id: int,
    remove: int = Query(0),
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    # Super admins (from .env) can never be demoted.
    if remove and user_id in settings.admin_id_set:
        return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)
    await set_admin(session, user_id, not bool(remove))
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/wipe", include_in_schema=False)
async def wipe_user_images(
    user_id: int,
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    await delete_user_images(session, user_id)
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/quota", include_in_schema=False)
async def set_quota(
    user_id: int,
    request: Request,
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    raw = str(form.get("mb", ""))
    try:
        quota = _parse_quota_mb(raw)
    except (ValueError, TypeError):
        return RedirectResponse(
            url="/admin/users?err=quota", status_code=status.HTTP_303_SEE_OTHER
        )
    await set_user_quota(session, user_id, quota)
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/bulk", include_in_schema=False)
async def bulk_users(
    request: Request,
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    action = str(form.get("action", ""))
    raw_ids = form.getlist("user_ids")
    ids: list[int] = []
    for value in raw_ids:
        try:
            ids.append(int(str(value)))
        except ValueError:
            continue

    for uid in ids:
        if action == "ban":
            if uid in settings.admin_id_set:
                continue
            await set_banned(session, uid, True)
        elif action == "unban":
            await set_banned(session, uid, False)
        elif action == "promote":
            await set_admin(session, uid, True)
        elif action == "demote":
            if uid in settings.admin_id_set:
                continue
            await set_admin(session, uid, False)
        elif action == "wipe":
            await delete_user_images(session, uid)
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
async def settings_page(
    request: Request,
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    return _settings_context(
        request,
        await get_admin_username(session),
        await is_custom(session),
    )


@router.post("/settings", response_class=HTMLResponse, include_in_schema=False)
async def update_settings(
    request: Request,
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    password2 = str(form.get("password2", ""))

    if not username:
        return _settings_context(
            request,
            await get_admin_username(session),
            await is_custom(session),
            error="用户名不能为空。",
        )
    if password or password2:
        if password != password2:
            return _settings_context(
                request,
                await get_admin_username(session),
                await is_custom(session),
                error="两次输入的密码不一致。",
            )
        if len(password) < 6:
            return _settings_context(
                request,
                await get_admin_username(session),
                await is_custom(session),
                error="密码至少 6 位。",
            )

    await set_admin_credentials(session, username, password or None)
    return _settings_context(
        request,
        username,
        True,
        message="已保存。若修改了用户名或密码，浏览器下次请求需要重新登录。",
    )


@router.post("/settings/reset", include_in_schema=False)
async def reset_settings(
    _: str = Depends(admin_auth),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    await reset_admin_credentials(session)
    return RedirectResponse(url="/admin/settings", status_code=status.HTTP_303_SEE_OTHER)
