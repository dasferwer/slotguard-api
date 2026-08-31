from fastapi import APIRouter

from slotguard.api.routes import auth, bookings, health, rooms

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/api/v1")
api_router.include_router(rooms.router, prefix="/api/v1")
api_router.include_router(bookings.router, prefix="/api/v1")
