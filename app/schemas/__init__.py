import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, model_validator
from app.models import UserRole, Difficulty, ExamStatus, RunStatus


# ─── Auth ─────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    id_token: str


class UserOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: UserRole
    avatar_url: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    user: UserOut


# ─── Player State ──────────────────────────────────────────────────────────────

class PlayerStats(BaseModel):
    total_runs: int = 0
    total_kills: int = 0
    total_questions_answered: int = 0
    accuracy: float = 0.0
    best_run_kills: int = 0
    best_run_score: int = 0
    study_streak_days: int = 0


class PlayerStateOut(BaseModel):
    gold: int
    xp: int
    level: int
    permanent_upgrades: dict
    stats: PlayerStats


class MeResponse(BaseModel):
    user: UserOut
    player_state: PlayerStateOut | None


class UpgradeRequest(BaseModel):
    upgrade_key: str
    levels: int = Field(ge=1, le=5)


class UpgradeResponse(BaseModel):
    permanent_upgrades: dict
    gold_remaining: int


# ─── Concurso ─────────────────────────────────────────────────────────────────

class ConcursoCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=50, pattern=r"^[a-z_]+$")
    name: str = Field(min_length=2, max_length=200)
    area: str = Field(min_length=2, max_length=100)
    emoji: str = Field(max_length=10)
    color_hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class ConcursoOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    area: str
    emoji: str
    color_hex: str

    model_config = {"from_attributes": True}


# ─── Questions ────────────────────────────────────────────────────────────────

class QuestionOption(BaseModel):
    index: int = Field(ge=0, le=4)
    text: str = Field(min_length=1)
    tip: str = Field(min_length=1)


class QuestionCreate(BaseModel):
    text: str = Field(min_length=20)
    options: list[QuestionOption] = Field(min_length=5, max_length=5)
    correct_index: int = Field(ge=0, le=4)
    topic: str = Field(min_length=2, max_length=200)
    difficulty: Difficulty = Difficulty.medium
    concurso_id: uuid.UUID
    exam_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_options_count(self):
        if len(self.options) != 5:
            raise ValueError("Exatamente 5 opções são necessárias")
        return self


class QuestionUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=20)
    options: list[QuestionOption] | None = None
    correct_index: int | None = Field(default=None, ge=0, le=4)
    topic: str | None = None
    difficulty: Difficulty | None = None


class QuestionOut(BaseModel):
    id: uuid.UUID
    text: str
    options: list[dict]
    correct_index: int
    topic: str
    difficulty: Difficulty
    source: str
    ai_generated: bool
    concurso_slug: str | None = None
    exam_id: uuid.UUID | None
    hits: int
    misses: int
    hit_rate: float
    created_at: datetime

    model_config = {"from_attributes": True}


class QuestionListResponse(BaseModel):
    page: int
    per_page: int
    total: int
    has_next: bool
    items: list[QuestionOut]


class GenerateQuestionsRequest(BaseModel):
    concurso_slug: str
    topic: str
    count: int = Field(ge=1, le=20)


# ─── Exam ─────────────────────────────────────────────────────────────────────

class ExamOut(BaseModel):
    id: uuid.UUID
    banca: str
    year: int
    cargo: str
    concurso_slug: str | None = None
    status: ExamStatus
    parsed_count: int
    total_pages: int
    error_msg: str | None
    ingested_by: uuid.UUID | None
    ingested_at: datetime

    model_config = {"from_attributes": True}


class ExamStatusOut(BaseModel):
    status: ExamStatus
    parsed_count: int
    total_pages: int
    error_msg: str | None


class ExamDetailOut(BaseModel):
    exam: ExamOut
    questions: list[QuestionOut]
    total_questions: int


class ExamListResponse(BaseModel):
    page: int
    per_page: int
    total: int
    has_next: bool
    items: list[ExamOut]


# ─── Run / Gameplay ───────────────────────────────────────────────────────────

class EnemyConfig(BaseModel):
    name: str
    emoji: str
    hp: int
    max_hp: int
    modifier: str
    modifier_label: str
    damage_modifier: float
    gold_reward: int
    xp_reward: int


class StartRunRequest(BaseModel):
    concurso_id: uuid.UUID
    build_type: str = Field(pattern=r"^(guerreiro|mago|suporte)$")


class StartRunResponse(BaseModel):
    run_id: uuid.UUID
    questions: list[QuestionOut]
    enemy: EnemyConfig


class AnswerRequest(BaseModel):
    question_id: uuid.UUID
    chosen_index: int = Field(ge=0, le=4)
    ms_to_answer: int = Field(ge=0)


class AnswerResponse(BaseModel):
    correct: bool
    crit: bool
    damage_dealt: int
    damage_taken: int
    gold_gained: int
    xp_gained: int
    enemy_hp: int
    enemy_max_hp: int
    player_hp: int
    player_max_hp: int
    enemy_dead: bool
    chest_available: bool
    tip: str


class EndRunRequest(BaseModel):
    reason: str = Field(pattern=r"^(death|victory|abandoned)$")


class RunSummary(BaseModel):
    run_id: uuid.UUID
    gold_earned: int
    xp_earned: int
    kills: int
    accuracy: float
    time_seconds: int
    new_level: int | None


class RunOut(BaseModel):
    id: uuid.UUID
    concurso_id: uuid.UUID
    build_type: str
    status: RunStatus
    kills: int
    score: int
    gold_earned: int
    accuracy: float
    reason: str | None
    started_at: datetime
    ended_at: datetime | None

    model_config = {"from_attributes": True}


class RunListResponse(BaseModel):
    page: int
    per_page: int
    total: int
    has_next: bool
    items: list[RunOut]
