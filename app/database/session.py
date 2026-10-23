from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings


def prepare_url(raw: str) -> tuple[str, dict]:
    """Convert a standard postgres URL into an asyncpg-compatible one.

    Neon/Railway give `postgresql://...?sslmode=require`; asyncpg needs the
    `postgresql+asyncpg` scheme and an `ssl` connect argument instead.
    """
    parts = urlsplit(raw)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"

    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)

    connect_args: dict = {}
    if sslmode in ("require", "verify-ca", "verify-full"):
        connect_args["ssl"] = True

    url = urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return url, connect_args


_url, _connect_args = prepare_url(settings.database_url)

engine = create_async_engine(_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def check_db() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
