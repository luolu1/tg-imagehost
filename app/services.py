from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Image, Setting, User, utcnow
from app.utils import gen_id, gen_token


# ---------------------------------------------------------------- users


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        user = User(
            id=user_id,
            username=username,
            first_name=first_name,
            is_admin=user_id in settings.admin_id_set,
        )
        session.add(user)
        await session.commit()
    else:
        changed = False
        if username != user.username:
            user.username = username
            changed = True
        if first_name != user.first_name:
            user.first_name = first_name
            changed = True
        if user_id in settings.admin_id_set and not user.is_admin:
            user.is_admin = True
            changed = True
        if changed:
            await session.commit()
    return user


async def get_user_by_token(session: AsyncSession, token: str) -> User | None:
    result = await session.execute(select(User).where(User.api_token == token))
    return result.scalar_one_or_none()


async def ensure_api_token(session: AsyncSession, user: User) -> str:
    if not user.api_token:
        user.api_token = gen_token()
        await session.commit()
    return user.api_token


async def rotate_api_token(session: AsyncSession, user: User) -> str:
    """Generate a brand new API token for the user."""
    user.api_token = gen_token()
    await session.commit()
    return user.api_token


async def get_user_stats(session: AsyncSession, user_id: int) -> tuple[int, int]:
    """Return (image_count, total_size) for an active user."""
    stmt = select(func.count(Image.id), func.coalesce(func.sum(Image.file_size), 0)).where(
        Image.owner_id == user_id, Image.is_deleted.is_(False)
    )
    count, size = (await session.execute(stmt)).one()
    return int(count), int(size)


def effective_quota(user: User | None) -> int:
    """Per-user quota in bytes; ``None`` per-user means inherit the global default."""
    if user is not None and user.quota_bytes is not None:
        return int(user.quota_bytes)
    return settings.quota_bytes


async def set_user_quota(
    session: AsyncSession, user_id: int, quota_bytes: int | None
) -> User | None:
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.quota_bytes = quota_bytes
    await session.commit()
    return user


# ---------------------------------------------------------------- images


@dataclass
class NewImage:
    file_id: str
    file_unique_id: str | None = None
    thumb_file_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int = 0
    width: int | None = None
    height: int | None = None
    source: str = "telegram"
    storage_chat_id: int | None = None
    storage_message_id: int | None = None
    owner_id: int | None = None


async def create_image(session: AsyncSession, data: NewImage) -> Image:
    image = Image(
        id=gen_id(),
        owner_id=data.owner_id,
        file_id=data.file_id,
        file_unique_id=data.file_unique_id,
        thumb_file_id=data.thumb_file_id,
        file_name=data.file_name,
        mime_type=data.mime_type,
        file_size=data.file_size,
        width=data.width,
        height=data.height,
        source=data.source,
        storage_chat_id=data.storage_chat_id,
        storage_message_id=data.storage_message_id,
    )
    session.add(image)

    if data.owner_id is not None:
        user = await session.get(User, data.owner_id)
        if user is not None:
            user.upload_count += 1
            user.total_size += data.file_size

    await session.commit()
    return image


async def get_image(session: AsyncSession, image_id: str, include_deleted: bool = False) -> Image | None:
    image = await session.get(Image, image_id)
    if image is None:
        return None
    if image.is_deleted and not include_deleted:
        return None
    return image


async def bump_views(session: AsyncSession, image: Image) -> None:
    image.views += 1
    await session.commit()


async def soft_delete_image(session: AsyncSession, image: Image) -> None:
    if image.is_deleted:
        return
    image.is_deleted = True
    image.deleted_at = utcnow()
    if image.owner_id is not None:
        user = await session.get(User, image.owner_id)
        if user is not None:
            user.upload_count = max(0, user.upload_count - 1)
            user.total_size = max(0, user.total_size - image.file_size)
    await session.commit()


