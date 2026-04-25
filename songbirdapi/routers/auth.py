import uuid
from typing import Optional

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from songbirdapi import crud
from songbirdapi.models import Role, User
from songbirdapi.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from ..dependencies import get_current_user, get_db, load_settings, require_admin

router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str
    email: str
    password: str
    role: Role = Role.user


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: Role
    is_active: bool

    model_config = {"from_attributes": True}


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    response.set_cookie(ACCESS_COOKIE, access_token, httponly=True, samesite="lax")
    response.set_cookie(REFRESH_COOKIE, refresh_token, httponly=True, samesite="lax")


@router.post("/login")
async def login(body: LoginBody, response: Response, db: AsyncSession = Depends(get_db)):
    user = await crud.get_user_by_username(db, body.username)
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    config = load_settings()
    access_token = create_access_token(user.id, user.role.value, config.jwt_secret)
    refresh_token = create_refresh_token(user.id, config.jwt_secret)
    _set_auth_cookies(response, access_token, refresh_token)
    return UserResponse.model_validate(user)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(ACCESS_COOKIE)
    response.delete_cookie(REFRESH_COOKIE)
    return {"message": "logged out"}


@router.post("/refresh")
async def refresh(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if not refresh_token:
        raise credentials_exception
    config = load_settings()
    try:
        payload = decode_token(refresh_token, config.jwt_secret)
        if payload.get("type") != "refresh":
            raise credentials_exception
        user_id: str = payload.get("sub")
    except jwt.PyJWTError:
        raise credentials_exception

    user = await crud.get_user(db, user_id)
    if not user or not user.is_active:
        raise credentials_exception

    access_token = create_access_token(user.id, user.role.value, config.jwt_secret)
    response.set_cookie(ACCESS_COOKIE, access_token, httponly=True, samesite="lax")
    return {"message": "token refreshed"}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> UserResponse:
    if await crud.get_user_by_username(db, body.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")
    if await crud.get_user_by_email(db, body.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        id=str(uuid.uuid4()),
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    await crud.create_user(db, user)
    return UserResponse.model_validate(user)


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.patch("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")
    current_user.hashed_password = hash_password(body.new_password)
    await db.commit()
