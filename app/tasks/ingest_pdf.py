"""PDF Ingestion — background Celery task.
Extracts text from exam PDF, parses the answer key PDF,
then calls Ollama to structure the questions and bulk-inserts them.
"""
import re
import uuid
import asyncio
from celery import Celery
from celery.utils.log import get_task_logger

from app.config import settings

celery_app = Celery("phantom", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.task_routes = {"app.tasks.ingest_pdf.*": {"queue": "pdf_ingestion"}}

logger = get_task_logger(__name__)


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Synchronous PDF text extraction using pypdf."""
    from io import BytesIO
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_answer_key(key_text: str) -> dict[int, str]:
    """Extract question number → letter from answer key text.
    Handles formats: '1. A', '1-A', '1) A', '01 A' etc.
    """
    pattern = re.compile(r"(\d{1,3})\s*[.\-\)]\s*([A-Ea-e])")
    return {int(m.group(1)): m.group(2).upper() for m in pattern.finditer(key_text)}


EXTRACTION_PROMPT = """Você é um parser de provas de concurso público brasileiro.
Extraia CADA questão do texto abaixo e retorne somente um JSON válido (sem markdown).

TEXTO DA PROVA:
{exam_text}

GABARITO (questão -> letra correta):
{answer_map}

Retorne exatamente no formato (array JSON):
[
  {{
    "number": 1,
    "text": "Enunciado completo...",
    "options": [
      {{"index": 0, "text": "A..."}},
      {{"index": 1, "text": "B..."}},
      {{"index": 2, "text": "C..."}},
      {{"index": 3, "text": "D..."}},
      {{"index": 4, "text": "E..."}}
    ],
    "correct_index": 2,
    "topic": "tópico estimado"
  }}
]"""


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30,
                 name="app.tasks.ingest_pdf.process_exam")
def process_exam(self, exam_id: str, exam_bytes: bytes, key_bytes: bytes, concurso_id: str):
    """Parse PDFs and ingest questions into the database. Runs in Celery worker."""
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, Session
    from app.models import Exam, Question, Concurso, ExamStatus, Difficulty
    from app.services.llm_service import extract_json
    import httpx

    sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_db_url)
    SessionLocal = sessionmaker(bind=engine)

    def update_status(db: Session, status: ExamStatus, error: str | None = None, count: int = 0):
        exam = db.get(Exam, uuid.UUID(exam_id))
        if exam:
            exam.status = status
            if error:
                exam.error_msg = error
            if count:
                exam.parsed_count = count
            db.commit()

    with SessionLocal() as db:
        try:
            update_status(db, ExamStatus.processing)

            # 1. Extract text
            exam_text = _extract_text_from_pdf(exam_bytes)
            key_text = _extract_text_from_pdf(key_bytes)
            answer_map = _parse_answer_key(key_text)

            # 2. Call Ollama synchronously
            prompt = EXTRACTION_PROMPT.format(
                exam_text=exam_text[:12000],  # limit context window
                answer_map=json.dumps(answer_map, ensure_ascii=False)
            )
            resp = httpx.post(
                f"{settings.OLLAMA_URL}/api/generate",
                json={"model": "llama3.2", "prompt": prompt, "stream": False,
                      "format": "json", "options": {"temperature": 0.1, "num_predict": 6000}},
                timeout=120,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            parsed = extract_json(raw)
            if not isinstance(parsed, list):
                parsed = parsed.get("questions", [])

            # 3. Bulk insert
            letter_to_index = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
            inserted = 0
            for item in parsed:
                num = item.get("number")
                correct_letter = answer_map.get(num, "A")
                opts = item.get("options", [])
                if len(opts) != 5:
                    continue
                # add tips from answer key
                correct_idx = letter_to_index.get(correct_letter, 0)
                for opt in opts:
                    opt.setdefault("tip", "Gabarito extraído da prova oficial.")

                q = Question(
                    concurso_id=uuid.UUID(concurso_id),
                    exam_id=uuid.UUID(exam_id),
                    text=item.get("text", ""),
                    options=opts,
                    correct_index=correct_idx,
                    topic=item.get("topic", "Geral"),
                    source="real",
                    ai_generated=False,
                )
                db.add(q)
                inserted += 1

            db.commit()
            update_status(db, ExamStatus.done, count=inserted)
            logger.info("Exam %s processed: %d questions inserted.", exam_id, inserted)

        except Exception as exc:
            logger.error("Error processing exam %s: %s", exam_id, exc)
            try:
                raise self.retry(exc=exc)
            except self.MaxRetriesExceededError:
                update_status(db, ExamStatus.error, error=str(exc))
