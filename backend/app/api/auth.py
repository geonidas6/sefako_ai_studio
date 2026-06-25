from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db.database import get_db
from app.models.user import User
from app.core.security import verify_password, create_access_token, hash_password, get_current_admin

router = APIRouter()


class Token(BaseModel):
    access_token: str
    token_type: str
    username: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class ChangePasswordOut(BaseModel):
    success: bool


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs",
        )

    token = create_access_token({"sub": user.username})
    return Token(access_token=token, token_type="bearer", username=user.username)


@router.get("/me")
async def get_me(db: AsyncSession = Depends(get_db)):
    """Public endpoint to check if admin user exists (for first-run detection)."""
    result = await db.execute(select(User).where(User.is_admin == True))  # noqa: E712
    admin = result.scalar_one_or_none()
    return {"admin_exists": admin is not None}


@router.post("/change-password", response_model=ChangePasswordOut)
async def change_password(
    body: ChangePasswordIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    current_password = body.current_password
    new_password = body.new_password
    confirm_password = body.confirm_password

    if not verify_password(current_password, admin.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le mot de passe actuel est incorrect")

    if len(new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le nouveau mot de passe doit contenir au moins 8 caractères")

    if new_password != confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La confirmation du mot de passe ne correspond pas")

    if verify_password(new_password, admin.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le nouveau mot de passe doit être différent de l'ancien")

    admin.hashed_password = hash_password(new_password)
    await db.commit()
    return ChangePasswordOut(success=True)
