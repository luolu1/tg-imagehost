"""Live end-to-end check against the running web server + real Telegram storage.

Uploads a generated PNG, fetches it back through /i/<id>, then cleans up
(channel message, DB row, cache file). Run: python -m scripts.verify_e2e
"""

import asyncio
import io
import sys

import httpx
from PIL import Image as PILImage

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Image, User
from app.services import ensure_api_token, get_or_create_user
from app.telegram_files import get_bot

BASE = "http://127.0.0.1:8080"
ADMIN_ID = 7122485076


async def main() -> int:
    await init_db()
    async with SessionLocal() as session:
        user = await get_or_create_user(session, ADMIN_ID, None, "Admin")
        token = await ensure_api_token(session, user)

    buf = io.BytesIO()
    PILImage.new("RGB", (80, 60), (79, 140, 255)).save(buf, format="PNG")
    png = buf.getvalue()

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{BASE}/api/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("e2e_test.png", png, "image/png")},
        )
        r.raise_for_status()
        data = r.json()
        print("upload :", data["id"], f"{data['size']}B", f"{data['width']}x{data['height']}")

        served = await client.get(data["url"])
        print("serve  :", served.status_code, served.headers.get("content-type"), f"{len(served.content)}B")
        assert served.status_code == 200, served.text
        assert served.content[:8] == b"\x89PNG\r\n\x1a\n", "served content is not a PNG"

    async with SessionLocal() as session:
        row = await session.get(Image, data["id"])
        chat_id, message_id, owner_id, size = (
            row.storage_chat_id,
            row.storage_message_id,
            row.owner_id,
            row.file_size,
        )
        await session.delete(row)
        if owner_id is not None:
            owner = await session.get(User, owner_id)
            if owner is not None:
                owner.upload_count = max(0, owner.upload_count - 1)
                owner.total_size = max(0, owner.total_size - size)
        await session.commit()

    bot = get_bot()
    if chat_id and message_id:
        try:
            await bot.delete_message(chat_id, message_id)
            print("cleanup: channel message deleted")
        except Exception as exc:  # noqa: BLE001
            print("cleanup warn:", exc)
    await bot.session.close()

    for path in settings.cache_path.glob(f"{data['id']}.*"):
        path.unlink(missing_ok=True)

    print("E2E_OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
