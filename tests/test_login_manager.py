import asyncio
from types import SimpleNamespace

import pytest
from telethon import errors

from app.telegram_client.auth import LoginError, LoginManager, delivery_kind


class FakeClient:
    def __init__(self, script=None):
        self.script = script or {}
        self.connected = False
        self.disconnected = False
        self.session = SimpleNamespace(save=lambda: "SESSION-STRING")

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.disconnected = True

    async def send_code_request(self, phone):
        exc = self.script.get("send")
        if exc:
            raise exc
        return SimpleNamespace(phone_code_hash="HASH")

    async def sign_in(self, phone=None, code=None, password=None, phone_code_hash=None):
        key = "password" if password is not None else "code"
        queue = self.script.get(key, [])
        if queue:
            action = queue.pop(0)
            if isinstance(action, Exception):
                raise action
        return None

    async def get_me(self):
        return SimpleNamespace(id=555, first_name="Ann", last_name="Lee", username="ann")


def make(script=None, **kw):
    clients = []

    def factory():
        c = FakeClient(script)
        clients.append(c)
        return c

    params = dict(ttl=600, max_code_attempts=3, max_password_attempts=2, max_starts=3, start_window=600)
    params.update(kw)
    return LoginManager(factory, **params), clients


def run(coro):
    return asyncio.run(coro)


def test_happy_path_without_2fa():
    async def go():
        m, clients = make()
        await m.start(1, "+351 912-345-678")
        out = await m.submit_code(1, "12345")
        assert out.status == "connected"
        assert out.session.tg_account_id == 555
        assert out.session.display_name == "Ann Lee"
        assert clients[0].disconnected
        with pytest.raises(LoginError) as e:  # state is gone after success
            await m.submit_code(1, "12345")
        assert e.value.code == "no_login"
    run(go())


def test_two_factor_path():
    async def go():
        m, _ = make({"code": [errors.SessionPasswordNeededError(None)]})
        await m.start(1, "+351912345678")
        assert (await m.submit_code(1, "12345")).status == "password_needed"
        out = await m.submit_password(1, "pw")
        assert out.status == "connected" and out.session.session_string == "SESSION-STRING"
    run(go())


def test_code_attempt_limit_drops_login():
    async def go():
        m, clients = make({"code": [errors.PhoneCodeInvalidError(None)] * 5}, max_code_attempts=3)
        await m.start(1, "+351912345678")
        for _ in range(3):
            with pytest.raises(LoginError) as e:
                await m.submit_code(1, "11111")
            assert e.value.code == "code_invalid"
        with pytest.raises(LoginError) as e:
            await m.submit_code(1, "11111")
        assert e.value.code == "too_many_attempts"
        assert clients[0].disconnected
    run(go())


def test_wrong_password_limit():
    async def go():
        m, _ = make({"code": [errors.SessionPasswordNeededError(None)],
                     "password": [errors.PasswordHashInvalidError(None)] * 3}, max_password_attempts=2)
        await m.start(1, "+351912345678")
        await m.submit_code(1, "12345")
        for _ in range(2):
            with pytest.raises(LoginError) as e:
                await m.submit_password(1, "bad")
            assert e.value.code == "password_invalid"
        with pytest.raises(LoginError) as e:
            await m.submit_password(1, "bad")
        assert e.value.code == "too_many_attempts"
    run(go())


def test_expired_login_is_rejected_and_cleaned():
    async def go():
        m, clients = make(ttl=0)
        await m.start(1, "+351912345678")
        await asyncio.sleep(0.01)
        with pytest.raises(LoginError) as e:
            await m.submit_code(1, "12345")
        assert e.value.code == "no_login"
        await m.cleanup_expired()
        assert clients[0].disconnected
    run(go())


def test_start_rate_limit():
    async def go():
        m, _ = make(max_starts=2)
        await m.start(1, "+351912345678")
        await m.start(1, "+351912345678")
        with pytest.raises(LoginError) as e:
            await m.start(1, "+351912345678")
        assert e.value.code == "too_many_attempts" and e.value.retry_after
        await m.start(2, "+351912345678")  # other user is not affected
    run(go())


def test_new_start_replaces_previous_pending():
    async def go():
        m, clients = make()
        await m.start(1, "+351912345678")
        await m.start(1, "+351912345678")
        assert clients[0].disconnected and not clients[1].disconnected
    run(go())


def test_logins_are_isolated_between_users():
    async def go():
        m, _ = make()
        await m.start(1, "+351912345678")
        with pytest.raises(LoginError) as e:
            await m.submit_code(2, "12345")
        assert e.value.code == "no_login"
    run(go())


@pytest.mark.parametrize("phone", ["", "123", "abc", "+12", "++351912345678"])
def test_bad_phone(phone):
    async def go():
        m, _ = make()
        with pytest.raises(LoginError) as e:
            await m.start(1, phone)
        assert e.value.code == "phone_invalid"
    run(go())


def test_flood_wait_reports_retry_after_and_disconnects():
    async def go():
        m, clients = make({"send": errors.FloodWaitError(None, capture=42)})
        with pytest.raises(LoginError) as e:
            await m.start(1, "+351912345678")
        assert e.value.code == "flood_wait" and e.value.retry_after == 42
        assert clients[0].disconnected
    run(go())


def test_code_format_is_validated_without_burning_telegram_call():
    async def go():
        m, _ = make()
        await m.start(1, "+351912345678")
        with pytest.raises(LoginError) as e:
            await m.submit_code(1, "abc")
        assert e.value.code == "code_invalid"
    run(go())


def test_start_reports_delivery_kind():
    class SentCodeTypeApp: ...
    class SentCodeTypeSms: ...

    class C(FakeClient):
        kind = SentCodeTypeApp

        async def send_code_request(self, phone):
            return SimpleNamespace(phone_code_hash="H", type=self.kind())

    async def go():
        m = LoginManager(lambda: C(), 600, 3, 2, 3, 600)
        assert (await m.start(1, "+351912345678")).delivery == "app"
        C.kind = SentCodeTypeSms
        assert (await m.start(1, "+351912345678")).delivery == "sms"

    run(go())
    assert delivery_kind(None) == "other"
