from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from slotguard.api.dependencies import CurrentUser, DbSession
from slotguard.core.security import create_access_token, hash_password, verify_password
from slotguard.models import User, UserRole
from slotguard.schemas.auth import LoginRequest, TokenResponse
from slotguard.schemas.user import UserCreate, UserRead
from slotguard.services.audit import add_audit_log

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: DbSession) -> User:
    email = payload.email.lower()
    existing = db.scalar(select(User.id).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already used")

    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=UserRole.USER,
    )
    db.add(user)
    db.flush()
    add_audit_log(
        db,
        actor_id=user.id,
        action="user.registered",
        entity_type="user",
        entity_id=user.id,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already used",
        ) from exc
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    email = payload.email.lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return TokenResponse(access_token=create_access_token(user.id, str(user.role)))


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: CurrentUser) -> User:
    return current_user
