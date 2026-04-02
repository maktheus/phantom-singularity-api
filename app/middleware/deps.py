from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models import User, UserRole
from app.services.auth_service import decode_access_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(401, "Não autenticado", headers={"X-Error-Code": "UNAUTHENTICATED"})
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    user = await db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    if not user:
        raise HTTPException(401, "Usuário não encontrado", headers={"X-Error-Code": "UNAUTHENTICATED"})
    return user


def require_role(*roles: UserRole):
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(403, "Acesso negado", headers={"X-Error-Code": "INSUFFICIENT_ROLE"})
        return current_user
    return checker
