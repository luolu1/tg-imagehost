from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Image
from app.services import NewImage, create_image
from app.telegram_files import store_bytes
from app.utils import image_dimensions

log = logging.getLogger(__name__)


class UploadError(Exception):
    pass


async def upload_bytes(
    session: AsyncSession,
    *,
    owner_id: int | None,
    filename: str,
    mime_type: str | None,
    data: bytes,
    source: str = "web",
) -> Image:
    """Push bytes to the Telegram storage chat and persist an Image row."""
    if not data:
        raise UploadError("空文件")
    if len(data) > settings.max_upload_bytes:
        raise UploadError(f"文件过大，上限 {settings.max_upload_mb} MB")
    if not filename:
        filename = "upload"

    try:
        chat_id, message = await store_bytes(data, filename, mime_type)
    except RuntimeError as exc:
        raise UploadError(str(exc)) from exc

    doc = message.document  # type: ignore[attr-defined]
    if doc is None:
        raise UploadError("存储失败：Telegram 未返回文件信息")

    width, height = image_dimensions(data)

    return await create_image(
        session,
        NewImage(
            file_id=doc.file_id,
            file_unique_id=doc.file_unique_id,
            thumb_file_id=doc.thumbnail.file_id if doc.thumbnail else None,
            file_name=doc.file_name or filename,
            mime_type=doc.mime_type or mime_type,
            file_size=doc.file_size or len(data),
            width=width,
            height=height,
            source=source,
            storage_chat_id=chat_id,
            storage_message_id=message.message_id,  # type: ignore[attr-defined]
            owner_id=owner_id,
        ),
    )
