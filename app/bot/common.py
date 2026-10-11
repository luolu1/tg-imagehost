from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.config import settings
from app.services import effective_quota, ensure_api_token, get_user_stats
from app.utils import human_size

router = Router(name="common")


def welcome_text(is_admin: bool) -> str:
    text = (
        f"👋 <b>欢迎使用 {settings.site_name}</b>\n\n"
        "把图片发给我，我会返回一个可直接访问的链接。\n\n"
        "<b>怎么用</b>\n"
        "· 直接发送图片 / 图片文件 → 得到直链\n"
        "· /id → 获取当前会话 Chat ID 和你的用户 ID\n"
        "· /token → 获取 API Token（用于 Web 与接口上传）\n"
        "· /stats → 查看我的用量\n"
        "· /delete &lt;ID&gt; 或回复图片 → 删除\n"
        "\n"
        f"🌐 上传页：{settings.upload_url()}\n"
        f"👤 用户中心：{settings.portal_url()}"
    )
    if is_admin:
        text += "\n\n👑 你是管理员，可使用 /admin 查看管理命令。"
    return text


@router.message(CommandStart())
async def cmd_start(message: Message, user) -> None:
    await message.answer(welcome_text(user.is_admin))


@router.message(Command("help"))
async def cmd_help(message: Message, user) -> None:
    await message.answer(welcome_text(user.is_admin))


@router.message(Command("token"))
async def cmd_token(message: Message, user, session) -> None:
    token = await ensure_api_token(session, user)
    text = (
        "🔑 <b>你的 API Token</b>\n\n"
        f"<code>{token}</code>\n\n"
        "用法：在 Web 上传页填写，或作为 "
        "<code>Authorization: Bearer &lt;token&gt;</code> 调用接口。\n"
        f"👤 也可用它在用户中心登录：{settings.portal_url()}\n"
        "⚠️ 不要泄露给他人。"
    )
    await message.answer(text)


@router.message(Command("stats"))
async def cmd_stats(message: Message, user, session) -> None:
    count, size = await get_user_stats(session, user.id)
    quota = effective_quota(user)
    quota_text = human_size(quota) if quota > 0 else "不限"
    text = (
        "📊 <b>我的用量</b>\n\n"
        f"🖼 图片数量：{count}\n"
        f"📦 已用空间：{human_size(size)}\n"
        f"🎯 配额：{quota_text}"
    )
    await message.answer(text)


@router.message(Command("admin"))
async def cmd_admin(message: Message, user) -> None:
    if not user.is_admin:
        await message.answer("⛔ 仅管理员可用。")
        return
    text = (
        "👑 <b>管理命令</b>\n\n"
        "/ban &lt;user_id&gt; — 封禁用户\n"
        "/unban &lt;user_id&gt; — 解封用户\n"
        "/promote &lt;user_id&gt; — 设为管理员\n"
        "/demote &lt;user_id&gt; — 取消管理员\n"
        "/userinfo &lt;user_id&gt; — 查看用户\n"
        "/quota &lt;user_id&gt; [MB] — 设置/查看配额\n"
        "/broadcast &lt;文本&gt; — 全员广播\n"
        "\n（删除图片：回复图片发送 /delete，或用 /delete &lt;ID&gt;）\n"
        f"\n🌐 管理后台：{settings.admin_url()}"
    )
    await message.answer(text)
