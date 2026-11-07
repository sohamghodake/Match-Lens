#!/bin/sh
# Production entrypoint (Render): apply migrations, then serve. Render's free plan has no
# pre-deploy step, and with a single instance, migrating at boot is safe. Set
# RUN_MIGRATIONS=false to skip (e.g. when migrations are run separately).
set -e
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  alembic upgrade head
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*'
