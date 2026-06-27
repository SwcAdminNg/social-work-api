from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.common.responses import ApiErrorResponse
from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.health.router import router as health_router
from app.modules.user.router import router as user_router

app = FastAPI(
    title=settings.app_name,
    description="Social Workers API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,  # hide the "Schemas" section
        "docExpansion": "none",  # collapse all tags/endpoints by default
    },
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ApiErrorResponse(
            message="Validation error",
            errors=[{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()],
        ).model_dump(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiErrorResponse(message=str(exc.detail)).model_dump(),
        headers=exc.headers,
    )


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(user_router)
