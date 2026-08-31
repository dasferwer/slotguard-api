#!/bin/sh
set -eu

alembic upgrade head
python -m slotguard.seed

exec "$@"
