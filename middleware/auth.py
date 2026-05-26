"""
Autenticación por X-Service-Key.

Fuente de verdad: verify_service_key() — usada por el middleware (capa de borde)
y por la dependencia require_service_key (Swagger Authorize + validación en rutas).
Ambas deben coincidir; no duplicar lógica de comparación en otro sitio.
"""

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from config import get_settings

api_key_header = APIKeyHeader(name="X-Service-Key", auto_error=False)

settings = get_settings()


def verify_service_key(key: str | None) -> bool:
    """
    Valida la clave de servicio.
    Retorna True si AUTH_ENABLED es False o si la clave coincide.
    """
    if not settings.AUTH_ENABLED:
        return True
    if not key or not settings.SERVICE_API_KEY:
        return False
    return key == settings.SERVICE_API_KEY


async def require_service_key(
    api_key: str | None = Security(api_key_header),
) -> str | None:
    """
    Dependencia FastAPI para endpoints protegidos.
    Con AUTH_ENABLED=true, Swagger muestra el botón Authorize.
    """
    if not settings.AUTH_ENABLED:
        return None
    if not verify_service_key(api_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-Service-Key",
        )
    return api_key
