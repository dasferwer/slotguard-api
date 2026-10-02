"""Реальные HTTP/Docker/PostgreSQL границы безопасности recovery; запускать на proof-стенде."""

import os
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

import recovery_smoke as recovery


def test_foreign_http_address_is_rejected_before_registration():
    requests = []

    class ForeignAPI(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(self.path)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"detail":"foreign API"}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), ForeignAPI)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [sys.executable, "scripts/recovery_smoke.py"],
            cwd=recovery.ROOT,
            env={**os.environ, "BASE_URL": f"http://127.0.0.1:{server.server_port}"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0
        assert requests == [], "Recovery отправил POST в API другого стенда"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_already_removed_api_does_not_leave_restore_database():
    database = "slotguard_restore_test_" + uuid4().hex
    recovery.sql(f'CREATE DATABASE "{database}"', "postgres")
    try:
        # Такого ID нет; это состояние API после автоматического удаления через --rm.
        errors = recovery.cleanup(uuid4().hex + uuid4().hex, database)
        assert not errors, errors
        assert (
            recovery.sql(f"SELECT count(*) FROM pg_database WHERE datname='{database}'", "postgres")
            == "0"
        )
    finally:
        recovery.sql(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)', "postgres")


def test_container_removal_failure_still_drops_restore_database(tmp_path, monkeypatch):
    container = recovery.compose("ps", "-q", "api", capture_output=True, text=True).stdout.strip()
    assert container
    database = "slotguard_restore_test_" + uuid4().hex
    recovery.sql(f'CREATE DATABASE "{database}"', "postgres")
    docker = shutil.which("docker")
    assert docker
    # Нельзя остановить весь daemon: DROP тоже идёт через Docker. Инъекция затрагивает
    # только rm; inspect/ps/psql выполняются настоящим CLI и настоящей БД.
    wrapper = tmp_path / "docker"
    wrapper.write_text(
        f"#!{sys.executable}\nimport os,sys\n"
        "if sys.argv[1:2] == ['rm']:\n    sys.exit(71)\n"
        f"os.execv({docker!r}, [{docker!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    try:
        try:
            errors = recovery.cleanup(container, database)
        except subprocess.CalledProcessError:
            errors = ["Инъекция ошибки удаления контейнера"]
        assert errors, "Инъекция rm должна быть замечена"
        assert (
            recovery.sql(f"SELECT count(*) FROM pg_database WHERE datname='{database}'", "postgres")
            == "0"
        ), "Ошибка rm не должна пропускать удаление БД"
    finally:
        recovery.sql(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)', "postgres")
