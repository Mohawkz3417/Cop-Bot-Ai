@echo off
REM One-command launcher for CopBot AI (Windows).
cd /d "%~dp0"

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
echo Installing dependencies...
pip install -q --upgrade pip
pip install -q -r requirements.txt

if not exist ".env" (
  copy .env.example .env
  echo Created .env from .env.example — add your GROQ_API_KEY there for full AI answers.
)

echo.
echo Starting CopBot AI on http://localhost:8000 ...
python -m backend.main
