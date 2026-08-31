from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from slotguard.api.dependencies import DbSession

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
def health(db: DbSession) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(status="ok", database="ok")
