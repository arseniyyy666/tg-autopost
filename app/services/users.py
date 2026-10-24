from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditEvent, User


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


async def accept_terms(session: AsyncSession, user_id: int) -> None:
    """Record (once) that the user accepted how their connected account is used."""
    result = await session.execute(
        update(User)
        .where(User.id == user_id, User.terms_accepted_at.is_(None))
        .values(terms_accepted_at=func.now())
    )
    if result.rowcount:
        session.add(AuditEvent(user_id=user_id, event_type="terms_accepted"))
    await session.commit()
