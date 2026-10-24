import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import settings
from app.database.session import check_db
from app.services.accounts import AccountError
from app.telegram_client.auth import LoginError
from app.telegram_client.runtime import login_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")


def _log_bot_task_result(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        # Log only the exception type: never risk printing secrets.
        logger.error("bot polling stopped: %s", type(exc).__name__)


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            await login_manager.cleanup_expired()
        except Exception as e:
            logger.error("login cleanup failed: %s", type(e).__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = None
    bot = None
    cleanup_task = asyncio.create_task(_cleanup_loop())
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
        cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await cleanup_task
        await login_manager.shutdown()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if bot is not None:
            await bot.session.close()


app = FastAPI(title="TG Autopost", lifespan=lifespan)
app.include_router(api_router)


@app.exception_handler(LoginError)
async def login_error_handler(_: Request, exc: LoginError):
    status = 429 if exc.code in ("too_many_attempts", "flood_wait") else 400
    return JSONResponse(
        {"error": exc.code, "message": exc.message, "retry_after": exc.retry_after},
        status_code=status,
    )


@app.exception_handler(AccountError)
async def account_error_handler(_: Request, exc: AccountError):
    status = {"not_found": 404, "consent_required": 403}.get(exc.code, 409)
    return JSONResponse({"error": exc.code, "message": exc.message}, status_code=status)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError):
    # Do not echo the submitted input back: it may contain a login code or password.
    return JSONResponse({"error": "bad_request", "message": "Некорректный запрос."}, status_code=422)


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
