import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.session import get_db
from app.models import Exam, Question, Concurso, ExamStatus, UserRole, User
from app.schemas import ExamOut, ExamStatusOut, ExamDetailOut, ExamListResponse
from app.middleware.deps import get_current_user, require_role

router = APIRouter(prefix="/exams", tags=["Exams"])

MAX_EXAM_MB = 50
MAX_KEY_MB = 5


def _exam_to_out(exam: Exam) -> ExamOut:
    slug = exam.concurso.slug if exam.concurso else None
    return ExamOut(id=exam.id, banca=exam.banca, year=exam.year, cargo=exam.cargo,
                   concurso_slug=slug, status=exam.status, parsed_count=exam.parsed_count,
                   total_pages=exam.total_pages, error_msg=exam.error_msg,
                   ingested_by=exam.ingested_by, ingested_at=exam.ingested_at)


@router.post("/ingest", status_code=202)
async def ingest_exam(
    background_tasks: BackgroundTasks,
    exam_pdf: UploadFile = File(...),
    key_pdf: UploadFile = File(...),
    banca: str = Form(...),
    year: int = Form(..., ge=1990, le=2030),
    cargo: str = Form(...),
    concurso_id: uuid.UUID = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    # Validate mime types
    for upload, label in [(exam_pdf, "exam_pdf"), (key_pdf, "key_pdf")]:
        if upload.content_type != "application/pdf":
            raise HTTPException(400, f"{label}: apenas PDFs são aceitos",
                                headers={"X-Error-Code": "VALIDATION_ERROR"})

    # Validate size
    exam_bytes = await exam_pdf.read()
    key_bytes = await key_pdf.read()
    if len(exam_bytes) > MAX_EXAM_MB * 1024 * 1024:
        raise HTTPException(400, f"exam_pdf excede {MAX_EXAM_MB}MB",
                            headers={"X-Error-Code": "VALIDATION_ERROR"})
    if len(key_bytes) > MAX_KEY_MB * 1024 * 1024:
        raise HTTPException(400, f"key_pdf excede {MAX_KEY_MB}MB",
                            headers={"X-Error-Code": "VALIDATION_ERROR"})

    # Validate concurso exists
    conc = await db.scalar(select(Concurso).where(Concurso.id == concurso_id))
    if not conc:
        raise HTTPException(404, "concurso_id não encontrado", headers={"X-Error-Code": "NOT_FOUND"})

    # Create exam record
    exam = Exam(concurso_id=concurso_id, banca=banca, year=year, cargo=cargo,
                status=ExamStatus.pending, ingested_by=current_user.id)
    db.add(exam)
    await db.commit()
    await db.refresh(exam)

    # Dispatch Celery task
    from app.tasks.ingest_pdf import process_exam
    process_exam.apply_async(
        args=[str(exam.id), exam_bytes, key_bytes, str(concurso_id)],
        queue="pdf_ingestion",
    )

    return {"exam_id": str(exam.id), "status": "processing",
            "message": "PDF recebido. Processamento iniciado em background."}


@router.get("/{exam_id}/status", response_model=ExamStatusOut)
async def exam_status(exam_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                      _: User = Depends(get_current_user)):
    exam = await db.scalar(select(Exam).where(Exam.id == exam_id))
    if not exam:
        raise HTTPException(404, "Prova não encontrada", headers={"X-Error-Code": "NOT_FOUND"})
    return ExamStatusOut(status=exam.status, parsed_count=exam.parsed_count,
                         total_pages=exam.total_pages, error_msg=exam.error_msg)


@router.get("", response_model=ExamListResponse)
async def list_exams(concurso_id: uuid.UUID | None = None, banca: str | None = None,
                     year: int | None = None, status: ExamStatus | None = None,
                     page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100),
                     db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    stmt = select(Exam).where(Exam.deleted_at.is_(None))
    if concurso_id:
        stmt = stmt.where(Exam.concurso_id == concurso_id)
    if banca:
        stmt = stmt.where(Exam.banca.ilike(f"%{banca}%"))
    if year:
        stmt = stmt.where(Exam.year == year)
    if status:
        stmt = stmt.where(Exam.status == status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    items_q = await db.scalars(stmt.order_by(Exam.ingested_at.desc()).offset((page - 1) * per_page).limit(per_page))
    items = [_exam_to_out(e) for e in items_q]
    return ExamListResponse(page=page, per_page=per_page, total=total,
                            has_next=(page * per_page) < total, items=items)


@router.get("/{exam_id}", response_model=ExamDetailOut)
async def get_exam(exam_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                   _: User = Depends(get_current_user)):
    exam = await db.scalar(select(Exam).where(Exam.id == exam_id, Exam.deleted_at.is_(None)))
    if not exam:
        raise HTTPException(404, "Prova não encontrada", headers={"X-Error-Code": "NOT_FOUND"})
    qs_q = await db.scalars(select(Question).where(Question.exam_id == exam_id, Question.deleted_at.is_(None)))
    from app.routers.v1.questions import _q_to_out
    questions = [_q_to_out(q) for q in qs_q]
    return ExamDetailOut(exam=_exam_to_out(exam), questions=questions, total_questions=len(questions))


@router.delete("/{exam_id}", status_code=204)
async def delete_exam(exam_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                      _: User = Depends(require_role(UserRole.admin))):
    exam = await db.scalar(select(Exam).where(Exam.id == exam_id, Exam.deleted_at.is_(None)))
    if not exam:
        raise HTTPException(404, "Prova não encontrada", headers={"X-Error-Code": "NOT_FOUND"})
    now = datetime.utcnow()
    exam.deleted_at = now
    # cascade soft-delete questions
    qs_q = await db.scalars(select(Question).where(Question.exam_id == exam_id, Question.deleted_at.is_(None)))
    for q in qs_q:
        q.deleted_at = now
    await db.commit()
