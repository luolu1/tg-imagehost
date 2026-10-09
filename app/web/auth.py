from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import delete_setting, get_setting, set_setting

USERNAME_KEY = "admin_username"
PASSWORD_KEY = "admin_password_hash"
CUSTOM_KEY = "admin_credentials_custom"  # "1" once changed from the web UI

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS
    )
    return f"{_ALGO}${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$", 3)
        if algo != _ALGO:
            return False
        computed = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(computed.hex(), digest)


async def ensure_admin_seeded(session: AsyncSession) -> None:
    """Seed the credentials store from .env on first run."""
    if await get_setting(session, USERNAME_KEY) is None:
        await set_setting(session, USERNAME_KEY, settings.admin_username)
    if await get_setting(session, PASSWORD_KEY) is None:
        await set_setting(session, PASSWORD_KEY, hash_password(settings.admin_password))


async def get_admin_username(session: AsyncSession) -> str:
    return await get_setting(session, USERNAME_KEY) or settings.admin_username


async def is_custom(session: AsyncSession) -> bool:
    return await get_setting(session, CUSTOM_KEY) == "1"


async def verify_admin(session: AsyncSession, username: str, password: str) -> bool:
    expected = await get_admin_username(session)
    if not hmac.compare_digest(username.encode(), expected.encode()):
        return False
    stored = await get_setting(session, PASSWORD_KEY)
    if stored is None:
        return hmac.compare_digest(password.encode(), settings.admin_password.encode())
    return verify_password(password, stored)


async def set_admin_credentials(
    session: AsyncSession, username: str, password: str | None
) -> None:
    if username:
        await set_setting(session, USERNAME_KEY, username)
    if password:
        await set_setting(session, PASSWORD_KEY, hash_password(password))
    await set_setting(session, CUSTOM_KEY, "1")


async def reset_admin_credentials(session: AsyncSession) -> None:
    await delete_setting(session, USERNAME_KEY)
    await delete_setting(session, PASSWORD_KEY)
    await delete_setting(session, CUSTOM_KEY)
