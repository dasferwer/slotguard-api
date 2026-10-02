"""Восстановить снимок в пустую БД и проверить HTTP-контракт через отдельный API."""

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def compose(*args, **kwargs):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, timeout=180, **kwargs)


def sql(statement, database="slotguard"):
    return compose(
        "exec",
        "-T",
        "database",
        "psql",
        "-U",
        "slotguard",
        "-d",
        database,
        "-X",
        "-A",
        "-t",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        statement,
        capture_output=True,
        text=True,
    ).stdout.strip()


def snapshot(database):
    tables = sql(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
        database,
    ).splitlines()
    result = {}
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        result[table] = json.loads(
            sql(
                "SELECT COALESCE(jsonb_agg(row ORDER BY row::text),'[]'::jsonb) "
                f"FROM (SELECT to_jsonb(t) AS row FROM {quoted} t) s",
                database,
            )
        )
    return result


def call(base, method, path, *, data=None, token=None, key=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    request = Request(
        base + path,
        method=method,
        headers=headers,
        data=json.dumps(data).encode() if data is not None else None,
    )
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except HTTPError as error:
        return error.code, json.load(error)


def wait_api(base):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if call(base, "GET", "/health")[0] == 200:
                return
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.2)
    raise TimeoutError("Восстановленный API не запустился")


def expect(result, status):
    assert result[0] == status, result
    return result[1]


def verify_api_address(base):
    published = compose("port", "api", "8000", capture_output=True, text=True).stdout.splitlines()
    address = urlsplit(base)
    matches = any(
        item in (f"127.0.0.1:{address.port}", f"0.0.0.0:{address.port}") for item in published
    )
    if (
        not matches
        or address.scheme != "http"
        or address.hostname not in ("127.0.0.1", "localhost")
        or address.path
        or address.query
        or address.fragment
        or address.username is not None
        or address.password is not None
    ):
        raise SystemExit("BASE_URL не соответствует API выбранного proof-проекта")


