import hmac
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import AppConfig
from .dependencies import get_config

security = HTTPBearer()

async def require_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    config: AppConfig = Depends(get_config),
):
    if credentials is None or credentials.scheme.lower() != 'bearer':
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid auth scheme')
    if credentials.credentials != config.auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid token')
    return True


CONFIRM_PASSWORD_HEADER = "X-Confirm-Password"


async def require_protected_password(
    confirm_password: str | None = Header(
        None, alias=CONFIRM_PASSWORD_HEADER,
        description="Must match `protected_commands_password` from the server configuration. "
        "Guards against accidental use; it is not a security boundary.",
    ),
    config: AppConfig = Depends(get_config),
) -> bool:
    """Confirm a protected command with the shared password from the configuration."""
    if config.protected_commands_password is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Protected commands are disabled: protected_commands_password is not configured",
        )
    if confirm_password is None or not hmac.compare_digest(
        confirm_password.encode(), config.protected_commands_password.encode(),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing or wrong {CONFIRM_PASSWORD_HEADER}",
        )
    return True


PROTECTED_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Unauthorized (missing or invalid auth token)"},
    403: {
        "description": "Protected commands disabled, or missing or wrong X-Confirm-Password. Nothing was done.",
        "content": {"application/json": {"examples": {
            "wrong_password": {"summary": "Missing or wrong X-Confirm-Password", "value": {"detail": {
                "code": 403, "reason": "forbidden", "message": "Missing or wrong X-Confirm-Password",
            }}},
            "disabled": {"summary": "protected_commands_password not configured", "value": {"detail": {
                "code": 403, "reason": "forbidden",
                "message": "Protected commands are disabled: protected_commands_password is not configured",
            }}},
        }}},
    },
}


def maintenance_router(prefix: str = "") -> APIRouter:
    """Router for operator-only endpoints (Swagger group Maintenance).

    Rule: every Maintenance endpoint needs the Bearer token and the
    X-Confirm-Password header. The router enforces both, so a new endpoint
    added here cannot forget them (checked by test_network_sections).
    """
    return APIRouter(
        prefix=prefix, tags=["Maintenance"], responses=PROTECTED_RESPONSES,
        dependencies=[Depends(require_token), Depends(require_protected_password)],
    )
