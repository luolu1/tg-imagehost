from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.models import Image
from app.utils import human_size


def success_text(image: Image) -> str:
    url = settings.image_url(image.id, image.ext)
    view = settings.view_url(image.id)
    dims = f"{image.width}×{image.height}" if image.width and image.height else "-"
    return (
        "✅ <b>上传成功</b>\n\n"
        f"🔗 直链：<code>{url}</code>\n"
        f"📄 页面：{view}\n"
        f"🆔 ID：<code>{image.id}</code>\n"
        f"📦 大小：{human_size(image.file_size)}  ·  {dims}"
    )


def success_keyboard(image: Image, owner: bool = True) -> InlineKeyboardMarkup:
    url = settings.image_url(image.id, image.ext)
    rows = [
        [
            InlineKeyboardButton(text="🌐 打开页面", url=settings.view_url(image.id)),
            InlineKeyboardButton(text="🔗 复制直链", url=url),
        ]
    ]
    if owner:
        rows.append(
            [InlineKeyboardButton(text="🗑 删除这张图", callback_data=f"del:{image.id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_keyboard(image_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ 确认删除", callback_data=f"delyes:{image_id}"),
                InlineKeyboardButton(text="↩️ 取消", callback_data="delno"),
            ]
        ]
    )
