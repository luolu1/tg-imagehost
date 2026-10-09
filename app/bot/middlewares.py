from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update, User as TgUser

from app.config import settings
from app.db import SessionLocal
from app.services import get_or_create_user

log = logging.getLogger(__name__)


def _inner_message(event: TelegramObject) -> Message | None:
    """User-authored message (channel_post is intentionally excluded)."""
    if isinstance(event, Message):
        return event
    if isinstance(event, Update):
        return event.message or event.edited_message
    return None


def _inner_callback(event: TelegramObject) -> CallbackQuery | None:
    if isinstance(event, CallbackQuery):
        return event
    if isinstance(event, Update):
        return event.callback_query
    return None


class ContextMiddleware(BaseMiddleware):
    """Opens a DB session, upserts the user and enforces bans."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None:
            tg_user = getattr(event, "from_user", None)

        inner_message = _inner_message(event)
        inner_callback = _inner_callback(event)

        async with SessionLocal() as session:
            data["session"] = session

            # No usable user (anonymous group admin / channel post / bot).
            # User-scoped handlers need a `user`, so skip them cleanly.
            if tg_user is None or tg_user.is_bot:
                if inner_message is not None or inner_callback is not None:
                    return None
                return await handler(event, data)

            user = await get_or_create_user(
                session,
                tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
            )
            data["user"] = user

            if user.is_banned and tg_user.id not in settings.admin_id_set:
                if inner_message is not None:
                    try:
                        await inner_message.answer("🚫 你已被禁止使用本服务。")
                    except Exception:  # noqa: BLE001
                        pass
                elif inner_callback is not None:
                    try:
                        await inner_callback.answer("🚫 你已被禁止使用本服务。", show_alert=True)
                    except Exception:  # noqa: BLE001
                        pass
                return None

            return await handler(event, data)
