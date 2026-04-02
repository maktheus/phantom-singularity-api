from datetime import timedelta
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.schemas import (
    RegisterRequest, LoginRequest, GoogleAuthRequest,
    AuthResponse, UserOut, MeResponse
)
from app.services import auth_service
from app.middleware.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/auth", tags=["Auth"])

REFRESH_COOKIE = "refresh_token"
COOKIE_OPTS = dict(httponly=True, secure=True, samesite="strict",
                   max_age=int(timedelta(days=30).total_seconds()))


def _set_refresh_cookie(response: Response, token: str):
    response.set_cookie(REFRESH_COOKIE, token, **COOKIE_OPTS)


@router.post("/register", status_code=201, response_model=AuthResponse)
async def register(body: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await auth_service.register_user(body.name, body.email, body.password, db)
    raw_rt = auth_service.create_refresh_token_raw()
    await auth_service.save_refresh_token(user.id, raw_rt, db)
    _set_refresh_cookie(response, raw_rt)
    token = auth_service.create_access_token(str(user.id), user.role.value)
    return AuthResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await auth_service.login_user(body.email, body.password, db)
    raw_rt = auth_service.create_refresh_token_raw()
    await auth_service.save_refresh_token(user.id, raw_rt, db)
    _set_refresh_cookie(response, raw_rt)
    token = auth_service.create_access_token(str(user.id), user.role.value)
    return AuthResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/google", response_model=AuthResponse)
async def google_auth(body: GoogleAuthRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user, created = await auth_service.google_login(body.id_token, db)
    raw_rt = auth_service.create_refresh_token_raw()
    await auth_service.save_refresh_token(user.id, raw_rt, db)
    _set_refresh_cookie(response, raw_rt)
    token = auth_service.create_access_token(str(user.id), user.role.value)
    resp = AuthResponse(access_token=token, user=UserOut.model_validate(user))
    # Return 201 if newly created
    if created:
        from fastapi.responses import JSONResponse
        return JSONResponse(content=resp.model_dump(), status_code=201)
    return resp


@router.post("/refresh", response_model=dict)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from fastapi import HTTPException
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(401, "Refresh token ausente", headers={"X-Error-Code": "REFRESH_TOKEN_INVALID"})
    user, new_raw = await auth_service.rotate_refresh_token(raw, db)
    _set_refresh_cookie(response, new_raw)
    token = auth_service.create_access_token(str(user.id), user.role.value)
    return {"access_token": token}


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db),
                 _: User = Depends(get_current_user)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await auth_service.revoke_refresh_token(raw, db)
    response.delete_cookie(REFRESH_COOKIE)


@router.get("/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)):
    from app.schemas import PlayerStateOut, PlayerStats
    ps = current_user.player_state
    stats = PlayerStats(**(ps.meta_stats if ps else {})) if ps else PlayerStats()
    player_out = PlayerStateOut(
        gold=ps.gold if ps else 0, xp=ps.xp if ps else 0, level=ps.level if ps else 1,
        permanent_upgrades=ps.permanent_upgrades if ps else {}, stats=stats
    ) if ps else None
    return MeResponse(user=UserOut.model_validate(current_user), player_state=player_out)
