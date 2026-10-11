"""Import + DB smoke test. Run from project root: python -m scripts.smoke"""

import asyncio
import sys


async def main() -> int:
    # import every module to catch syntax/import errors
    import app.bot.admin  # noqa: F401
    import app.bot.common  # noqa: F401
    import app.bot.deletion  # noqa: F401
    import app.bot.info  # noqa: F401
    import app.bot.main  # noqa: F401
    import app.bot.middlewares  # noqa: F401
    import app.bot.upload  # noqa: F401
    import app.uploads  # noqa: F401
    import app.web.admin  # noqa: F401
    import app.web.api  # noqa: F401
    import app.web.deps  # noqa: F401
    import app.web.main  # noqa: F401
    import app.web.pages  # noqa: F401
    import app.web.user_auth  # noqa: F401
    from app.config import settings
    from app.db import SessionLocal, init_db
    from app.services import (
        NewImage,
        create_image,
        delete_user_images,
        get_or_create_user,
        get_user_stats,
        global_stats,
        set_admin,
        soft_delete_image,
    )
    from app.utils import human_size
    from app.web.user_auth import is_admin_user

    await init_db()
    async with SessionLocal() as session:
        user = await get_or_create_user(session, 111111111, "tester", "Test")
        assert user.is_admin == (111111111 in settings.admin_id_set)

        image = await create_image(
            session,
            NewImage(
                file_id="FILEID",
                file_unique_id="UNIQ",
                file_name="a.png",
                mime_type="image/png",
                file_size=1234,
                width=10,
                height=10,
                owner_id=user.id,
            ),
        )
        count, size = await get_user_stats(session, user.id)
        assert count == 1 and size == 1234, (count, size)
        assert image.ext == "png", image.ext

        stats = await global_stats(session)
        assert stats.images == 1, stats

        await soft_delete_image(session, image)
        count2, size2 = await get_user_stats(session, user.id)
        assert count2 == 0 and size2 == 0, (count2, size2)

    # --- token-based admin detection + user management ---
    async with SessionLocal() as session:
        # promote/demote + wipe images
        target = await get_or_create_user(session, 222222222, "member", "Member")
        assert not is_admin_user(target)
        await set_admin(session, target.id, True)
        target = await session.get(type(target), target.id)
        assert target.is_admin is True
        assert is_admin_user(target)
        await set_admin(session, target.id, False)
        target = await session.get(type(target), target.id)
        assert target.is_admin is False

        await create_image(
            session,
            NewImage(file_id="F2", file_unique_id="U2", file_size=10, owner_id=target.id),
        )
        removed = await delete_user_images(session, target.id)
        assert removed == 1, removed
        c, s = await get_user_stats(session, target.id)
        assert c == 0 and s == 0, (c, s)

    assert human_size(1536) == "1.5 KB", human_size(1536)
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
