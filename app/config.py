from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: str
    storage_chat_id: int | None = None
    admin_ids: str = ""

    # Web / URLs
    # 有域名时（如走 Nginx 反代），填写完整地址：
    #   web_base_url   —— 页面访问地址（上传页 / 详情页 / 管理后台）
    #   image_base_url —— 图片直链地址
    # 没有域名时两者留空，会用 public_host + web_port 自动拼出 http://host:port
    web_base_url: str | None = None
    image_base_url: str | None = None
    public_host: str = "localhost"
    web_host: str = "0.0.0.0"
    web_port: int = 8080

    # Storage / DB
    database_url: str = "sqlite+aiosqlite:///./data/imagehost.db"
    cache_dir: str = "./data/cache"
    cache_max_mb: int = 2048

    # Limits
    max_upload_mb: int = 20
    default_quota_mb: int = 0
    group_process_all: bool = False

    @field_validator("web_base_url", "image_base_url")
    @classmethod
    def _strip_slash(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v.rstrip("/") or None

    @field_validator("storage_chat_id", mode="before")
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @property
    def admin_id_set(self) -> set[int]:
        ids: set[int] = set()
        for part in self.admin_ids.split(","):
            part = part.strip()
            if part:
                ids.add(int(part))
        return ids

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def quota_bytes(self) -> int:
        return self.default_quota_mb * 1024 * 1024

    @property
    def cache_path(self) -> Path:
        p = Path(self.cache_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def host_base(self) -> str:
        """Fallback base derived from public host + port (no domain case)."""
        host = self.public_host.strip() or "localhost"
        return f"http://{host}:{self.web_port}"

    @property
    def web_base(self) -> str:
        """Base used for page links (upload / view / admin)."""
        return self.web_base_url or self.host_base

    @property
    def image_base(self) -> str:
        """Base used for direct image links."""
        return self.image_base_url or self.web_base

    def image_url(self, image_id: str, ext: str | None = None) -> str:
        suffix = f".{ext}" if ext else ""
        return f"{self.image_base}/i/{image_id}{suffix}"

    def view_url(self, image_id: str) -> str:
        return f"{self.web_base}/v/{image_id}"

    def upload_url(self) -> str:
        return f"{self.web_base}/upload"

    def portal_url(self) -> str:
        return f"{self.web_base}/my"

    def admin_url(self) -> str:
        return f"{self.web_base}/admin"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
