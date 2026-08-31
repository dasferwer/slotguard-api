import logging

from sqlalchemy import func, select

from slotguard.config import get_settings
from slotguard.core.security import hash_password, verify_password
from slotguard.db import SessionLocal
from slotguard.models import Room, User, UserRole

logger = logging.getLogger(__name__)

SEED_ROOMS = (
    {
        "name": "Atlas",
        "location": "Floor 2, east wing",
        "capacity": 8,
        "description": "Meeting room with a large display",
    },
    {
        "name": "Aurora",
        "location": "Floor 3, north wing",
        "capacity": 4,
        "description": "Compact room for interviews and one-to-one meetings",
    },
    {
        "name": "Orion",
        "location": "Floor 5, west wing",
        "capacity": 14,
        "description": "Conference room for team planning",
    },
)


def seed_database() -> None:
    settings = get_settings()
    with SessionLocal.begin() as db:
        admin_email = str(settings.admin_email).lower()
        admin = db.scalar(select(User).where(func.lower(User.email) == admin_email))
        if admin is None:
            admin = User(
                email=admin_email,
                full_name=settings.admin_name,
                password_hash=hash_password(settings.admin_password.get_secret_value()),
                role=UserRole.ADMIN,
            )
            db.add(admin)
        else:
            admin.full_name = settings.admin_name
            admin.role = UserRole.ADMIN
            admin.is_active = True
            if not verify_password(
                settings.admin_password.get_secret_value(),
                admin.password_hash,
            ):
                admin.password_hash = hash_password(settings.admin_password.get_secret_value())

        for room_data in SEED_ROOMS:
            room = db.scalar(select(Room).where(Room.name == room_data["name"]))
            if room is None:
                db.add(Room(**room_data))
            else:
                for field, value in room_data.items():
                    setattr(room, field, value)
                room.is_active = True

    logger.info("Seed completed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_database()
