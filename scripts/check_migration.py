"""Проверить сохранность бизнес-данных при откате и повторном применении миграции."""

import hashlib
import json
import subprocess

from sqlalchemy import text

from slotguard.db import engine


def snapshot() -> str:
    data = {}
    with engine.connect() as connection:
        for table in ("users", "rooms", "bookings", "audit_logs"):
            rows = (
                connection.execute(
                    text(f"SELECT to_jsonb(t) - 'version' FROM {table} t ORDER BY id")
                )
                .scalars()
                .all()
            )
            data[table] = rows
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def main() -> None:
    if engine.url.database != "slotguard_test":
        raise RuntimeError("Проверка миграции разрешена только в БД slotguard_test")
    before = snapshot()
    subprocess.run(["alembic", "downgrade", "20260831_0001"], check=True)
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    if snapshot() != before:
        raise RuntimeError("После миграции изменились бизнес-данные")
    print("Бизнес-данные сохранены при откате и повторном применении миграции")


if __name__ == "__main__":
    main()
