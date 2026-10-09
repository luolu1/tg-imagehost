from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.services import get_user_by_token

bearer = HTTPBearer(auto_error=False)


async def current_api_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resolve a user from `Authorization: Bearer <token>` or `X-API-Token`."""
    token: str | None = None
    if credentials is not None:
        token = credentials.credentials
    if not token:
        token = request.headers.get("X-API-Token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少 API Token")

    user = await get_user_by_token(session, token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token 无效")
    if user.is_banned:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被封禁")
    return user
