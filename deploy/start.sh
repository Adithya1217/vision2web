#!/bin/bash
# Starts FastAPI (internal) and Next.js (public) in one container. If either exits, the container
# exits so the platform restarts it.
set -euo pipefail
APP_DIR="${APP_DIR:-/app}"

cd "$APP_DIR/backend"
alembic upgrade head
if [ "${SEED_DEMO:-false}" = "true" ]; then
  python -m scripts.seed || echo "Demo seed failed; continuing without demo data."
fi
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers &

# Wait (up to 60s) for the API so the public server never proxies to a closed port.
python - <<'PY'
import socket, time
for _ in range(120):
    try:
        socket.create_connection(("127.0.0.1", 8000), timeout=1).close()
        break
    except OSError:
        time.sleep(0.5)
PY

cd "$APP_DIR/frontend"
PORT="${PORT:-10000}" HOSTNAME=0.0.0.0 node server.js &

wait -n
exit $?
