from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User


async def get_or_create_user(
    session: AsyncSession, tg_id: int, language_code: str | None
) -> User:
    """Register a user on first contact; safe to call concurrently."""
    language = (language_code or "ru")[:8]
    stmt = (
        pg_insert(User)
        .values(tg_id=tg_id, language=language, status="active")
        .on_conflict_do_nothing(index_elements=[User.tg_id])
    )
    await session.execute(stmt)
    await session.commit()
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one()