async def get_image_by_unique(
    session: AsyncSession, file_unique_id: str, owner_id: int | None = None
) -> Image | None:
    stmt = select(Image).where(
        Image.file_unique_id == file_unique_id, Image.is_deleted.is_(False)
    )
    if owner_id is not None:
        stmt = stmt.where(Image.owner_id == owner_id)
    stmt = stmt.order_by(Image.created_at.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def find_user_images(
    session: AsyncSession, user_id: int, limit: int = 10, offset: int = 0
) -> list[Image]:
    stmt = (
        select(Image)
        .where(Image.owner_id == user_id, Image.is_deleted.is_(False))
        .order_by(Image.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars())


async def recent_images(
    session: AsyncSession, limit: int = 12, source: str | None = None
) -> list[Image]:
    """Most recent active uploads, optionally filtered by source."""
    stmt = select(Image).where(Image.is_deleted.is_(False))
    if source is not None:
        stmt = stmt.where(Image.source == source)
    stmt = stmt.order_by(Image.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def list_images(
    session: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    owner_id: int | None = None,
    include_deleted: bool = True,
    search: str | None = None,
) -> tuple[list[Image], int]:
    conditions = []
    if owner_id is not None:
        conditions.append(Image.owner_id == owner_id)
    if not include_deleted:
        conditions.append(Image.is_deleted.is_(False))
    if search:
        conditions.append(Image.id.like(f"%{search}%"))

    base = select(Image)
    count_stmt = select(func.count(Image.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    base = base.order_by(Image.created_at.desc()).limit(limit).offset(offset)
    images = list((await session.execute(base)).scalars())
    total = int((await session.execute(count_stmt)).scalar_one())
    return images, total


async def list_users(
    session: AsyncSession, limit: int = 50, offset: int = 0, search: str | None = None
) -> tuple[list[User], int]:
    base = select(User)
    count_stmt = select(func.count(User.id))
    if search:
        try:
            uid = int(search)
            cond = User.id == uid
        except ValueError:
            cond = User.username.like(f"%{search}%")
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)
    base = base.order_by(User.created_at.desc()).limit(limit).offset(offset)
    users = list((await session.execute(base)).scalars())
    total = int((await session.execute(count_stmt)).scalar_one())
    return users, total


async def all_user_ids(session: AsyncSession) -> list[int]:
    result = await session.execute(select(User.id).where(User.is_banned.is_(False)))
    return list(result.scalars())


async def set_banned(session: AsyncSession, user_id: int, banned: bool) -> User | None:
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.is_banned = banned
    await session.commit()
    return user


async def set_admin(session: AsyncSession, user_id: int, is_admin: bool) -> User | None:
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.is_admin = is_admin
    await session.commit()
    return user


async def delete_user_images(session: AsyncSession, user_id: int) -> int:
    """Soft-delete every active image owned by a user. Returns how many were affected."""
    stmt = select(Image).where(Image.owner_id == user_id, Image.is_deleted.is_(False))
    images = list((await session.execute(stmt)).scalars())
    now = utcnow()
    for image in images:
        image.is_deleted = True
        image.deleted_at = now
    user = await session.get(User, user_id)
    if user is not None:
        user.upload_count = 0
        user.total_size = 0
    await session.commit()
    return len(images)


async def delete_images(
    session: AsyncSession, image_ids: list[str], owner_id: int | None = None
) -> int:
    """Soft-delete the given images; when ``owner_id`` is set only that owner's rows."""
    if not image_ids:
        return 0
    stmt = select(Image).where(Image.id.in_(image_ids), Image.is_deleted.is_(False))
    if owner_id is not None:
        stmt = stmt.where(Image.owner_id == owner_id)
    images = list((await session.execute(stmt)).scalars())
    now = utcnow()
    for image in images:
        image.is_deleted = True
        image.deleted_at = now
        if image.owner_id is not None:
            user = await session.get(User, image.owner_id)
            if user is not None:
                user.upload_count = max(0, user.upload_count - 1)
                user.total_size = max(0, user.total_size - image.file_size)
    await session.commit()
    return len(images)


# ---------------------------------------------------------------- settings


async def get_setting(
    session: AsyncSession, key: str, default: str | None = None
) -> str | None:
    row = await session.get(Setting, key)
    return row.value if row is not None else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    await session.commit()


async def delete_setting(session: AsyncSession, key: str) -> None:
    row = await session.get(Setting, key)
    if row is not None:
        await session.delete(row)
        await session.commit()


# ---------------------------------------------------------------- global stats


@dataclass
class GlobalStats:
    users: int
    images: int
    deleted_images: int
    total_size: int
    today_images: int


async def global_stats(session: AsyncSession) -> GlobalStats:
    users = int((await session.execute(select(func.count(User.id)))).scalar_one())
    images = int(
        (
            await session.execute(
                select(func.count(Image.id)).where(Image.is_deleted.is_(False))
            )
        ).scalar_one()
    )
    deleted = int(
        (
            await session.execute(
                select(func.count(Image.id)).where(Image.is_deleted.is_(True))
            )
        ).scalar_one()
    )
    total_size = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(Image.file_size), 0)).where(
                    Image.is_deleted.is_(False)
                )
            )
        ).scalar_one()
    )
    midnight = dt.datetime.now(dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today = int(
        (
            await session.execute(
                select(func.count(Image.id)).where(Image.created_at >= midnight)
            )
        ).scalar_one()
    )
    return GlobalStats(users, images, deleted, total_size, today)


async def quota_exceeded(session: AsyncSession, user: User, incoming: int) -> bool:
    quota = effective_quota(user)
    if quota <= 0:
        return False
    _, used = await get_user_stats(session, user.id)
    return used + incoming > quota


# ---------------------------------------------------------------- charts


async def uploads_per_day(
    session: AsyncSession, days: int = 14, owner_id: int | None = None
) -> list[dict]:
    """Daily upload counts for the last ``days`` days (UTC), oldest first."""
    today = dt.datetime.now(dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = today - dt.timedelta(days=days - 1)
    stmt = select(Image.created_at).where(Image.created_at >= start)
    if owner_id is not None:
        stmt = stmt.where(Image.owner_id == owner_id)
    rows = (await session.execute(stmt)).scalars().all()

    buckets: dict[dt.date, int] = {}
    for ts in rows:
        if ts.tzinfo is None:
            key = ts.date()
        else:
            key = ts.astimezone(dt.timezone.utc).date()
        buckets[key] = buckets.get(key, 0) + 1

    series: list[dict] = []
    for i in range(days):
        day = (start + dt.timedelta(days=i)).date()
        series.append(
            {"date": day.isoformat(), "label": f"{day.month}/{day.day}", "count": buckets.get(day, 0)}
        )
    return series


async def source_breakdown(session: AsyncSession) -> list[dict]:
    """Active image counts grouped by upload source."""
    stmt = (
        select(Image.source, func.count(Image.id))
        .where(Image.is_deleted.is_(False))
        .group_by(Image.source)
        .order_by(func.count(Image.id).desc())
    )
    return [{"source": s or "unknown", "count": int(c)} for s, c in (await session.execute(stmt)).all()]


async def top_uploaders(session: AsyncSession, limit: int = 5) -> list[dict]:
    """Users ranked by their active image count."""
    stmt = (
        select(
            User.id,
            User.username,
            User.first_name,
            func.count(Image.id),
            func.coalesce(func.sum(Image.file_size), 0),
        )
        .join(Image, Image.owner_id == User.id)
        .where(Image.is_deleted.is_(False))
        .group_by(User.id)
        .order_by(func.count(Image.id).desc())
        .limit(limit)
    )
    return [
        {
            "id": uid,
            "username": username,
            "first_name": first_name,
            "count": int(count),
            "size": int(size),
        }
        for uid, username, first_name, count, size in (await session.execute(stmt)).all()
    ]
