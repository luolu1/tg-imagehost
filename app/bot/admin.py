from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from app.models import User
from app.services import (
    all_user_ids,
    effective_quota,
    get_user_stats,
    set_admin,
    set_banned,
    set_user_quota,
)
from app.utils import human_size

log = logging.getLogger(__name__)
router = Router(name="admin")


async def _require_admin(message: Message, user) -> bool:
    if not user.is_admin:
        await message.reply("⛔ 仅管理员可用。")
        return False
    return True


async def _target_id(message: Message) -> int | None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return None
    try:
        return int(parts[1].strip())
    except ValueError:
        return None


@router.message(Command("ban"))
async def cmd_ban(message: Message, user, session) -> None:
    if not await _require_admin(message, user):
        return
    target = await _target_id(message)
    if target is None:
        await message.reply("用法：/ban &lt;user_id&gt;")
        return
    if target in settings.admin_id_set:
        await message.reply("该用户是超级管理员（来自 .env），不能封禁。")
        return
    result = await set_banned(session, target, True)
    if result is None:
        await message.reply("未找到该用户。")
    else:
        await message.reply(f"🚫 已封禁 <code>{target}</code>")


@router.message(Command("unban"))
async def cmd_unban(message: Message, user, session) -> None:
    if not await _require_admin(message, user):
        return
    target = await _target_id(message)
    if target is None:
        await message.reply("用法：/unban &lt;user_id&gt;")
        return
    result = await set_banned(session, target, False)
    if result is None:
        await message.reply("未找到该用户。")
    else:
        await message.reply(f"✅ 已解封 <code>{target}</code>")


@router.message(Command("userinfo"))
async def cmd_userinfo(message: Message, user, session) -> None:
    if not await _require_admin(message, user):
        return
    target = await _target_id(message)
    if target is None:
        await message.reply("用法：/userinfo &lt;user_id&gt;")
        return
    target_user = await session.get(User, target)
    if target_user is None:
        await message.reply("未找到该用户。")
        return
    count, size = await get_user_stats(session, target)
    status = "🚫 已封禁" if target_user.is_banned else "✅ 正常"
    role = "超级管理员" if target in settings.admin_id_set else ("管理员" if target_user.is_admin else "普通用户")
    quota = effective_quota(target_user)
    quota_text = human_size(quota) if quota > 0 else "不限"
    custom = "（单独设置）" if target_user.quota_bytes is not None else ""
    await message.reply(
        f"<b>用户信息</b>\n"
        f"ID：<code>{target_user.id}</code>\n"
        f"用户名：@{target_user.username or '-'}\n"
        f"昵称：{target_user.first_name or '-'}\n"
        f"状态：{status}\n"
        f"图片数：{count}\n"
        f"已用空间：{human_size(size)}\n"
        f"配额：{quota_text}{custom}\n"
        f"角色：{role}"
    )


@router.message(Command("promote"))
async def cmd_promote(message: Message, user, session) -> None:
    if not await _require_admin(message, user):
        return
    target = await _target_id(message)
    if target is None:
        await message.reply("用法：/promote &lt;user_id&gt;")
        return
    result = await set_admin(session, target, True)
    if result is None:
        await message.reply("未找到该用户。")
    else:
        await message.reply(f"👑 已将 <code>{target}</code> 设为管理员")


@router.message(Command("demote"))
async def cmd_demote(message: Message, user, session) -> None:
    if not await _require_admin(message, user):
        return
    target = await _target_id(message)
    if target is None:
        await message.reply("用法：/demote &lt;user_id&gt;")
        return
    if target in settings.admin_id_set:
        await message.reply("该用户是超级管理员（来自 .env），不能取消。")
        return
    result = await set_admin(session, target, False)
    if result is None:
        await message.reply("未找到该用户。")
    else:
        await message.reply(f"已将 <code>{target}</code> 取消管理员")


@router.message(Command("quota"))
async def cmd_quota(message: Message, user, session) -> None:
    if not await _require_admin(message, user):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.reply(
            "用法：/quota &lt;user_id&gt; [MB]\n"
            "· 不填 MB → 查看当前配额\n"
            "· MB=0 → 不限量\n"
            "· MB=default → 恢复全局默认"
        )
        return
    try:
        target = int(parts[1])
    except ValueError:
        await message.reply("用户 ID 必须是数字。")
        return
    target_user = await session.get(User, target)
    if target_user is None:
        await message.reply("未找到该用户。")
        return
    if len(parts) < 3:
        quota = effective_quota(target_user)
        text = human_size(quota) if quota > 0 else "不限"
        await message.reply(f"用户 <code>{target}</code> 配额：{text}")
        return
    raw = parts[2].strip().lower()
    if raw in ("default", "inherit", "-"):
        await set_user_quota(session, target, None)
        await message.reply(f"已将 <code>{target}</code> 的配额恢复为全局默认。")
        return
    try:
        mb = float(raw)
    except ValueError:
        await message.reply("MB 必须是数字、0 或 default。")
        return
    if mb < 0:
        await message.reply("MB 不能为负数。")
        return
    quota_bytes = int(mb * 1024 * 1024)
    await set_user_quota(session, target, quota_bytes)
    text = human_size(quota_bytes) if quota_bytes > 0 else "不限"
    await message.reply(f"已将 <code>{target}</code> 的配额设为 {text}。")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, user, session, bot: Bot) -> None:
    if not await _require_admin(message, user):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("用法：/broadcast &lt;文本&gt;")
        return
    text = parts[1]
    ids = await all_user_ids(session)
    sent = 0
    for uid in ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.05)
    await message.reply(f"📣 广播完成：成功 {sent}/{len(ids)}")
