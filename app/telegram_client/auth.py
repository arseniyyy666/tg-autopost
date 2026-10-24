"""Interactive Telegram login (phone -> code -> optional 2FA password).

Pending logins live only in memory (they hold a live MTProto connection), have a
short lifetime, limited attempts, and at most one per service user. Codes and
passwords are passed straight to Telegram and are never stored or logged.
"""
import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from telethon import errors

logger = logging.getLogger("app.login")

PHONE_RE = re.compile(r"^\+\d{7,15}$")
CODE_RE = re.compile(r"^\d{4,8}$")


class LoginError(Exception):
    def __init__(self, code: str, message: str, retry_after: int | None = None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass
class StartResult:
    expires_in: int
    delivery: str  # "app" | "sms" | "call" | "email" | "other"


def delivery_kind(sent_type: Any) -> str:
    """Where Telegram says it delivered the login code (for a helpful hint)."""
    name = type(sent_type).__name__ if sent_type is not None else ""
    if name == "SentCodeTypeApp":
        return "app"
    if name in ("SentCodeTypeSms", "SentCodeTypeSmsWord", "SentCodeTypeSmsPhrase"):
        return "sms"
    if name in ("SentCodeTypeCall", "SentCodeTypeFlashCall", "SentCodeTypeMissedCall"):
        return "call"
    if name == "SentCodeTypeEmailCode":
        return "email"
    return "other"


@dataclass
class AuthorizedSession:
    tg_account_id: int
    display_name: str
    username: str | None
    session_string: str = field(repr=False)  # secret: never log


@dataclass
class LoginOutcome:
    status: str  # "password_needed" | "connected"
    session: AuthorizedSession | None = None


@dataclass
class _Pending:
    client: Any
    phone: str = field(repr=False)
    phone_code_hash: str = field(repr=False)
    expires_at: float
    state: str = "code"
    code_attempts: int = 0
    password_attempts: int = 0


def normalize_phone(raw: str) -> str:
    phone = re.sub(r"[\s\-()]", "", raw or "")
    if not PHONE_RE.match(phone):
        raise LoginError("phone_invalid", "Введите номер в международном формате, например +351912345678.")
    return phone


class LoginManager:
    def __init__(
        self,
        client_factory: Callable[[], Any],
        ttl: int,
        max_code_attempts: int,
        max_password_attempts: int,
        max_starts: int,
        start_window: int,
    ):
        self._factory = client_factory
        self._ttl = ttl
        self._max_code = max_code_attempts
        self._max_password = max_password_attempts
        self._max_starts = max_starts
        self._start_window = start_window
        self._pending: dict[int, _Pending] = {}
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._starts: dict[int, deque[float]] = defaultdict(deque)

    # ---- helpers -------------------------------------------------------
    @staticmethod
    async def _safe_disconnect(client: Any) -> None:
        try:
            await client.disconnect()
        except Exception:
            pass

    async def _drop(self, user_id: int) -> None:
        pending = self._pending.pop(user_id, None)
        if pending is not None:
            await self._safe_disconnect(pending.client)

    def _get_pending(self, user_id: int, state: str) -> _Pending:
        pending = self._pending.get(user_id)
        if pending is None or pending.expires_at < time.monotonic():
            raise LoginError("no_login", "Сеанс входа истёк. Начните подключение заново.")
        if pending.state != state:
            raise LoginError("wrong_step", "Неверный шаг входа. Начните подключение заново.")
        return pending

    # ---- public API ----------------------------------------------------
    async def start(self, user_id: int, raw_phone: str) -> StartResult:
        phone = normalize_phone(raw_phone)
        async with self._locks[user_id]:
            now = time.monotonic()
            starts = self._starts[user_id]
            while starts and now - starts[0] > self._start_window:
                starts.popleft()
            if len(starts) >= self._max_starts:
                wait = int(self._start_window - (now - starts[0]))
                raise LoginError(
                    "too_many_attempts",
                    "Слишком много попыток входа. Попробуйте позже.",
                    retry_after=max(wait, 1),
                )
            starts.append(now)

            await self._drop(user_id)
            client = self._factory()
            try:
                await client.connect()
                sent = await client.send_code_request(phone)
            except errors.FloodWaitError as e:
                await self._safe_disconnect(client)
                raise LoginError(
                    "flood_wait",
                    "Telegram временно ограничил запрос кода. Подождите и попробуйте снова.",
                    retry_after=int(getattr(e, "seconds", 0)) or None,
                ) from None
            except (errors.PhoneNumberInvalidError, errors.PhoneNumberBannedError,
                    errors.PhoneNumberFloodError) as e:
                await self._safe_disconnect(client)
                if isinstance(e, errors.PhoneNumberBannedError):
                    raise LoginError("phone_banned", "Этот номер заблокирован в Telegram.") from None
                if isinstance(e, errors.PhoneNumberFloodError):
                    raise LoginError("flood_wait", "Для этого номера слишком много запросов кода. Попробуйте позже.") from None
                raise LoginError("phone_invalid", "Номер не принят Telegram. Проверьте формат.") from None
            except errors.ApiIdInvalidError:
                await self._safe_disconnect(client)
                logger.error("API_ID/API_HASH rejected by Telegram")
                raise LoginError("server_config", "Сервис настроен неверно. Сообщите администратору.") from None
            except Exception as e:
                await self._safe_disconnect(client)
                logger.error("send_code failed: %s", type(e).__name__)
                raise LoginError("telegram_error", "Не удалось связаться с Telegram. Попробуйте позже.") from None

            delivery = delivery_kind(getattr(sent, "type", None))
            logger.info("login code requested, delivery=%s", delivery)
            self._pending[user_id] = _Pending(
                client=client,
                phone=phone,
                phone_code_hash=sent.phone_code_hash,
                expires_at=now + self._ttl,
            )
            return StartResult(expires_in=self._ttl, delivery=delivery)

    async def submit_code(self, user_id: int, raw_code: str) -> LoginOutcome:
        code = (raw_code or "").strip().replace(" ", "")
        async with self._locks[user_id]:
            pending = self._get_pending(user_id, "code")
            if not CODE_RE.match(code):
                raise LoginError("code_invalid", "Код состоит из цифр. Проверьте и введите снова.")
            pending.code_attempts += 1
            if pending.code_attempts > self._max_code:
                await self._drop(user_id)
                raise LoginError("too_many_attempts", "Слишком много неверных кодов. Начните заново.")
            try:
                await pending.client.sign_in(
                    phone=pending.phone, code=code, phone_code_hash=pending.phone_code_hash
                )
            except errors.SessionPasswordNeededError:
                pending.state = "password"
                return LoginOutcome(status="password_needed")
            except errors.PhoneCodeInvalidError:
                raise LoginError("code_invalid", "Неверный код. Проверьте и введите снова.") from None
            except (errors.PhoneCodeExpiredError, errors.PhoneCodeEmptyError):
                await self._drop(user_id)
                raise LoginError("code_expired", "Код устарел. Запросите новый.") from None
            except errors.FloodWaitError as e:
                await self._drop(user_id)
                raise LoginError("flood_wait", "Telegram ограничил попытки. Подождите.",
                                 retry_after=int(getattr(e, "seconds", 0)) or None) from None
            except Exception as e:
                await self._drop(user_id)
                logger.error("sign_in failed: %s", type(e).__name__)
                raise LoginError("telegram_error", "Не удалось войти. Начните заново.") from None
            return await self._finish(user_id, pending)

    async def submit_password(self, user_id: int, password: str) -> LoginOutcome:
        async with self._locks[user_id]:
            pending = self._get_pending(user_id, "password")
            if not password:
                raise LoginError("password_invalid", "Введите пароль двухэтапной проверки.")
            pending.password_attempts += 1
            if pending.password_attempts > self._max_password:
                await self._drop(user_id)
                raise LoginError("too_many_attempts", "Слишком много неверных паролей. Начните заново.")
            try:
                await pending.client.sign_in(password=password)
            except errors.PasswordHashInvalidError:
                raise LoginError("password_invalid", "Неверный пароль. Попробуйте ещё раз.") from None
            except errors.FloodWaitError as e:
                await self._drop(user_id)
                raise LoginError("flood_wait", "Telegram ограничил попытки. Подождите.",
                                 retry_after=int(getattr(e, "seconds", 0)) or None) from None
            except Exception as e:
                await self._drop(user_id)
                logger.error("password sign_in failed: %s", type(e).__name__)
                raise LoginError("telegram_error", "Не удалось войти. Начните заново.") from None
            return await self._finish(user_id, pending)

    async def cancel(self, user_id: int) -> None:
        async with self._locks[user_id]:
            await self._drop(user_id)

    async def cleanup_expired(self) -> None:
        now = time.monotonic()
        for user_id in [u for u, p in self._pending.items() if p.expires_at < now]:
            async with self._locks[user_id]:
                pending = self._pending.get(user_id)
                if pending is not None and pending.expires_at < now:
                    await self._drop(user_id)

    async def shutdown(self) -> None:
        for user_id in list(self._pending):
            await self._drop(user_id)

    # ---- internals -----------------------------------------------------
    async def _finish(self, user_id: int, pending: _Pending) -> LoginOutcome:
        try:
            me = await pending.client.get_me()
            session_string = pending.client.session.save()
        except Exception as e:
            await self._drop(user_id)
            logger.error("finish failed: %s", type(e).__name__)
            raise LoginError("telegram_error", "Не удалось завершить вход. Начните заново.") from None
        name = " ".join(p for p in (getattr(me, "first_name", None), getattr(me, "last_name", None)) if p)
        authorized = AuthorizedSession(
            tg_account_id=me.id,
            display_name=(name or getattr(me, "username", None) or str(me.id))[:128],
            username=getattr(me, "username", None),
            session_string=session_string,
        )
        # Keep the remote session alive; only close our connection and forget the state.
        self._pending.pop(user_id, None)
        await self._safe_disconnect(pending.client)
        return LoginOutcome(status="connected", session=authorized)
