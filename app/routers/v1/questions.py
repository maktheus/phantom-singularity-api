import math
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.db.session import get_db
from app.models import Question, Concurso, Difficulty, UserRole, User
from app.schemas import (
    QuestionCreate, QuestionUpdate, QuestionOut,
    QuestionListResponse, GenerateQuestionsRequest
)
from app.middleware.deps import get_current_user, require_role
from app.services.question_gen import generate_questions_rag

router = APIRouter(prefix="/questions", tags=["Questions"])


def _q_to_out(q: Question) -> QuestionOut:
    slug = q.concurso.slug if q.concurso else None
    return QuestionOut(
        id=q.id, text=q.text, options=q.options, correct_index=q.correct_index,
        topic=q.topic, difficulty=q.difficulty, source=q.source, ai_generated=q.ai_generated,
        concurso_slug=slug, exam_id=q.exam_id, hits=q.hits, misses=q.misses,
        hit_rate=q.hit_rate, created_at=q.created_at
    )


@router.get("", response_model=QuestionListResponse)
async def list_questions(
    concurso: str | None = None, topic: str | None = None,
    difficulty: Difficulty | None = None, source: str | None = None,
    page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Question).where(Question.deleted_at.is_(None))
    if difficulty:
        stmt = stmt.where(Question.difficulty == difficulty)
    if source:
        stmt = stmt.where(Question.source == source)
    if topic:
        stmt = stmt.where(Question.topic.ilike(f"%{topic}%"))
    if concurso:
        conc = await db.scalar(select(Concurso).where(Concurso.slug == concurso))
        if not conc:
            raise HTTPException(400, f"Concurso '{concurso}' não encontrado",
                                headers={"X-Error-Code": "VALIDATION_ERROR"})
        stmt = stmt.where(Question.concurso_id == conc.id)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    items_q = await db.scalars(stmt.offset((page - 1) * per_page).limit(per_page))
    items = [_q_to_out(q) for q in items_q]
    return QuestionListResponse(page=page, per_page=per_page, total=total,
                                has_next=(page * per_page) < total, items=items)


@router.get("/{question_id}", response_model=QuestionOut)
async def get_question(question_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                       _: User = Depends(get_current_user)):
    q = await db.scalar(select(Question).where(Question.id == question_id, Question.deleted_at.is_(None)))
    if not q:
        raise HTTPException(404, "Questão não encontrada", headers={"X-Error-Code": "NOT_FOUND"})
    return _q_to_out(q)


@router.post("", status_code=201, response_model=QuestionOut)
async def create_question(body: QuestionCreate, db: AsyncSession = Depends(get_db),
                          _: User = Depends(require_role(UserRole.admin))):
    q = Question(
        concurso_id=body.concurso_id, exam_id=body.exam_id,
        text=body.text, options=[o.model_dump() for o in body.options],
        correct_index=body.correct_index, topic=body.topic, difficulty=body.difficulty,
        source="real", ai_generated=False,
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return _q_to_out(q)


@router.patch("/{question_id}", response_model=QuestionOut)
async def update_question(question_id: uuid.UUID, body: QuestionUpdate,
                          db: AsyncSession = Depends(get_db),
                          _: User = Depends(require_role(UserRole.admin))):
    q = await db.scalar(select(Question).where(Question.id == question_id, Question.deleted_at.is_(None)))
    if not q:
        raise HTTPException(404, "Questão não encontrada", headers={"X-Error-Code": "NOT_FOUND"})
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(q, field, value)
    await db.commit()
    await db.refresh(q)
    return _q_to_out(q)


@router.delete("/{question_id}", status_code=204)
async def delete_question(question_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                          _: User = Depends(require_role(UserRole.admin))):
    q = await db.scalar(select(Question).where(Question.id == question_id, Question.deleted_at.is_(None)))
    if not q:
        raise HTTPException(404, "Questão não encontrada", headers={"X-Error-Code": "NOT_FOUND"})
    q.deleted_at = datetime.utcnow()
    await db.commit()


@router.post("/generate", response_model=list[QuestionOut])
async def generate_questions(body: GenerateQuestionsRequest, db: AsyncSession = Depends(get_db),
                              _: User = Depends(require_role(UserRole.admin))):
    try:
        questions = await generate_questions_rag(body.concurso_slug, body.topic, body.count, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, "LLM indisponível — tente novamente",
                            headers={"X-Error-Code": "LLM_UNAVAILABLE"}) from e
    return [_q_to_out(q) for q in questions]
