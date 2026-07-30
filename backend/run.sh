#!/usr/bin/env bash
# 백엔드 기동 스크립트. backend/ 에서 실행할 것.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

[ -f .env ] || { cp .env.example .env; echo "→ .env 를 만들었습니다. UPSTAGE_API_KEY 를 채우세요."; }

exec ./.venv/bin/uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" --reload
