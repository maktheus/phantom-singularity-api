from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.models import User, UserRole
from app.schemas import PlayerStateOut, PlayerStats, UpgradeRequest, UpgradeResponse
from app.middleware.deps import get_current_user

router = APIRouter(prefix="/player", tags=["Player"])

UPGRADE_COSTS = {"sword": 100, "shield": 80, "crit": 150, "gold_boost": 120, "phoenix": 200}
UPGRADE_MAX_LEVEL = 5


@router.get("/me", response_model=PlayerStateOut)
async def get_player(current_user: User = Depends(get_current_user)):
    ps = current_user.player_state
    if not ps:
        raise HTTPException(404, "Player state não encontrado", headers={"X-Error-Code": "NOT_FOUND"})
    stats = PlayerStats(**(ps.meta_stats or {}))
    return PlayerStateOut(gold=ps.gold, xp=ps.xp, level=ps.level,
                          permanent_upgrades=ps.permanent_upgrades, stats=stats)


@router.patch("/me/upgrades", response_model=UpgradeResponse)
async def buy_upgrade(body: UpgradeRequest, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    if body.upgrade_key not in UPGRADE_COSTS:
        raise HTTPException(400, f"upgrade_key inválido: {body.upgrade_key}",
                            headers={"X-Error-Code": "INVALID_UPGRADE_KEY"})

    ps = current_user.player_state
    if not ps:
        raise HTTPException(404, "Player state não encontrado")

    upgrades = ps.permanent_upgrades or {}
    current_level = upgrades.get(body.upgrade_key, 0)

    if current_level + body.levels > UPGRADE_MAX_LEVEL:
        raise HTTPException(400, f"Nível máximo ({UPGRADE_MAX_LEVEL}) já atingido ou seria ultrapassado",
                            headers={"X-Error-Code": "MAX_LEVEL_REACHED"})

    total_cost = UPGRADE_COSTS[body.upgrade_key] * body.levels
    if ps.gold < total_cost:
        raise HTTPException(400, f"Ouro insuficiente. Necessário: {total_cost}, disponível: {ps.gold}",
                            headers={"X-Error-Code": "INSUFFICIENT_GOLD"})

    ps.gold -= total_cost
    upgrades[body.upgrade_key] = current_level + body.levels
    ps.permanent_upgrades = upgrades
    await db.commit()

    return UpgradeResponse(permanent_upgrades=ps.permanent_upgrades, gold_remaining=ps.gold)
