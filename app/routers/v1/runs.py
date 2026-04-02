import uuid
import random
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.session import get_db
from app.models import Run, RunAnswer, RunStatus, Question, Concurso, Difficulty, User, PlayerState
from app.schemas import (
    StartRunRequest, StartRunResponse, AnswerRequest, AnswerResponse,
    EndRunRequest, RunSummary, RunOut, RunListResponse, EnemyConfig, QuestionOut
)
from app.middleware.deps import get_current_user
from app.routers.v1.questions import _q_to_out

router = APIRouter(prefix="/runs", tags=["Runs"])

ENEMY_POOL = [
    {"name": "Candidato Perdido", "emoji": "😰", "base_hp": 80, "gold": 15, "xp": 20},
    {"name": "Questão de Direito", "emoji": "⚖️", "base_hp": 100, "gold": 20, "xp": 30},
    {"name": "Lobo Concurseiro", "emoji": "🐺", "base_hp": 120, "gold": 25, "xp": 40},
    {"name": "Dragão da Burocracia", "emoji": "🐉", "base_hp": 180, "gold": 45, "xp": 70},
    {"name": "Chefe da Banca", "emoji": "👹", "base_hp": 250, "gold": 80, "xp": 120},
]

BUILD_STATS = {
    "guerreiro": {"base_hp": 150, "base_dmg": 25, "crit_chance": 0.05},
    "mago":      {"base_hp": 100, "base_dmg": 40, "crit_chance": 0.20},
    "suporte":   {"base_hp": 200, "base_dmg": 15, "crit_chance": 0.05},
}


