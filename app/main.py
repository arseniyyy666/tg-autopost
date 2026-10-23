import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.database.session import check_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

app = FastAPI(title="TG Autopost")


@app.get("/health/live")
async def live() -> dict:
    return {"status": "ok"}


@app.get("/health")
async def health():
    try:
        await check_db()
    except Exception:
        # Never leak connection details to the client or logs.
        logger.error("database check failed")
        return JSONResponse({"status": "error", "db": "down"}, status_code=503)
    return {"status": "ok", "db": "up"}
