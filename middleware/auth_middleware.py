"""
Middleware de autenticación por X-Service-Key (capa de borde).

Usa verify_service_key() de middleware.auth como fuente de verdad.
Rutas exentas: /health, /docs, /openapi.json, /redoc.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import get_settings
from middleware.auth import verify_service_key

settings = get_settings()

_RUTAS_EXENTAS = frozenset(["/health", "/docs", "/openapi.json", "/redoc"])


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.AUTH_ENABLED:
            return await call_next(request)

        if request.url.path in _RUTAS_EXENTAS:
            return await call_next(request)

        key = request.headers.get("X-Service-Key", "")
        if not verify_service_key(key or None):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing X-Service-Key"},
            )

        return await call_next(request)
