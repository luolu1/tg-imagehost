from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import LinkPreviewOptions, Message

from app.bot.keyboards import success_keyboard, success_text
from app.config import settings
from app.services import NewImage, create_image, effective_quota, quota_exceeded
from app.utils import human_size

log = logging.getLogger(__name__)
router = Router(name="upload")

ALLOWED_EXT = {
    "jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "ico",
    "tif", "tiff", "avif", "heic",
}


def _is_image_document(message: Message) -> bool:
    doc = message.document
    if doc is None:
        return False
    if doc.mime_type and doc.mime_type.startswith("image/"):
        return True
    if doc.file_name and "." in doc.file_name:
        return doc.file_name.rsplit(".", 1)[1].lower() in ALLOWED_EXT
    return False


async def _addressed_to_bot(message: Message, bot: Bot) -> bool:
    """Decide whether a group message should be handled."""
    if message.chat.type == "private":
        return True
    if settings.group_process_all:
        return True
    if message.reply_to_message and message.reply_to_message.from_user:
        me = await bot.get_me()
        if message.reply_to_message.from_user.id == me.id:
            return True
    if message.caption:
        me = await bot.get_me()
        if me.username and f"@{me.username}".lower() in message.caption.lower():
            return True
    return False


async def _handle(message: Message, bot: Bot, user, session, *, file_id, unique_id,
                  file_name, mime_type, file_size, width, height, thumb_id) -> None:
    if file_size and file_size > settings.max_upload_bytes:
        await message.reply(
            f"❌ 文件过大（{human_size(file_size)}），上限 {settings.max_upload_mb} MB。"
        )
        return
    if await quota_exceeded(session, user, file_size or 0):
        await message.reply(
            f"❌ 配额已满（{human_size(effective_quota(user))}），请先删除部分图片。"
        )
        return

    storage_chat_id = None
    storage_message_id = None
    if settings.storage_chat_id:
        try:
            copied = await bot.copy_message(
                chat_id=settings.storage_chat_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            storage_chat_id = settings.storage_chat_id
            storage_message_id = copied.message_id
        except Exception:  # noqa: BLE001 - archive is best effort
            log.warning("failed to archive message to storage chat", exc_info=True)

    image = await create_image(
        session,
        NewImage(
            file_id=file_id,
            file_unique_id=unique_id,
            thumb_file_id=thumb_id,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size or 0,
            width=width,
            height=height,
            source="telegram",
            storage_chat_id=storage_chat_id,
            storage_message_id=storage_message_id,
            owner_id=user.id,
        ),
    )
    await message.reply(
        success_text(image),
        reply_markup=success_keyboard(image, owner=True),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot, user, session) -> None:
    if not await _addressed_to_bot(message, bot):
        return
    photo = message.photo[-1]
    await _handle(
        message, bot, user, session,
        file_id=photo.file_id,
        unique_id=photo.file_unique_id,
        file_name=f"{photo.file_unique_id}.jpg",
        mime_type="image/jpeg",
        file_size=photo.file_size or 0,
        width=photo.width,
        height=photo.height,
        thumb_id=photo.file_id,
    )


@router.message(F.document)
async def on_document(message: Message, bot: Bot, user, session) -> None:
    if not await _addressed_to_bot(message, bot):
        return
    if not _is_image_document(message):
        await message.reply("❌ 请发送图片文件（jpg/png/gif/webp 等）。")
        return
    doc = message.document
    thumb_id = doc.thumbnail.file_id if doc.thumbnail else None
    await _handle(
        message, bot, user, session,
        file_id=doc.file_id,
        unique_id=doc.file_unique_id,
        file_name=doc.file_name or f"{doc.file_unique_id}",
        mime_type=doc.mime_type,
        file_size=doc.file_size or 0,
        width=None,
        height=None,
        thumb_id=thumb_id,
    )
