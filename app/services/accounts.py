import logging
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import AuditEvent, TelegramAccount
from app.security.crypto import CryptoError, get_cipher, session_aad
from app.telegram_client.auth import AuthorizedSession

logger = logging.getLogger("app.accounts")


class AccountError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code = code
        self.message = message


async def count_accounts(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(TelegramAccount).where(TelegramAccount.user_id == user_id)
    )
    return int(result.scalar_one())


async def ensure_can_connect(session: AsyncSession, user_id: int) -> None:
    if await count_accounts(session, user_id) >= settings.max_accounts_per_user:
        raise AccountError(
            "limit_reached",
            "Достигнут лимит подключённых аккаунтов. Сначала отключите текущий.",
        )


async def list_accounts(session: AsyncSession, user_id: int) -> list[TelegramAccount]:
    result = await session.execute(
        select(TelegramAccount)
        .where(TelegramAccount.user_id == user_id)
        .order_by(TelegramAccount.id)
    )
    return list(result.scalars())


async def save_account(
    session: AsyncSession, user_id: int, authorized: AuthorizedSession
) -> TelegramAccount:
    cipher = get_cipher()
    blob, version = cipher.encrypt(authorized.session_string, session_aad(user_id))

    existing = (
        await session.execute(
            select(TelegramAccount).where(TelegramAccount.tg_account_id == authorized.tg_account_id)
        )
    ).scalar_one_or_none()

    if existing is not None and existing.user_id != user_id:
        raise AccountError("account_taken", "Этот аккаунт Telegram уже подключён к другому пользователю сервиса.")

    if existing is not None:
        existing.session_enc = blob
        existing.key_version = version
        existing.auth_status = "active"
        existing.display_name = authorized.display_name
        existing.username = authorized.username
        account = existing
    else:
        await ensure_can_connect(session, user_id)
        account = TelegramAccount(
            user_id=user_id,
            tg_account_id=authorized.tg_account_id,
            display_name=authorized.display_name,
            username=authorized.username,
            session_enc=blob,
            key_version=version,
            auth_status="active",
        )
        session.add(account)
    session.add(AuditEvent(user_id=user_id, event_type="account_connected", meta={"tg_account_id": authorized.tg_account_id}))
    await session.commit()
    return account


async def disconnect_account(
    session: AsyncSession,
    user_id: int,
    account_id: int,
    client_factory: Callable[[str], Any],
) -> bool:
    """Log the session out on Telegram's side and delete it. Owner-checked."""
    account = (
        await session.execute(
            select(TelegramAccount).where(
                TelegramAccount.id == account_id, TelegramAccount.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if account is None:
        return False

    remote_logout = False
    client = None
    try:
        session_string = get_cipher().decrypt(
            account.session_enc, account.key_version, session_aad(user_id)
        )
        client = client_factory(session_string)
        await client.connect()
        await client.log_out()
        remote_logout = True
    except CryptoError:
        logger.error("stored session cannot be decrypted; deleting it anyway")
    except Exception as e:
        # Session may already be revoked by the user; local deletion still proceeds.
        logger.warning("remote logout failed: %s", type(e).__name__)
    finally:
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    tg_account_id = account.tg_account_id
    await session.delete(account)
    session.add(
        AuditEvent(
            user_id=user_id,
            event_type="account_disconnected",
            meta={"tg_account_id": tg_account_id, "remote_logout": remote_logout},
        )
    )
    await session.commit()
    return True