def _make_enemy(kill_count: int) -> EnemyConfig:
    pool_idx = min(kill_count // 3, len(ENEMY_POOL) - 1)
    base = ENEMY_POOL[pool_idx]
    hp_scale = 1 + kill_count * 0.15
    is_boss = kill_count > 0 and kill_count % 5 == 0
    modifier = "boss" if is_boss else ("furious" if random.random() < 0.2 else "normal")
    dmg_mod = 2.0 if is_boss else (1.5 if modifier == "furious" else 1.0)
    hp = int(base["base_hp"] * hp_scale * (1.5 if is_boss else 1.0))
    return EnemyConfig(
        name=("👑 " if is_boss else "") + base["name"],
        emoji=base["emoji"], hp=hp, max_hp=hp,
        modifier=modifier, modifier_label=modifier.capitalize(),
        damage_modifier=dmg_mod, gold_reward=base["gold"], xp_reward=base["xp"]
    )


async def _pick_questions(concurso_id: uuid.UUID, count: int, db: AsyncSession) -> list[Question]:
    """Pick a balanced set of questions: 70% real, 30% ai; 30% easy, 50% medium, 20% hard."""
    results = []
    for src, n in [("real", int(count * 0.7)), ("ai", count - int(count * 0.7))]:
        for diff, frac in [(Difficulty.easy, 0.3), (Difficulty.medium, 0.5), (Difficulty.hard, 0.2)]:
            sub_n = max(1, int(n * frac))
            q_rows = await db.scalars(
                select(Question).where(
                    Question.concurso_id == concurso_id,
                    Question.source == src,
                    Question.difficulty == diff,
                    Question.deleted_at.is_(None),
                ).order_by(func.random()).limit(sub_n)
            )
            results.extend(list(q_rows))
    # Fallback: if not enough, fill randomly
    if len(results) < count:
        existing_ids = {q.id for q in results}
        extra = await db.scalars(
            select(Question).where(
                Question.concurso_id == concurso_id,
                Question.id.notin_(existing_ids),
                Question.deleted_at.is_(None),
            ).order_by(func.random()).limit(count - len(results))
        )
        results.extend(list(extra))
    random.shuffle(results)
    return results[:count]


@router.post("", status_code=201, response_model=StartRunResponse)
async def start_run(body: StartRunRequest, db: AsyncSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    # Check for active run
    active = await db.scalar(
        select(Run).where(Run.user_id == current_user.id, Run.status == RunStatus.active))
    if active:
        raise HTTPException(409, "Você já tem uma run ativa. Encerre-a primeiro.",
                            headers={"X-Error-Code": "RUN_ALREADY_ACTIVE"})

    conc = await db.scalar(select(Concurso).where(Concurso.id == body.concurso_id))
    if not conc:
        raise HTTPException(404, "Concurso não encontrado", headers={"X-Error-Code": "NOT_FOUND"})

    stats = BUILD_STATS[body.build_type]
    enemy = _make_enemy(0)

    run = Run(
        user_id=current_user.id, concurso_id=body.concurso_id,
        build_type=body.build_type, status=RunStatus.active,
        enemy_state=enemy.model_dump(),
        player_state_snapshot={**stats, "hp": stats["base_hp"], "max_hp": stats["base_hp"]},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    questions = await _pick_questions(body.concurso_id, 10, db)
    return StartRunResponse(run_id=run.id, questions=[_q_to_out(q) for q in questions], enemy=enemy)


@router.post("/{run_id}/answer", response_model=AnswerResponse)
async def answer_question(
    run_id: uuid.UUID, body: AnswerRequest, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_idempotency_key: str | None = Header(default=None),
):
    # Idempotency check
    if x_idempotency_key:
        existing = await db.scalar(
            select(RunAnswer).where(RunAnswer.idempotency_key == x_idempotency_key))
        if existing:
            # Return same result — simplified: return from stored run state
            raise HTTPException(409, "Resposta já registrada",
                                headers={"X-Error-Code": "QUESTION_ALREADY_ANSWERED"})

    run = await db.scalar(select(Run).where(Run.id == run_id, Run.user_id == current_user.id))
    if not run:
        raise HTTPException(404, "Run não encontrada", headers={"X-Error-Code": "NOT_FOUND"})
    if run.status == RunStatus.ended:
        raise HTTPException(400, "Run já encerrada", headers={"X-Error-Code": "RUN_ALREADY_ENDED"})

    # Check not already answered in this run
    already = await db.scalar(
        select(RunAnswer).where(RunAnswer.run_id == run_id, RunAnswer.question_id == body.question_id))
    if already:
        raise HTTPException(409, "Questão já respondida nesta run",
                            headers={"X-Error-Code": "QUESTION_ALREADY_ANSWERED"})

    q = await db.get(Question, body.question_id)
    if not q:
        raise HTTPException(404, "Questão não encontrada", headers={"X-Error-Code": "NOT_FOUND"})

    correct = body.chosen_index == q.correct_index
    snap = run.player_state_snapshot
    enemy = run.enemy_state
    build_stats = BUILD_STATS.get(run.build_type, BUILD_STATS["guerreiro"])

    # Combat calculations
    crit = correct and random.random() < build_stats["crit_chance"]
    dmg_dealt = int(build_stats["base_dmg"] * (2.0 if crit else 1.0)) if correct else 0
    enemy_dmg = int(15 * enemy.get("damage_modifier", 1.0))
    dmg_taken = enemy_dmg if not correct else 0
    gold_gained = int(enemy.get("gold_reward", 10) * 0.2) if correct else 0
    xp_gained = 10 if correct else 0

    # Update player HP
    new_player_hp = max(0, snap.get("hp", 100) - dmg_taken)
    new_enemy_hp = max(0, enemy.get("hp", 100) - dmg_dealt)
    enemy_dead = new_enemy_hp <= 0
    chest_available = enemy_dead and (run.kills + 1) % 3 == 0

    # Persist state
    snap["hp"] = new_player_hp
    enemy["hp"] = new_enemy_hp
    if enemy_dead:
        run.kills += 1
        run.gold_earned += enemy.get("gold_reward", 20)
        run.xp_earned += enemy.get("xp_reward", 30)
        # Spawn next enemy
        new_enemy = _make_enemy(run.kills)
        run.enemy_state = new_enemy.model_dump()
    else:
        run.enemy_state = enemy
    run.player_state_snapshot = snap

    # Update question stats
    if correct:
        q.hits += 1
    else:
        q.misses += 1

    # Record answer
    answer = RunAnswer(
        run_id=run_id, question_id=body.question_id,
        chosen_index=body.chosen_index, is_correct=correct,
        ms_to_answer=body.ms_to_answer, idempotency_key=x_idempotency_key,
    )
    db.add(answer)
    await db.commit()

    tip = q.options[q.correct_index].get("tip", "") if q.options else ""
    return AnswerResponse(
        correct=correct, crit=crit,
        damage_dealt=dmg_dealt, damage_taken=dmg_taken,
        gold_gained=gold_gained, xp_gained=xp_gained,
        enemy_hp=new_enemy_hp, enemy_max_hp=enemy.get("max_hp", 100),
        player_hp=new_player_hp, player_max_hp=snap.get("max_hp", 100),
        enemy_dead=enemy_dead, chest_available=chest_available,
        tip=tip,
    )


@router.post("/{run_id}/end", response_model=RunSummary)
async def end_run(run_id: uuid.UUID, body: EndRunRequest, db: AsyncSession = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    run = await db.scalar(select(Run).where(Run.id == run_id, Run.user_id == current_user.id))
    if not run:
        raise HTTPException(404, "Run não encontrada", headers={"X-Error-Code": "NOT_FOUND"})
    if run.status == RunStatus.ended:
        raise HTTPException(400, "Run já encerrada", headers={"X-Error-Code": "RUN_ALREADY_ENDED"})

    # Calculate accuracy
    total_answers = await db.scalar(
        select(func.count()).where(RunAnswer.run_id == run_id))
    correct_answers = await db.scalar(
        select(func.count()).where(RunAnswer.run_id == run_id, RunAnswer.is_correct == True))
    accuracy = round(correct_answers / total_answers, 2) if total_answers else 0.0
    elapsed = int((datetime.now(timezone.utc) - run.started_at.replace(tzinfo=timezone.utc)).total_seconds())

    run.status = RunStatus.ended
    run.reason = body.reason
    run.accuracy = accuracy
    run.ended_at = datetime.now(timezone.utc)
    run.score = run.kills * 100 + int(accuracy * 500)

    # Update player state
    ps = current_user.player_state
    if ps:
        ps.gold += run.gold_earned
        ps.xp += run.xp_earned
        old_level = ps.level
        ps.level = max(1, ps.xp // 500)
        new_level = ps.level if ps.level > old_level else None
        stats = ps.meta_stats or {}
        stats["total_runs"] = stats.get("total_runs", 0) + 1
        stats["total_kills"] = stats.get("total_kills", 0) + run.kills
        stats["best_run_kills"] = max(stats.get("best_run_kills", 0), run.kills)
        stats["best_run_score"] = max(stats.get("best_run_score", 0), run.score)
        total_q = stats.get("total_questions_answered", 0) + (total_answers or 0)
        stats["total_questions_answered"] = total_q
        ps.meta_stats = stats
    else:
        new_level = None

    await db.commit()
    return RunSummary(run_id=run.id, gold_earned=run.gold_earned, xp_earned=run.xp_earned,
                      kills=run.kills, accuracy=accuracy, time_seconds=elapsed, new_level=new_level)


@router.get("", response_model=RunListResponse)
async def list_runs(page: int = 1, per_page: int = 20, db: AsyncSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    stmt = select(Run).where(Run.user_id == current_user.id).order_by(Run.started_at.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    items_q = await db.scalars(stmt.offset((page - 1) * per_page).limit(per_page))
    items = [RunOut.model_validate(r) for r in items_q]
    return RunListResponse(page=page, per_page=per_page, total=total,
                           has_next=(page * per_page) < total, items=items)
