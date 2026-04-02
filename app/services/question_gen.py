import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException
from app.models import Question, Concurso, Difficulty
from app.services.llm_service import ollama_generate, extract_json

RAG_PROMPT_TEMPLATE = """Você é um professor especialista para concursos públicos brasileiros.
Abaixo estão {n_examples} questões REAIS de prova da área de {area}. Analise o estilo, tom, dificuldade e a forma como as alternativas enganam o candidato:

--- QUESTÕES DE REFERÊNCIA ---
{examples}
--- FIM DAS REFERÊNCIAS ---

Agora gere exatamente {count} NOVAS questões sobre o tópico "{topic}" no MESMO estilo e nível de dificuldade.
IMPORTANTE: As questões devem ser INÉDITAS, mas com o mesmo grau de dificuldade, terminologia jurídica/técnica e pegadinhas.

Retorne SOMENTE um JSON válido (sem markdown), neste formato:
[
  {{
    "text": "Enunciado completo com situação hipotética se aplicável...",
    "options": [
      {{"index": 0, "text": "Alternativa A completa", "tip": "Explicação do erro/acerto"}},
      {{"index": 1, "text": "Alternativa B completa", "tip": "Explicação do erro/acerto"}},
      {{"index": 2, "text": "Alternativa C completa", "tip": "Explicação do erro/acerto"}},
      {{"index": 3, "text": "Alternativa D completa", "tip": "Explicação do erro/acerto"}},
      {{"index": 4, "text": "Alternativa E completa", "tip": "Explicação do erro/acerto"}}
    ],
    "correct_index": 2,
    "topic": "{topic}"
  }}
]"""


def _format_question_for_context(q: Question) -> str:
    opts = "\n".join(f"  {chr(65+o['index'])}) {o['text']}" for o in q.options)
    correct_letter = chr(65 + q.correct_index)
    return f"Questão: {q.text}\n{opts}\nGabarito: {correct_letter}"


async def generate_questions_rag(
    concurso_slug: str, topic: str, count: int, db: AsyncSession
) -> list[Question]:
    # 1. Fetch concurso
    concurso = await db.scalar(select(Concurso).where(Concurso.slug == concurso_slug))
    if not concurso:
        raise HTTPException(404, f"Concurso '{concurso_slug}' não encontrado")

    # 2. Get few-shot examples from real DB
    examples_q = await db.scalars(
        select(Question).where(
            Question.concurso_id == concurso.id,
            Question.source == "real",
            Question.deleted_at.is_(None),
        ).order_by(func.random()).limit(5)
    )
    examples = list(examples_q)

    examples_text = "\n\n".join(_format_question_for_context(q) for q in examples) if examples else "(sem exemplos ainda no banco)"

    prompt = RAG_PROMPT_TEMPLATE.format(
        n_examples=len(examples), area=concurso.area,
        examples=examples_text, count=count, topic=topic
    )

    try:
        raw = await ollama_generate(prompt)
        parsed = extract_json(raw)
        if not isinstance(parsed, list):
            parsed = parsed.get("questions", [])
    except Exception as e:
        raise HTTPException(500, f"Falha ao estruturar questões — verifique o modelo: {e}") from e

    # 3. Validate and save
    created: list[Question] = []
    for item in parsed[:count]:
        if len(item.get("options", [])) != 5:
            continue
        q = Question(
            concurso_id=concurso.id,
            text=item["text"],
            options=item["options"],
            correct_index=int(item.get("correct_index", 0)),
            topic=item.get("topic", topic),
            difficulty=Difficulty.medium,
            source="ai",
            ai_generated=True,
        )
        db.add(q)
        created.append(q)

    await db.commit()
    for q in created:
        await db.refresh(q)

    if not created:
        raise HTTPException(500, "LLM não retornou questões válidas. Tente novamente.")

    return created
