from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.services import get_user_by_token

# The portal cookie simply holds the user's API token. The token is already the
# credential used by the REST API, and the cookie is HttpOnly so scripts can't
# read it. Logging out just clears the cookie.
COOKIE_NAME = "tg_portal_token"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


async def resolve_web_user(request: Request, session: AsyncSession) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    user = await get_user_by_token(session, token)
    if user is None or user.is_banned:
        return None
    return user


def _login_redirect() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": "/my/login"},
    )


async def require_web_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    """Cookie-authenticated user for the portal pages; 303 to login when absent."""
    user = await resolve_web_user(request, session)
    if user is None:
        raise _login_redirect()
    return user
