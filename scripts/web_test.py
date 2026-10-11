"""Web/portal regression test using FastAPI TestClient + a temp SQLite DB.

Run: python -m scripts.web_test
Covers: token-based admin access (admin logs in via /my/login and lands on
/admin), per-user quota editing, bulk image delete, bulk user actions, and the
regular user portal (login / dashboard / images). Non-admins are redirected
away from /admin.
"""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/opencode/test_web.db")
os.environ.setdefault("CACHE_DIR", "/tmp/opencode/cache_web")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Image, User  # noqa: E402
from app.services import (  # noqa: E402
    effective_quota,
    ensure_api_token,
    get_or_create_user,
    set_admin,
)
from app.utils import gen_id  # noqa: E402
from app.web.main import app  # noqa: E402


async def _seed() -> tuple[str, str, int, list[str]]:
    """Returns (admin_token, user_token, user_id, image_ids)."""
    await init_db()
    async with SessionLocal() as session:
        admin = await get_or_create_user(session, 900000000, "adminuser", "Admin")
        await set_admin(session, admin.id, True)
        admin_token = await ensure_api_token(session, admin)

        user = await get_or_create_user(session, 900000001, "portaluser", "Portal")
        user_token = await ensure_api_token(session, user)
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
        return admin_token, user_token, user.id, ids


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
    admin_token, user_token, uid, ids = asyncio.run(_seed())

    with TestClient(app) as client:
        # --- admin logs in via token and lands on /admin ---
        r = client.post("/my/login", data={"token": admin_token}, follow_redirects=False)
        assert r.status_code == 303 and r.headers.get("location") == "/admin", (
            r.status_code,
            r.headers.get("location"),
        )

        # admin pages render (cookie now set on the client)
        for path in ("/admin", "/admin/images", "/admin/users"):
            r = client.get(path)
            assert r.status_code == 200, (path, r.status_code, r.text[:300])

        # the removed settings route no longer exists
        assert client.get("/admin/settings").status_code == 404

        # dashboard should contain the chart + a stat
        body = client.get("/admin").text
        assert "上传趋势" in body and "来源分布" in body

        # --- per-user quota ---
        r = client.post(f"/admin/users/{uid}/quota", data={"mb": "5"}, follow_redirects=False)
        assert r.status_code == 303, r.status_code
        quota, custom = asyncio.run(_quota_of(uid))
        assert quota == 5 * 1024 * 1024 and custom == 5 * 1024 * 1024, (quota, custom)

        client.post(f"/admin/users/{uid}/quota", data={"mb": "default"}, follow_redirects=False)
        quota2, custom2 = asyncio.run(_quota_of(uid))
        assert custom2 is None, custom2

        # users page shows the quota form
        assert "/quota" in client.get("/admin/users").text

        # --- bulk image delete (admin) ---
        r = client.post(
            "/admin/images/bulk-delete",
            data={"image_ids": ids[:2]},
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
            follow_redirects=False,
        )
        assert asyncio.run(_user_flags(target_id)) == (True, False)
        client.post(
            "/admin/users/bulk",
            data={"user_ids": [str(target_id)], "action": "ban"},
            follow_redirects=False,
        )
        assert asyncio.run(_user_flags(target_id)) == (True, True)
        client.post(
            "/admin/users/bulk",
            data={"user_ids": [str(target_id)], "action": "unban"},
            follow_redirects=False,
        )
        client.post(
            "/admin/users/bulk",
            data={"user_ids": [str(target_id)], "action": "demote"},
            follow_redirects=False,
        )
        assert asyncio.run(_user_flags(target_id)) == (False, False)

        # --- regular user portal ---
        client.cookies.clear()
        assert client.get("/my/login").status_code == 200
        # wrong token rejected
        assert client.post("/my/login", data={"token": "bad"}).status_code == 401
        # correct token -> redirect to /my + cookie
        r = client.post("/my/login", data={"token": user_token}, follow_redirects=False)
        assert r.status_code == 303 and r.headers.get("location") == "/my", (r.status_code, r.headers)
        assert "tg_portal_token" in client.cookies

        dash = client.get("/my")
        assert dash.status_code == 200, dash.status_code
        assert "快速上传" in dash.text

        imgs = client.get("/my/images")
        assert imgs.status_code == 200
        assert ids[2] in imgs.text  # remaining image listed

        # a normal user cannot reach /admin -> redirected to /my
        r = client.get("/admin", follow_redirects=False)
        assert r.status_code == 303 and r.headers.get("location") == "/my", (
            r.status_code,
            r.headers.get("location"),
        )

        # portal bulk delete of the remaining image
        r = client.post("/my/images/bulk-delete", data={"image_ids": [ids[2]]}, follow_redirects=False)
        assert r.status_code == 303
        assert asyncio.run(_image_deleted(ids[2]))

        # portal cannot be accessed without cookie
        client.cookies.clear()
        r = client.get("/my", follow_redirects=False)
        assert r.status_code == 303 and r.headers.get("location") == "/my/login", r.status_code

        # /admin without cookie -> login
        r = client.get("/admin", follow_redirects=False)
        assert r.status_code == 303 and r.headers.get("location") == "/my/login", r.status_code

        # --- public pages render ---
        assert client.get("/upload").status_code == 200
        assert client.get("/").status_code in (200, 307)
        # favicon + TOS
        fav = client.get("/favicon.svg")
        assert fav.status_code == 200 and "svg" in fav.headers.get("content-type", "")
        tos = client.get("/tos")
        assert tos.status_code == 200 and "使用条款" in tos.text
        # API docs: human page + interactive docs + OpenAPI schema
        api_docs = client.get("/api-docs")
        assert api_docs.status_code == 200 and "/api/upload" in api_docs.text
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        assert "/api/upload" in schema.json()["paths"]

        # --- guest upload: no token needed, stored ownerless + source=guest ---
        import io

        import app.web.pages as pages_mod
        from app.services import NewImage, create_image

        async def _fake_upload(session, *, owner_id, filename, mime_type, data, source="web"):
            async with SessionLocal() as s:
                img = await create_image(
                    s,
                    NewImage(
                        file_id="GUESTFID",
                        file_unique_id="GUESTUNIQ",
                        file_name=filename,
                        mime_type=mime_type,
                        file_size=len(data),
                        source=source,
                        owner_id=owner_id,
                    ),
                )
                return img

        orig = pages_mod.upload_bytes
        pages_mod.upload_bytes = _fake_upload
        try:
            r = client.post(
                "/upload",
                files={"file": ("guest.png", io.BytesIO(b"x" * 32), "image/png")},
            )
            assert r.status_code == 201, (r.status_code, r.text[:200])
            body = r.json()
            assert body["id"] and body["url"], body
        finally:
            pages_mod.upload_bytes = orig

        async def _is_guest_ownerless(image_id: str):
            async with SessionLocal() as s:
                row = await s.get(Image, image_id)
                return row.owner_id is None and row.source == "guest"

        assert asyncio.run(_is_guest_ownerless(body["id"]))

        # upload page lists recent uploads
        assert body["id"] in client.get("/upload").text

    print("WEB_PORTAL_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
