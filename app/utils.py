from __future__ import annotations

import secrets
import string

_ALPHABET = string.ascii_letters + string.digits


def gen_id(length: int = 10) -> str:
    """URL-safe short id."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def gen_token() -> str:
    return secrets.token_urlsafe(24)


def human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{num} B"


def escape_md(text: str) -> str:
    """Escape for legacy Markdown parse mode."""
    for ch in ("_", "*", "[", "]", "`"):
        text = text.replace(ch, f"\\{ch}")
    return text


def image_dimensions(data: bytes) -> tuple[int | None, int | None]:
    """Best-effort width/height for an image byte stream."""
    try:
        import io

        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(data)) as im:
            return im.width, im.height
    except Exception:  # noqa: BLE001 - not fatal for non-image or exotic formats
        return None, None
