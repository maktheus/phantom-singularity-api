import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.models import Concurso, UserRole, User
from app.schemas import ConcursoCreate, ConcursoOut
from app.middleware.deps import get_current_user, require_role

router = APIRouter(prefix="/concursos", tags=["Concursos"])


@router.get("", response_model=list[ConcursoOut])
async def list_concursos(db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(Concurso).order_by(Concurso.name))
    return [ConcursoOut.model_validate(r) for r in rows]


@router.get("/{concurso_id}", response_model=ConcursoOut)
async def get_concurso(concurso_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    c = await db.get(Concurso, concurso_id)
    if not c:
        raise HTTPException(404, "Concurso não encontrado", headers={"X-Error-Code": "NOT_FOUND"})
    return ConcursoOut.model_validate(c)


@router.post("", status_code=201, response_model=ConcursoOut)
async def create_concurso(body: ConcursoCreate, db: AsyncSession = Depends(get_db),
                          _: User = Depends(require_role(UserRole.admin))):
    existing = await db.scalar(select(Concurso).where(Concurso.slug == body.slug))
    if existing:
        raise HTTPException(409, f"Slug '{body.slug}' já existe",
                            headers={"X-Error-Code": "EMAIL_ALREADY_IN_USE"})
    c = Concurso(**body.model_dump())
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return ConcursoOut.model_validate(c)


@router.patch("/{concurso_id}", response_model=ConcursoOut)
async def update_concurso(concurso_id: uuid.UUID, body: ConcursoCreate,
                          db: AsyncSession = Depends(get_db),
                          _: User = Depends(require_role(UserRole.admin))):
    c = await db.get(Concurso, concurso_id)
    if not c:
        raise HTTPException(404, "Concurso não encontrado", headers={"X-Error-Code": "NOT_FOUND"})
    for field, value in body.model_dump().items():
        setattr(c, field, value)
    await db.commit()
    await db.refresh(c)
    return ConcursoOut.model_validate(c)


@router.delete("/{concurso_id}", status_code=204)
async def delete_concurso(concurso_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                          _: User = Depends(require_role(UserRole.admin))):
    c = await db.get(Concurso, concurso_id)
    if not c:
        raise HTTPException(404, "Concurso não encontrado", headers={"X-Error-Code": "NOT_FOUND"})
    await db.delete(c)
    await db.commit()
