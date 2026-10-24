#!/usr/bin/env bash
# One-command launcher for CopBot AI (macOS / Linux).
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
echo "Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example — add your GROQ_API_KEY there for full AI answers."
fi

echo ""
echo "Starting CopBot AI on http://localhost:8000 ..."
python -m backend.main
