"""FastAPI application entry point for Concierge."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import config
from .memory import _ensure_dirs
from .routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Concierge API...")
    _ensure_dirs()
    logger.info(f"Data dir: {config.data_dir}")
    logger.info("Concierge API ready")
    yield
    logger.info("Concierge API shutting down")


app = FastAPI(
    title="Moncey Concierge",
    description="Monce AI extraction memory & intelligence layer",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Static files + landing page
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", include_in_schema=False)
async def landing_page():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Concierge API", "docs": "/docs", "chat": "/ui"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host=config.api_host, port=config.api_port, reload=True)
