import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import settings
from app.database.session import check_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")


def _log_bot_task_result(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        # Log only the exception type: never risk printing secrets.
        logger.error("bot polling stopped: %s", type(exc).__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = None
    bot = None
    if settings.webapp_url and not settings.webapp_url.startswith("https://"):
        logger.warning("WEBAPP_URL must start with https:// for Telegram Mini Apps")
    if settings.run_bot:
        from app.bot.setup import create_bot, create_dispatcher

        bot = create_bot()
        dp = create_dispatcher()
        task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
        task.add_done_callback(_log_bot_task_result)
        logger.info("bot polling started")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if bot is not None:
            await bot.session.close()


app = FastAPI(title="TG Autopost", lifespan=lifespan)
app.include_router(api_router)


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


app.mount(
    "/webapp",
    StaticFiles(directory=Path(__file__).parent / "webapp", html=True),
    name="webapp",
)
