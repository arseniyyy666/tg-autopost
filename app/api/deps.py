from fastapi import Depends, Header, HTTPException

from app.config import settings
from app.database.models import User
from app.database.session import SessionLocal
from app.security.telegram_auth import InitDataError, validate_init_data
from app.services.users import get_or_create_user


async def current_tg_user(authorization: str = Header(default="")) -> dict:
    """Authenticate a Mini App request via `Authorization: tma <initData>`."""
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "tma" or not value:
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        return validate_init_data(value, settings.bot_token, settings.initdata_max_age)
    except InitDataError:
        raise HTTPException(status_code=401, detail="unauthorized") from None


async def current_user(tg_user: dict = Depends(current_tg_user)) -> User:
    async with SessionLocal() as session:
        user = await get_or_create_user(session, tg_user["id"], tg_user.get("language_code"))
    if user.status != "active":
        raise HTTPException(status_code=403, detail="blocked")
    return user
