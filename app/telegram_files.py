from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile

from app.config import settings

log = logging.getLogger(__name__)

_bot: Bot | None = None

# per-file download locks to avoid duplicate concurrent downloads
_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(
            settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot


async def close_bot() -> None:
    global _bot
    if _bot is not None:
        await _bot.session.close()
        _bot = None


def storage_target() -> int | None:
    if settings.storage_chat_id:
        return settings.storage_chat_id
    admins = sorted(settings.admin_id_set)
    return admins[0] if admins else None


# ---------------------------------------------------------------- download


async def _file_lock(key: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


async def download_to_cache(file_id: str, cache_key: str, ext: str) -> Path:
    """Download a Telegram file into the local cache and return its path."""
    cache_dir = settings.cache_path
    target = cache_dir / f"{cache_key}.{ext}"
    if target.exists() and target.stat().st_size > 0:
        target.touch()
        return target

    lock = await _file_lock(cache_key)
    async with lock:
        # another coroutine may have finished while we waited
        if target.exists() and target.stat().st_size > 0:
            target.touch()
            return target

        bot = get_bot()
        tg_file = await bot.get_file(file_id)
        if not tg_file.file_path:
            raise RuntimeError("Telegram did not return a file path")

        url = f"https://api.telegram.org/file/bot{settings.bot_token}/{tg_file.file_path}"
        tmp = target.with_suffix(target.suffix + ".part")
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as fh:
                    async for chunk in resp.aiter_bytes(64 * 1024):
                        fh.write(chunk)
        tmp.replace(target)
        await _evict_cache(keep=target.name)
        return target


async def _evict_cache(keep: str | None = None) -> None:
    limit = settings.cache_max_mb * 1024 * 1024
    if limit <= 0:
        return
    files = [p for p in settings.cache_path.glob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    if total <= limit:
        return
    files.sort(key=lambda p: p.stat().st_mtime)
    for path in files:
        if total <= limit:
            break
        if path.name == keep:
            continue
        try:
            total -= path.stat().st_size
            path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- upload


async def store_bytes(
    data: bytes,
    filename: str,
    mime_type: str | None = None,
) -> tuple[int | None, object]:
    """Send raw bytes to the storage chat. Returns (chat_id, message)."""
    target = storage_target()
    if target is None:
        raise RuntimeError(
            "未配置 STORAGE_CHAT_ID 或 ADMIN_IDS，无法进行 Web/API 上传"
        )
    bot = get_bot()
    message = await bot.send_document(
        chat_id=target,
        document=BufferedInputFile(data, filename=filename),
    )
    return target, message
