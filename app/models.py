from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram user id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    api_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    upload_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # Per-user quota in bytes. None means "inherit DEFAULT_QUOTA_MB from .env".
    quota_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Image(Base):
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), index=True, nullable=True
    )
    file_id: Mapped[str] = mapped_column(String(256), nullable=False)
    file_unique_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    thumb_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="telegram", nullable=False)
    storage_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    storage_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def ext(self) -> str:
        if self.file_name and "." in self.file_name:
            ext = self.file_name.rsplit(".", 1)[1].lower()
            if 1 <= len(ext) <= 8 and ext.isalnum():
                return ext
        if self.mime_type and "/" in self.mime_type:
            sub = self.mime_type.split("/", 1)[1].lower()
            mapping = {"jpeg": "jpg", "svg+xml": "svg"}
            sub = mapping.get(sub, sub)
            if sub.isalnum() and len(sub) <= 8:
                return sub
        return "jpg"


class Setting(Base):
    """Runtime-editable key/value settings (admin credentials, etc.)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
