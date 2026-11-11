#!/usr/bin/env bash
# Run Django locally with .env.local overriding the production .env.
# Usage: ./run-local.sh                 -> runserver on 127.0.0.1:8000
#        ./run-local.sh migrate         -> any manage.py command
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .env.local ]; then echo ".env.local is missing" >&2; exit 1; fi
if grep -q "CHANGE_ME" .env.local; then echo "Set your local Postgres password in .env.local first (replace CHANGE_ME)." >&2; exit 1; fi
set -a; source .env.local; set +a          # exported vars win over .env (python-dotenv does not override them)
PY=./venv/bin/python
if [ $# -eq 0 ]; then exec "$PY" manage.py runserver 127.0.0.1:8000; fi
exec "$PY" manage.py "$@"
