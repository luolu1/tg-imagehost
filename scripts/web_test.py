"""Web/portal regression test using FastAPI TestClient + a temp SQLite DB.

Run: python -m scripts.web_test
Covers: admin pages render, per-user quota editing, bulk image delete,
bulk user actions, and the token-based user portal (login / dashboard / images).
"""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/opencode/test_web.db")
os.environ.setdefault("CACHE_DIR", "/tmp/opencode/cache_web")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Image, User  # noqa: E402
from app.services import (  # noqa: E402
    effective_quota,
    ensure_api_token,
    get_or_create_user,
)
from app.utils import gen_id  # noqa: E402
from app.web.main import app  # noqa: E402


async def _seed() -> tuple[str, int, list[str]]:
    await init_db()
    async with SessionLocal() as session:
        user = await get_or_create_user(session, 900000001, "portaluser", "Portal")
        token = await ensure_api_token(session, user)
        ids = []
        for i in range(3):
            iid = gen_id()
            ids.append(iid)
            session.add(
                Image(
                    id=iid,
                    owner_id=user.id,
                    file_id=f"F{i}",
                    file_unique_id=f"U{i}",
                    file_name=f"pic{i}.png",
                    mime_type="image/png",
                    file_size=1000 + i,
                    width=10,
                    height=10,
                    source="web",
                )
            )
        await session.commit()
        return token, user.id, ids


async def _image_deleted(image_id: str) -> bool:
    async with SessionLocal() as session:
        row = await session.get(Image, image_id)
        return bool(row and row.is_deleted)


async def _quota_of(user_id: int):
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        return effective_quota(user), user.quota_bytes


async def _user_flags(user_id: int):
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        return user.is_admin, user.is_banned


def main() -> int:
    token, uid, ids = asyncio.run(_seed())
    admin = (settings.admin_username, settings.admin_password)
    assert admin[1], "ADMIN_PASSWORD must be set for this test"

    with TestClient(app) as client:
        # --- admin pages render ---
        for path in ("/admin", "/admin/images", "/admin/users", "/admin/settings"):
            r = client.get(path, auth=admin)
            assert r.status_code == 200, (path, r.status_code, r.text[:300])
        r = client.get("/admin", auth=("nope", "nope"))
        assert r.status_code == 401, r.status_code

        # dashboard should contain the chart + a stat
        body = client.get("/admin", auth=admin).text
        assert "上传趋势" in body and "来源分布" in body

        # --- per-user quota ---
        r = client.post(f"/admin/users/{uid}/quota", data={"mb": "5"}, auth=admin, follow_redirects=False)
        assert r.status_code == 303, r.status_code
        quota, custom = asyncio.run(_quota_of(uid))
        assert quota == 5 * 1024 * 1024 and custom == 5 * 1024 * 1024, (quota, custom)

        client.post(f"/admin/users/{uid}/quota", data={"mb": "default"}, auth=admin, follow_redirects=False)
        quota2, custom2 = asyncio.run(_quota_of(uid))
        assert custom2 is None, custom2

        # users page shows the quota form
        assert "/quota" in client.get("/admin/users", auth=admin).text

        # --- bulk image delete (admin) ---
        r = client.post(
            "/admin/images/bulk-delete",
            data={"image_ids": ids[:2]},
            auth=admin,
            follow_redirects=False,
        )
        assert r.status_code == 303, r.status_code
        assert asyncio.run(_image_deleted(ids[0])) and asyncio.run(_image_deleted(ids[1]))

        # --- bulk user actions ---
        async def _make_target() -> int:
            async with SessionLocal() as session:
                u = await get_or_create_user(session, 900000002, "bulkuser", "Bulk")
                return u.id

        target_id = asyncio.run(_make_target())
        client.post(
            "/admin/users/bulk",
            data={"user_ids": [str(target_id)], "action": "promote"},
            auth=admin,
            follow_redirects=False,
        )
        assert asyncio.run(_user_flags(target_id)) == (True, False)
        client.post(
            "/admin/users/bulk",
            data={"user_ids": [str(target_id)], "action": "ban"},
            auth=admin,
            follow_redirects=False,
        )
        assert asyncio.run(_user_flags(target_id)) == (True, True)
        client.post(
            "/admin/users/bulk",
            data={"user_ids": [str(target_id)], "action": "unban"},
            auth=admin,
            follow_redirects=False,
        )
        client.post(
            "/admin/users/bulk",
            data={"user_ids": [str(target_id)], "action": "demote"},
            auth=admin,
            follow_redirects=False,
        )
        assert asyncio.run(_user_flags(target_id)) == (False, False)

        # --- user portal ---
        assert client.get("/my/login").status_code == 200
        # wrong token rejected
        assert client.post("/my/login", data={"token": "bad"}).status_code == 401
        # correct token -> redirect + cookie
        r = client.post("/my/login", data={"token": token}, follow_redirects=False)
        assert r.status_code == 303 and r.headers.get("location") == "/my", (r.status_code, r.headers)
        assert "tg_portal_token" in client.cookies

        dash = client.get("/my")
        assert dash.status_code == 200, dash.status_code
        assert "用户中心" in dash.text and "快速上传" in dash.text

        imgs = client.get("/my/images")
        assert imgs.status_code == 200
        assert ids[2] in imgs.text  # remaining image listed

        # portal bulk delete of the remaining image
        r = client.post("/my/images/bulk-delete", data={"image_ids": [ids[2]]}, follow_redirects=False)
        assert r.status_code == 303
        assert asyncio.run(_image_deleted(ids[2]))

        # portal cannot be accessed without cookie
        client.cookies.clear()
        r = client.get("/my", follow_redirects=False)
        assert r.status_code == 303 and r.headers.get("location") == "/my/login", r.status_code

        # --- public pages render ---
        assert client.get("/upload").status_code == 200
        assert client.get("/").status_code in (200, 307)

    print("WEB_PORTAL_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
