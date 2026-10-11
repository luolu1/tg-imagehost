from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import SessionLocal, init_db
from app.telegram_files import close_bot
from app.web import admin, api, pages, user_portal
from app.web.user_auth import is_admin_user, resolve_web_user

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("Web app ready. pages=%s images=%s", settings.web_base, settings.image_base)
    yield
    await close_bot()


app = FastAPI(title="TG Image Host", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def attach_current_user(request: Request, call_next):
    """Resolve the portal cookie once per request so templates can show the
    right navigation (user center vs admin) without each route re-querying."""
    request.state.site_name = settings.site_name
    request.state.me = None
    request.state.is_admin = False
    if request.cookies.get("tg_portal_token"):
        async with SessionLocal() as session:
            user = await resolve_web_user(request, session)
        request.state.me = user
        request.state.is_admin = is_admin_user(user)
    return await call_next(request)


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