def cleanup(restored_container, database):
    errors = []

    def exists(container):
        return subprocess.check_output(
            ["docker", "container", "ls", "-aq", "--filter", "id=" + container],
            text=True,
            timeout=30,
        ).strip()

    try:
        if restored_container and exists(restored_container):
            result = subprocess.run(
                ["docker", "rm", "-f", restored_container],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # --rm мог удалить контейнер между проверкой наличия и командой rm.
            if result.returncode and exists(restored_container):
                raise RuntimeError("Не удалось удалить временный API: " + result.stderr.strip())
    except Exception as error:
        errors.append(str(error))
    try:
        sql(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)', "postgres")
    except Exception as error:
        errors.append("Не удалось удалить восстановленную БД: " + str(error))
    return errors


def main():
    project = os.environ.get("COMPOSE_PROJECT_NAME", "")
    if not project.startswith("proof-"):
        raise SystemExit("Нужен отдельный COMPOSE_PROJECT_NAME с префиксом proof-")
    base = os.environ.get("BASE_URL", "http://127.0.0.1:8010")
    verify_api_address(base)
    database = "slotguard_restore_" + uuid4().hex
    restored_container = None
    credentials = {
        "email": "restore-" + uuid4().hex + "@example.com",
        "password": "RestoreDemoPassword123!",
        "full_name": "Проверка восстановления",
    }
    expect(call(base, "POST", "/api/v1/auth/register", data=credentials), 201)
    token = expect(call(base, "POST", "/api/v1/auth/login", data=credentials), 200)["access_token"]
    admin = expect(
        call(
            base,
            "POST",
            "/api/v1/auth/login",
            data={
                "email": os.environ.get("SLOTGUARD_ADMIN_EMAIL", "admin@example.com"),
                "password": os.environ.get("SLOTGUARD_ADMIN_PASSWORD", "ChangeMe123!"),
            },
        ),
        200,
    )["access_token"]
    room = expect(
        call(
            base,
            "POST",
            "/api/v1/rooms",
            token=admin,
            data={
                "name": "Restore " + uuid4().hex,
                "location": "Изолированный стенд",
                "capacity": 4,
            },
        ),
        201,
    )
    start = datetime.now(UTC) + timedelta(days=1)
    payload = {
        "room_id": room["id"],
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=1)).isoformat(),
        "purpose": "Снимок",
    }
    key = "restore-" + uuid4().hex
    booking = expect(
        call(base, "POST", "/api/v1/bookings", token=token, key=key, data=payload), 201
    )
    before = snapshot("slotguard")
    assert any(row["id"] == booking["id"] for row in before["bookings"])
    try:
        sql(f'CREATE DATABASE "{database}"', "postgres")
        assert not snapshot(database), "Целевая БД должна быть пустой до восстановления"
        with TemporaryDirectory(prefix="slotguard-backup-") as temporary:
            backup = Path(temporary) / "snapshot.dump"
            with backup.open("wb") as output:
                compose(
                    "exec",
                    "-T",
                    "database",
                    "pg_dump",
                    "-U",
                    "slotguard",
                    "-d",
                    "slotguard",
                    "-Fc",
                    stdout=output,
                    stderr=subprocess.PIPE,
                )
            with backup.open("rb") as stream:
                backup_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            with backup.open("rb") as source:
                compose(
                    "exec",
                    "-T",
                    "database",
                    "pg_restore",
                    "-U",
                    "slotguard",
                    "--exit-on-error",
                    "--no-owner",
                    "-d",
                    database,
                    stdin=source,
                    capture_output=True,
                )
        restored = snapshot(database)
        assert before == restored, "Потеря или изменение данных при восстановлении"
        # Отдельный процесс API получает только URL восстановленной базы.
        restored_container = compose(
            "run",
            "--rm",
            "--detach",
            "--no-deps",
            "--publish",
            "127.0.0.1::8000",
            "--env",
            f"SLOTGUARD_DATABASE_URL=postgresql+psycopg://slotguard:slotguard@database:5432/{database}",
            "api",
            capture_output=True,
            text=True,
        ).stdout.strip()
        ports = json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{json .NetworkSettings.Ports}}",
                    restored_container,
                ],
                text=True,
            )
        )
        restored_base = "http://127.0.0.1:" + ports["8000/tcp"][0]["HostPort"]
        wait_api(restored_base)
        replay = expect(
            call(restored_base, "POST", "/api/v1/bookings", token=token, key=key, data=payload), 201
        )
        assert replay == booking, "Повтор должен вернуть сохранённый исходный ответ"
        expect(
            call(
                restored_base,
                "POST",
                "/api/v1/bookings",
                token=token,
                key=uuid4().hex,
                data=payload,
            ),
            409,
        )
        assert snapshot(database) == restored, "Повтор и конфликт не должны изменить снимок"
        # Новая запись доказывает, что проверялся восстановленный, а не исходный API.
        adjacent = {
            **payload,
            "starts_at": payload["ends_at"],
            "ends_at": (start + timedelta(hours=2)).isoformat(),
        }
        created = expect(
            call(
                restored_base,
                "POST",
                "/api/v1/bookings",
                token=token,
                key=uuid4().hex,
                data=adjacent,
            ),
            201,
        )
        assert sql(f"SELECT count(*) FROM bookings WHERE id='{created['id']}'", database) == "1"
        assert sql(f"SELECT count(*) FROM bookings WHERE id='{created['id']}'") == "0"
        print(
            json.dumps(
                {
                    "scenario": "backup_restore",
                    "full_snapshot_equal": True,
                    "tables": {table: len(rows) for table, rows in restored.items()},
                    "backup_sha256": backup_hash,
                    "idempotent_replay": True,
                    "overlap_rejected": True,
                    "restored_api_database_verified": True,
                    "source_database_preserved": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        errors = cleanup(restored_container, database)
        if errors:
            print("Ошибки очистки: " + "; ".join(errors), file=sys.stderr)
            # При сбое сценария сохраняем его причину; при успехе сбой очистки даёт ненулевой exit.
            if sys.exc_info()[0] is None:
                raise RuntimeError("Очистка ресурсов не завершена")


if __name__ == "__main__":
    main()
