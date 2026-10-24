"""Server-side verification of Telegram Mini App `initData`.

Never trust a Telegram ID sent by the client: it is only accepted if the whole
initData string carries a valid HMAC signature made with the bot token.
Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_INIT_DATA_LEN = 8192


class InitDataError(Exception):
    """initData is missing, malformed, forged or expired."""


def validate_init_data(init_data: str, bot_token: str, max_age: int) -> dict:
    """Return the verified Telegram user dict, or raise InitDataError."""
    if not init_data or len(init_data) > MAX_INIT_DATA_LEN:
        raise InitDataError("empty or oversized initData")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("hash is missing")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("signature mismatch")

    try:
        auth_date = int(pairs["auth_date"])
    except (KeyError, ValueError):
        raise InitDataError("auth_date is invalid") from None
    now = time.time()
    if auth_date > now + 60 or now - auth_date > max_age:
        raise InitDataError("initData expired")

    try:
        user = json.loads(pairs["user"])
        user_id = user["id"]
    except (KeyError, ValueError, TypeError):
        raise InitDataError("user is missing") from None
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        raise InitDataError("user id is invalid")
    return user
