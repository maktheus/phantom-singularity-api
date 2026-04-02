from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "Erro interno no servidor", "details": None}},
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.headers.get("X-Error-Code", "HTTP_ERROR") if exc.headers else "HTTP_ERROR",
                           "message": exc.detail, "details": None}},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "UNPROCESSABLE_ENTITY",
                           "message": "Dados de entrada inválidos",
                           "details": exc.errors()}},
    )
