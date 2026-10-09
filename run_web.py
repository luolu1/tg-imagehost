"""Entry point for the FastAPI web/API process."""

import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.web.main:app",
        host=settings.web_host,
        port=settings.web_port,
        reload=False,
    )
