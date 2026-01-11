from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
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
