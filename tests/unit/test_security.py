import pytest
import jwt

from songbirdapi.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
    ALGORITHM,
)

SECRET = "testsecretthatisenoughbytes123456"


async def test_hash_and_verify_password():
    hashed = await hash_password("hunter2")
    assert await verify_password("hunter2", hashed)


async def test_wrong_password_fails():
    hashed = await hash_password("hunter2")
    assert not await verify_password("wrongpassword", hashed)


async def test_hash_is_not_plaintext():
    hashed = await hash_password("hunter2")
    assert hashed != "hunter2"


def test_create_access_token_decodes():
    token = create_access_token("user-123", "admin", "sid-1", SECRET)
    payload = decode_token(token, SECRET)
    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"
    assert payload["sid"] == "sid-1"


def test_access_token_wrong_secret_fails():
    token = create_access_token("user-123", "user", "sid-1", SECRET)
    with pytest.raises(jwt.PyJWTError):
        decode_token(token, "wrongsecret")


def test_session_refresh_jwt_is_identical_when_reissued():
    from datetime import datetime, timedelta, timezone

    from songbirdapi.models import AuthSession
    from songbirdapi.security import make_refresh_jwt

    created = datetime(2026, 1, 1, 12, 0, 0, 500000, tzinfo=timezone.utc)
    session = AuthSession(
        id="sid-1", user_id="user-123", jti="jti-1", created_at=created
    )
    args = (session, timedelta(days=90), SECRET)
    first = make_refresh_jwt(*args)
    assert make_refresh_jwt(*args) == first
    payload = jwt.decode(
        first, SECRET, algorithms=[ALGORITHM], options={"verify_exp": False}
    )
    assert payload == {
        "sub": "user-123",
        "type": "refresh",
        "sid": "sid-1",
        "jti": "jti-1",
        "exp": 1775044800,  # 2026-04-01T12:00:00Z
    }
