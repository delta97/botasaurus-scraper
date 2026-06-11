"""FastAPI app. Run from the repo root so Botasaurus's relative-path artifacts
(output/, cache/, error_logs/) land in gitignored directories:

    uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, db
from .routers import extension, models_proxy, recipes, runs, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    orphans = db.fail_orphaned_runs()
    if orphans:
        print(f"marked {orphans} orphaned run(s) as failed")
    yield


app = FastAPI(title="Botasaurus Automation Studio", lifespan=lifespan)

# Scoped to the Chrome extension origin only — never "*", which would let any
# website POST to the localhost server. Writes are additionally token-gated.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://.*",
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Studio-Token"],
    allow_credentials=False,
)

app.include_router(settings.router)
app.include_router(models_proxy.router)
app.include_router(runs.router)
app.include_router(recipes.router)
app.include_router(extension.router)


@app.get("/api/health")
def health():
    chrome = config.find_chrome()
    return {
        "ok": True,
        "chrome_found": bool(chrome),
        "chrome_path": chrome,
        "db_path": str(config.DB_PATH),
    }


if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIST), html=True), name="frontend")
