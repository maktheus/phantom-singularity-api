from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.middleware.error_handler import (
    global_exception_handler, http_exception_handler, validation_exception_handler
)
from app.routers.v1 import auth, questions, exams, runs, player, concursos

app = FastAPI(
    title="Phantom Singularity API",
    version="1.0.0",
    docs_url="/docs" if settings.ENV == "development" else None,
    redoc_url="/redoc" if settings.ENV == "development" else None,
    openapi_url="/openapi.json" if settings.ENV == "development" else None,
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:4173",
    "https://maktheus.github.io",
    "capacitor://localhost",      # Capacitor Android WebView
    "ionic://localhost",
]
if settings.ENV != "development":
    ALLOWED_ORIGINS = [o for o in ALLOWED_ORIGINS if "localhost" not in o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Error Handlers ────────────────────────────────────────────────────────────
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# ─── Health ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/health/ready", tags=["Health"])
async def health_ready():
    from app.db.session import engine
    from sqlalchemy import text
    import httpx
    results = {"db": "ok", "ollama": "ok"}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        results["db"] = "unreachable"

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            if r.status_code != 200:
                results["ollama"] = "unreachable"
    except Exception:
        results["ollama"] = "unreachable"

    status_code = 503 if any(v != "ok" for v in results.values()) else 200
    from fastapi.responses import JSONResponse
    return JSONResponse(content=results, status_code=status_code)


# ─── Routers ───────────────────────────────────────────────────────────────────
PREFIX = "/api/v1"
app.include_router(auth.router, prefix=PREFIX)
app.include_router(questions.router, prefix=PREFIX)
app.include_router(exams.router, prefix=PREFIX)
app.include_router(runs.router, prefix=PREFIX)
app.include_router(player.router, prefix=PREFIX)
app.include_router(concursos.router, prefix=PREFIX)
