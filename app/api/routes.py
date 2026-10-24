from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import current_tg_user, current_user
from app.database.models import User
from app.database.session import SessionLocal
from app.services import accounts as accounts_service
from app.services.users import accept_terms, get_or_create_user
from app.telegram_client.runtime import login_manager, make_client

router = APIRouter(prefix="/api")


class PhoneIn(BaseModel):
    phone: str = Field(max_length=32)


class CodeIn(BaseModel):
    code: str = Field(max_length=16)


class PasswordIn(BaseModel):
    password: str = Field(max_length=256)


def _account_json(a) -> dict:
    return {
        "id": a.id,
        "display_name": a.display_name,
        "username": a.username,
        "status": a.auth_status,
        "connected_at": a.connected_at.isoformat() if a.connected_at else None,
    }


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
        "terms_accepted": user.terms_accepted_at is not None,
    }


@router.post("/consent")
async def consent(user: User = Depends(current_user)) -> dict:
    async with SessionLocal() as session:
        await accept_terms(session, user.id)
    return {"status": "accepted"}


@router.get("/accounts")
async def list_my_accounts(user: User = Depends(current_user)) -> dict:
    async with SessionLocal() as session:
        items = await accounts_service.list_accounts(session, user.id)
    return {"accounts": [_account_json(a) for a in items]}


@router.post("/accounts/login/start")
async def login_start(body: PhoneIn, user: User = Depends(current_user)) -> dict:
    if user.terms_accepted_at is None:
        raise accounts_service.AccountError(
            "consent_required", "Сначала подтвердите согласие на использование аккаунта."
        )
    async with SessionLocal() as session:
        await accounts_service.ensure_can_connect(session, user.id)
    result = await login_manager.start(user.id, body.phone)
    return {"status": "code_sent", "expires_in": result.expires_in, "delivery": result.delivery}


@router.post("/accounts/login/code")
async def login_code(body: CodeIn, user: User = Depends(current_user)) -> dict:
    outcome = await login_manager.submit_code(user.id, body.code)
    return await _outcome_response(user, outcome)


@router.post("/accounts/login/password")
async def login_password(body: PasswordIn, user: User = Depends(current_user)) -> dict:
    outcome = await login_manager.submit_password(user.id, body.password)
    return await _outcome_response(user, outcome)


@router.post("/accounts/login/cancel")
async def login_cancel(user: User = Depends(current_user)) -> dict:
    await login_manager.cancel(user.id)
    return {"status": "cancelled"}


@router.delete("/accounts/{account_id}")
async def disconnect(account_id: int, user: User = Depends(current_user)) -> dict:
    async with SessionLocal() as session:
        removed = await accounts_service.disconnect_account(
            session, user.id, account_id, make_client
        )
    if not removed:
        raise accounts_service.AccountError("not_found", "Аккаунт не найден.")
    return {"status": "disconnected"}


async def _revoke_remote(session_string: str) -> None:
    """Log out a freshly created session that we failed to store (no orphans)."""
    client = make_client(session_string)
    try:
        await client.connect()
        await client.log_out()
    except Exception:
        pass
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def _outcome_response(user: User, outcome) -> dict:
    if outcome.status == "password_needed":
        return {"status": "password_needed"}
    try:
        async with SessionLocal() as session:
            account = await accounts_service.save_account(session, user.id, outcome.session)
    except Exception:
        await _revoke_remote(outcome.session.session_string)
        raise
    return {"status": "connected", "account": _account_json(account)}
