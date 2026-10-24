from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config import settings
from app.telegram_client.auth import LoginManager


def make_client(session_string: str = "") -> TelegramClient:
    # device_model is what the user sees in Telegram -> Settings -> Devices.
    return TelegramClient(
        StringSession(session_string),
        settings.api_id,
        settings.api_hash,
        device_model="TG Autopost",
        app_version="1.0",
        receive_updates=False,
    )


login_manager = LoginManager(
    client_factory=make_client,
    ttl=settings.login_ttl_seconds,
    max_code_attempts=settings.login_max_code_attempts,
    max_password_attempts=settings.login_max_password_attempts,
    max_starts=settings.login_max_starts,
    start_window=settings.login_start_window_seconds,
)
