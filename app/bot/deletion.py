from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import confirm_delete_keyboard
from app.services import get_image, get_image_by_unique, soft_delete_image

router = Router(name="deletion")


def _can_manage(user, image) -> bool:
    return user.is_admin or image.owner_id == user.id


@router.message(Command("delete", "del"))
async def cmd_delete(message: Message, user, session) -> None:
    image = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2:
        image = await get_image(session, parts[1].strip())
    elif message.reply_to_message:
        replied = message.reply_to_message
        unique_id = None
        if replied.photo:
            unique_id = replied.photo[-1].file_unique_id
        elif replied.document:
            unique_id = replied.document.file_unique_id
        if unique_id:
            image = await get_image_by_unique(
                session, unique_id, None if user.is_admin else user.id
            )

    if image is None:
        await message.reply("未找到对应图片。用法：/delete &lt;ID&gt;，或回复一张图片。")
        return
    if not _can_manage(user, image):
        await message.reply("⛔ 你只能删除自己上传的图片。")
        return
    await message.reply(
        f"确认删除 <code>{image.id}</code>？",
        reply_markup=confirm_delete_keyboard(image.id),
    )


@router.callback_query(F.data.startswith("del:"))
async def cb_delete(callback: CallbackQuery, user, session) -> None:
    image_id = callback.data.split(":", 1)[1]
    image = await get_image(session, image_id)
    if image is None:
        await callback.answer("图片不存在或已删除", show_alert=True)
        return
    if not _can_manage(user, image):
        await callback.answer("⛔ 你只能删除自己上传的图片", show_alert=True)
        return
    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=confirm_delete_keyboard(image.id)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("delyes:"))
async def cb_delete_yes(callback: CallbackQuery, user, session) -> None:
    image_id = callback.data.split(":", 1)[1]
    image = await get_image(session, image_id)
    if image is None:
        await callback.answer("图片不存在或已删除", show_alert=True)
        return
    if not _can_manage(user, image):
        await callback.answer("⛔ 无权限", show_alert=True)
        return
    await soft_delete_image(session, image)
    if callback.message is not None:
        await callback.message.edit_text(f"🗑 已删除 <code>{image.id}</code>")
    await callback.answer("已删除")


@router.callback_query(F.data == "delno")
async def cb_delete_no(callback: CallbackQuery) -> None:
    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
    await callback.answer("已取消")
