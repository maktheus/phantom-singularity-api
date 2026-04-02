import uuid
import enum
from datetime import datetime
from sqlalchemy import String, ForeignKey, Integer, Float, Boolean, Enum, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class UserRole(str, enum.Enum):
    player = "player"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)  # null for Google-only users
    google_sub: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.player, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    player_state: Mapped["PlayerState"] = relationship(back_populates="user", uselist=False, lazy="selectin")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", lazy="noload")
    runs: Mapped[list["Run"]] = relationship(back_populates="user", lazy="noload")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class PlayerState(Base):
    __tablename__ = "player_states"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    gold: Mapped[int] = mapped_column(Integer, default=0)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    permanent_upgrades: Mapped[dict] = mapped_column(JSONB, default=dict)
    meta_stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="player_state")


class Concurso(Base):
    __tablename__ = "concursos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    area: Mapped[str] = mapped_column(String(100), nullable=False)
    emoji: Mapped[str] = mapped_column(String(10), nullable=False)
    color_hex: Mapped[str] = mapped_column(String(7), nullable=False)

    questions: Mapped[list["Question"]] = relationship(back_populates="concurso", lazy="noload")
    exams: Mapped[list["Exam"]] = relationship(back_populates="concurso", lazy="noload")


class ExamStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    error = "error"


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    concurso_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concursos.id"), nullable=False)
    banca: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    cargo: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[ExamStatus] = mapped_column(Enum(ExamStatus), default=ExamStatus.pending)
    parsed_count: Mapped[int] = mapped_column(Integer, default=0)
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    concurso: Mapped["Concurso"] = relationship(back_populates="exams")
    questions: Mapped[list["Question"]] = relationship(back_populates="exam", lazy="noload")


class Difficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    concurso_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concursos.id"), nullable=False)
    exam_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exams.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{index,text,tip}]
    correct_index: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    difficulty: Mapped[Difficulty] = mapped_column(Enum(Difficulty), default=Difficulty.medium)
    source: Mapped[str] = mapped_column(String(10), default="real")  # real | ai
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    misses: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    concurso: Mapped["Concurso"] = relationship(back_populates="questions")
    exam: Mapped["Exam"] = relationship(back_populates="questions")

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 2) if total > 0 else 0.0


class RunStatus(str, enum.Enum):
    active = "active"
    ended = "ended"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    concurso_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concursos.id"), nullable=False)
    build_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.active)
    kills: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)
    gold_earned: Mapped[int] = mapped_column(Integer, default=0)
    xp_earned: Mapped[int] = mapped_column(Integer, default=0)
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str | None] = mapped_column(String(20), nullable=True)  # death|victory|abandoned
    items_acquired: Mapped[list] = mapped_column(JSONB, default=list)
    enemy_state: Mapped[dict] = mapped_column(JSONB, default=dict)  # current enemy hp etc
    player_state_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="runs")
    answers: Mapped[list["RunAnswer"]] = relationship(back_populates="run", lazy="noload")


class RunAnswer(Base):
    __tablename__ = "run_answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"), nullable=False)
    chosen_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ms_to_answer: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["Run"] = relationship(back_populates="answers")
