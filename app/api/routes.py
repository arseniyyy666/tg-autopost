from fastapi import APIRouter, Depends

from app.api.deps import current_tg_user
from app.database.session import SessionLocal
from app.services.users import get_or_create_user

router = APIRouter(prefix="/api")


@router.get("/me")
async def me(tg_user: dict = Depends(current_tg_user)) -> dict:
    async with SessionLocal() as session:
        user = await get_or_create_user(session, tg_user["id"], tg_user.get("language_code"))
    return {
        "id": user.id,
        "tg_id": user.tg_id,
        "first_name": tg_user.get("first_name", ""),
        "language": user.language,
        "registered_at": user.created_at.isoformat(),
    }
