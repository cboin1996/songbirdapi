from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from songbirdapi import crud
from songbirdapi.models import Role, User
from songbirdapi.routers.auth import UserResponse
from ..dependencies import get_db, require_admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class UpdateUserBody(BaseModel):
    role: Optional[Role] = None
    is_active: Optional[bool] = None


@router.get("/users", response_model=List[UserResponse])
async def list_users(db: AsyncSession = Depends(get_db)):
    return await crud.list_users(db)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: str, body: UpdateUserBody, db: AsyncSession = Depends(get_db)):
    user = await crud.update_user(db, user_id, role=body.role, is_active=body.is_active)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await crud.delete_user(db, user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
