from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="info")

_bot_username: str | None = None


def set_bot_username(username: str | None) -> None:
    global _bot_username
    _bot_username = username


def _esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def _mentions_bot(message: Message) -> bool:
    if not _bot_username:
        return False
    text = message.text or message.caption or ""
    return f"@{_bot_username}".lower() in text.lower()


def _has_media(message: Message) -> bool:
    return bool(
        message.photo
        or message.document
        or message.video
        or message.audio
        or message.voice
        or message.sticker
        or message.animation
    )


def _info_text(message: Message) -> str:
    chat = message.chat
    lines: list[str] = []

    lines.append("📋 <b>当前上下文信息</b>")
    lines.append("")

    # Who is talking (private / group only; channels have no from_user)
    if message.from_user is not None:
        u = message.from_user
        name = u.full_name or "-"
        lines.append("👤 <b>发送者（用户）</b>")
        lines.append(f"用户 ID：<code>{u.id}</code>")
        lines.append(f"昵称：{_esc(name)}")
        lines.append(f"用户名：{('@' + _esc(u.username)) if u.username else '-'}")
        lines.append(f"语言：{_esc(u.language_code or '-')}")
    elif message.sender_chat is not None:
        sc = message.sender_chat
        lines.append("📢 <b>发送者（频道/匿名）</b>")
        lines.append(f"会话 ID：<code>{sc.id}</code>")
        lines.append(f"标题：{_esc(sc.title or '-')}")
        lines.append(f"类型：<code>{sc.type}</code>")
    lines.append("")

    # Where we are
    lines.append("💬 <b>当前会话（Chat）</b>")
    lines.append(f"Chat ID：<code>{chat.id}</code>")
    lines.append(f"类型：<code>{chat.type}</code>")
    if chat.title:
        lines.append(f"标题：{_esc(chat.title)}")
    if chat.username:
        lines.append(f"链接：@{_esc(chat.username)}")
    if message.message_thread_id:
        lines.append(f"话题 ID：<code>{message.message_thread_id}</code>")
    lines.append("")

    # Practical hints
    lines.append("🛠 <b>怎么用</b>")
    if chat.type in ("group", "supergroup", "channel"):
        lines.append(
            f"把上面的 Chat ID（<code>{chat.id}</code>）填进 .env 的 "
            "<code>STORAGE_CHAT_ID</code>，即可用本会话做图片存储。"
        )
    if message.from_user is not None:
        lines.append(
            f"把用户 ID（<code>{message.from_user.id}</code>）填进 "
            "<code>ADMIN_IDS</code>，即可把自己设为管理员。"
        )
    lines.append("")
    lines.append(
        "ℹ️ 说明：Telegram Bot 无法获取用户 IP 地址（Bot API 不提供），"
        "上面能拿到的是用户 ID 与 Chat ID。"
    )

    return "\n".join(lines)


async def _send_info(message: Message) -> None:
    from aiogram.types import LinkPreviewOptions

    await message.answer(
        _info_text(message),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.message(Command("id", "chatid", "info", "whereami", "whoami"))
async def cmd_info(message: Message) -> None:
    await _send_info(message)


@router.channel_post(Command("id", "chatid", "info", "whereami", "whoami"))
async def cmd_info_channel(post: Message) -> None:
    await _send_info(post)


# @mention with plain text (no media) -> show context info.
@router.message(F.text & ~F.text.startswith("/"))
async def on_mention(message: Message) -> None:
    if _mentions_bot(message) and not _has_media(message):
        await _send_info(message)


@router.channel_post(F.text)
async def on_channel_mention(post: Message) -> None:
    if _mentions_bot(post):
        await _send_info(post)
