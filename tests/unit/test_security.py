import pytest
import jwt

from songbirdapi.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
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
    token = create_access_token("user-123", "admin", SECRET)
    payload = decode_token(token, SECRET)
    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_create_refresh_token_decodes():
    token = create_refresh_token("user-123", SECRET)
    payload = decode_token(token, SECRET)
    assert payload["sub"] == "user-123"
    assert payload["type"] == "refresh"


def test_access_token_wrong_secret_fails():
    token = create_access_token("user-123", "user", SECRET)
    with pytest.raises(jwt.PyJWTError):
        decode_token(token, "wrongsecret")


def test_access_and_refresh_tokens_are_different():
    access = create_access_token("user-123", "user", SECRET)
    refresh = create_refresh_token("user-123", SECRET)
    assert access != refresh
