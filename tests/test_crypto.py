import base64
import os

import pytest

from app.security.crypto import CryptoError, SessionCipher, session_aad


def key(v: int) -> str:
    return f"{v}:" + base64.urlsafe_b64encode(os.urandom(32)).decode()


def test_roundtrip():
    c = SessionCipher(key(1))
    blob, ver = c.encrypt("SECRET-SESSION", session_aad(7))
    assert ver == 1 and b"SECRET-SESSION" not in blob
    assert c.decrypt(blob, ver, session_aad(7)) == "SECRET-SESSION"


def test_nonce_is_random():
    c = SessionCipher(key(1))
    assert c.encrypt("x", b"a")[0] != c.encrypt("x", b"a")[0]


def test_other_owner_cannot_decrypt():
    c = SessionCipher(key(1))
    blob, ver = c.encrypt("S", session_aad(1))
    with pytest.raises(CryptoError):
        c.decrypt(blob, ver, session_aad(2))


def test_tampered_blob_is_rejected():
    c = SessionCipher(key(1))
    blob, ver = c.encrypt("S", session_aad(1))
    bad = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(CryptoError):
        c.decrypt(bad, ver, session_aad(1))


def test_key_rotation():
    k1, k2 = key(1), key(2)
    old = SessionCipher(k1)
    blob, ver = old.encrypt("S", b"a")
    rotated = SessionCipher(f"{k1},{k2}")
    assert rotated.current_version == 2
    assert rotated.decrypt(blob, ver, b"a") == "S"
    assert rotated.encrypt("S", b"a")[1] == 2


def test_missing_old_key_fails():
    blob, ver = SessionCipher(key(1)).encrypt("S", b"a")
    with pytest.raises(CryptoError):
        SessionCipher(key(2)).decrypt(blob, ver, b"a")


@pytest.mark.parametrize("bad", ["", "garbage", "1:short", "x:AAAA"])
def test_bad_config(bad):
    with pytest.raises(CryptoError):
        SessionCipher(bad)
