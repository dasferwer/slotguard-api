from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from slotguard.core.security import decode_access_token
from slotguard.db import get_db
from slotguard.models import User, UserRole

DbSession = Annotated[Session, Depends(get_db)]
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    authentication_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise authentication_error

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = UUID(str(payload.get("sub")))
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise authentication_error from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise authentication_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(current_user: CurrentUser) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role is required",
        )
    return current_user


AdminUser = Annotated[User, Depends(require_admin)]
