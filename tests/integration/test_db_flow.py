"""End-to-end test against a REAL PostgreSQL.

WARNING: wipes the public schema of the database in DATABASE_URL.
Never point it at your real data. Skipped unless RUN_DB_TESTS=1.
"""
import asyncio
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DB_TESTS") != "1", reason="needs a throwaway DB")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.database.session import prepare_url  # noqa: E402
from tests.test_telegram_auth import make_init_data  # noqa: E402

TOKEN = "123456:TEST_TOKEN_FOR_TESTS"


class FakeClient:
    instances = []

    def __init__(self, account_id=555):
        self.account_id = account_id
        self.logged_out = False
        self.session = SimpleNamespace(save=lambda: "SECRET-SESSION-STRING")
        FakeClient.instances.append(self)

    async def connect(self): ...
    async def disconnect(self): ...
    async def send_code_request(self, phone): return SimpleNamespace(phone_code_hash="H")
    async def sign_in(self, **kw): return None
    async def get_me(self): return SimpleNamespace(id=self.account_id, first_name="Ann", last_name=None, username="ann")
    async def log_out(self): self.logged_out = True; return True


def sql(query, **params):
    from app.config import settings

    async def go():
        url, args = prepare_url(settings.database_url)
        engine = create_async_engine(url, poolclass=NullPool, connect_args=args)
        async with engine.begin() as conn:
            res = await conn.execute(text(query), params)
            rows = res.fetchall() if res.returns_rows else []
        await engine.dispose()
        return rows

    return asyncio.run(go())


def hdr(tg_id):
    return {"Authorization": "tma " + make_init_data(user_id=tg_id)}


@pytest.fixture(scope="module")
def client():
    sql("DROP SCHEMA public CASCADE")
    sql("CREATE SCHEMA public")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)

    from app.api import routes
    from app.telegram_client.runtime import login_manager

    login_manager._factory = lambda: FakeClient(555)
    routes.make_client = lambda session_string="": FakeClient(555)
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_full_flow(client):
    a, b = hdr(1001), hdr(1002)
    assert client.get("/api/me", headers=a).status_code == 200
    assert client.get("/api/me", headers=b).status_code == 200
    assert client.get("/api/accounts", headers=a).json() == {"accounts": []}

    # consent is required (and enforced by the backend) before any login
    r = client.post("/api/accounts/login/start", json={"phone": "+351912345678"}, headers=a)
    assert r.status_code == 403 and r.json()["error"] == "consent_required"
    assert client.get("/api/me", headers=a).json()["terms_accepted"] is False
    assert client.post("/api/consent", headers=a).status_code == 200
    assert client.post("/api/consent", headers=a).status_code == 200  # idempotent
    assert client.post("/api/consent", headers=b).status_code == 200
    assert client.get("/api/me", headers=a).json()["terms_accepted"] is True

    # A connects an account
    r = client.post("/api/accounts/login/start", json={"phone": "+351912345678"}, headers=a)
    assert r.status_code == 200 and r.json()["delivery"] == "other"
    r = client.post("/api/accounts/login/code", json={"code": "12345"}, headers=a)
    assert r.status_code == 200 and r.json()["status"] == "connected"
    acc_id = r.json()["account"]["id"]

    # session is stored encrypted, bound to its owner
    (row,) = sql("SELECT session_enc, key_version, user_id FROM telegram_accounts")
    assert b"SECRET-SESSION-STRING" not in bytes(row[0]) and row[1] == 1
    from app.security.crypto import get_cipher, session_aad

    assert get_cipher().decrypt(bytes(row[0]), row[1], session_aad(row[2])) == "SECRET-SESSION-STRING"

    # limit: a second connection is refused before any code is sent
    r = client.post("/api/accounts/login/start", json={"phone": "+351912345678"}, headers=a)
    assert r.status_code == 409 and r.json()["error"] == "limit_reached"

    # B sees nothing of A and cannot disconnect A's account
    assert client.get("/api/accounts", headers=b).json() == {"accounts": []}
    assert client.delete(f"/api/accounts/{acc_id}", headers=b).status_code == 404
    assert sql("SELECT count(*) FROM telegram_accounts")[0][0] == 1

    # B tries to connect the same Telegram account: refused and the new session is revoked remotely
    before = len(FakeClient.instances)
    assert client.post("/api/accounts/login/start", json={"phone": "+351912345678"}, headers=b).status_code == 200
    r = client.post("/api/accounts/login/code", json={"code": "12345"}, headers=b)
    assert r.status_code == 409 and r.json()["error"] == "account_taken"
    assert any(c.logged_out for c in FakeClient.instances[before:])

    # validation errors never echo the submitted input
    r = client.post("/api/accounts/login/code", json={"code": "9" * 50}, headers=a)
    assert r.status_code == 422 and "9999" not in r.text

    # A disconnects: remote logout + row deleted + audit trail without secrets
    FakeClient.instances.clear()
    assert client.delete(f"/api/accounts/{acc_id}", headers=a).status_code == 200
    assert any(c.logged_out for c in FakeClient.instances)
    assert sql("SELECT count(*) FROM telegram_accounts")[0][0] == 0
    events = sql("SELECT event_type, meta::text FROM audit_events ORDER BY id")
    kinds = [e[0] for e in events]
    assert kinds.count("terms_accepted") == 2  # once per user, even after a repeated call
    assert kinds[-2:] == ["account_connected", "account_disconnected"]
    assert all("SECRET" not in (e[1] or "") for e in events)


def test_migration_downgrade():
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0001"], check=True)
    assert sql("SELECT to_regclass('public.telegram_accounts')")[0][0] is None
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    assert sql("SELECT to_regclass('public.telegram_accounts')")[0][0] is not None
