import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security.telegram_auth import InitDataError, validate_init_data

TOKEN = "123456:TEST_TOKEN_FOR_TESTS"


def make_init_data(token=TOKEN, user_id=42, auth_date=None, extra=None) -> str:
    auth_date = int(time.time()) if auth_date is None else auth_date
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": "Test", "language_code": "ru"}),
    }
    if extra:
        fields.update(extra)
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_init_data():
    user = validate_init_data(make_init_data(user_id=777), TOKEN, 3600)
    assert user["id"] == 777


def test_extra_signed_field_is_accepted():
    data = make_init_data(extra={"signature": "abc_def"})
    assert validate_init_data(data, TOKEN, 3600)["id"] == 42


def test_wrong_token_is_rejected():
    with pytest.raises(InitDataError):
        validate_init_data(make_init_data(token="999:OTHER"), TOKEN, 3600)


def test_tampered_user_is_rejected():
    data = make_init_data(user_id=1)
    forged = data.replace("%22id%22%3A+1", "%22id%22%3A+2")
    assert forged != data
    with pytest.raises(InitDataError):
        validate_init_data(forged, TOKEN, 3600)


def test_expired_is_rejected():
    old = make_init_data(auth_date=int(time.time()) - 7200)
    with pytest.raises(InitDataError):
        validate_init_data(old, TOKEN, 3600)


def test_future_date_is_rejected():
    future = make_init_data(auth_date=int(time.time()) + 3600)
    with pytest.raises(InitDataError):
        validate_init_data(future, TOKEN, 3600)


@pytest.mark.parametrize("bad", ["", "hash=abc", "user=%7B%7D", "a" * 9000])
def test_garbage_is_rejected(bad):
    with pytest.raises(InitDataError):
        validate_init_data(bad, TOKEN, 3600)


def test_api_me_requires_auth():
    client = TestClient(app)
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer x"}).status_code == 401
    assert client.get("/api/me", headers={"Authorization": "tma garbage"}).status_code == 401
