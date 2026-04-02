import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from app.config import settings
from app.models import User, RefreshToken, PlayerState, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TTL_MINUTES)
    return jwt.encode({"sub": user_id, "role": role, "exp": expire}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token_raw() -> str:
    return str(uuid.uuid4())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado",
                            headers={"X-Error-Code": "TOKEN_EXPIRED"})


async def get_or_create_player_state(user: User, db: AsyncSession) -> PlayerState:
    if user.player_state:
        return user.player_state
    ps = PlayerState(user_id=user.id,
                     permanent_upgrades={"sword": 0, "shield": 0, "crit": 0, "gold_boost": 0, "phoenix": 0},
                     meta_stats={"total_runs": 0, "total_kills": 0, "total_questions_answered": 0,
                                 "accuracy": 0.0, "best_run_kills": 0, "best_run_score": 0, "study_streak_days": 0})
    db.add(ps)
    await db.commit()
    await db.refresh(ps)
    return ps


async def register_user(name: str, email: str, password: str, db: AsyncSession) -> User:
    existing = await db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if existing:
        raise HTTPException(status_code=409, detail="E-mail já está em uso",
                            headers={"X-Error-Code": "EMAIL_ALREADY_IN_USE"})
    user = User(name=name, email=email, password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await get_or_create_player_state(user, db)
    return user


async def login_user(email: str, password: str, db: AsyncSession) -> User:
    user = await db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos",
                            headers={"X-Error-Code": "INVALID_CREDENTIALS"})
    return user


async def google_login(id_token_str: str, db: AsyncSession) -> tuple[User, bool]:
    try:
        info = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
    except Exception:
        raise HTTPException(status_code=401, detail="ID Token inválido ou expirado",
                            headers={"X-Error-Code": "INVALID_GOOGLE_TOKEN"})

    google_sub = info["sub"]
    email = info.get("email", "")
    name = info.get("name", email.split("@")[0])
    avatar_url = info.get("picture")

    user = await db.scalar(select(User).where(User.google_sub == google_sub))
    created = False
    if not user:
        # try to link existing email account
        user = await db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
        if user:
            user.google_sub = google_sub
            user.avatar_url = avatar_url
        else:
            user = User(name=name, email=email, google_sub=google_sub, avatar_url=avatar_url)
            db.add(user)
            created = True
        await db.commit()
        await db.refresh(user)
        await get_or_create_player_state(user, db)

    return user, created


async def save_refresh_token(user_id: uuid.UUID, raw_token: str, db: AsyncSession) -> None:
    expires = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TTL_DAYS)
    rt = RefreshToken(user_id=user_id, token_hash=hash_token(raw_token), expires_at=expires)
    db.add(rt)
    await db.commit()


async def rotate_refresh_token(raw_token: str, db: AsyncSession) -> tuple[User, str]:
    token_hash = hash_token(raw_token)
    rt = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
    )
    if not rt or rt.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Refresh token inválido ou expirado",
                            headers={"X-Error-Code": "REFRESH_TOKEN_INVALID"})
    rt.revoked_at = datetime.now(timezone.utc)
    new_raw = create_refresh_token_raw()
    expires = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TTL_DAYS)
    db.add(RefreshToken(user_id=rt.user_id, token_hash=hash_token(new_raw), expires_at=expires))
    await db.commit()
    user = await db.get(User, rt.user_id)
    return user, new_raw


async def revoke_refresh_token(raw_token: str, db: AsyncSession) -> None:
    token_hash = hash_token(raw_token)
    rt = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if rt:
        rt.revoked_at = datetime.now(timezone.utc)
        await db.commit()
