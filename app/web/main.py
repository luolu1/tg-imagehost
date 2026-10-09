from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import SessionLocal, init_db
from app.telegram_files import close_bot
from app.web import admin, api, pages, user_portal
from app.web.auth import ensure_admin_seeded

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with SessionLocal() as session:
        await ensure_admin_seeded(session)
    log.info("Web app ready. pages=%s images=%s", settings.web_base, settings.image_base)
    yield
    await close_bot()


app = FastAPI(title="TG Image Host", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api.router)
app.include_router(pages.router)
app.include_router(user_portal.router)
app.include_router(admin.router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"ok": True}
