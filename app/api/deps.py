from fastapi import Header, HTTPException

from app.config import settings
from app.security.telegram_auth import InitDataError, validate_init_data


async def current_tg_user(authorization: str = Header(default="")) -> dict:
    """Authenticate a Mini App request via `Authorization: tma <initData>`."""
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "tma" or not value:
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        return validate_init_data(value, settings.bot_token, settings.initdata_max_age)
    except InitDataError:
        raise HTTPException(status_code=401, detail="unauthorized") from None
