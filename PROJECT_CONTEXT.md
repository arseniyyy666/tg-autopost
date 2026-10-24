# PROJECT_CONTEXT

## Purpose
Telegram bot + Mini App for scheduled auto-messaging from a user's own connected Telegram account.
Only to chats/recipients the user is allowed to write to. No scraping, no FloodWait bypass.

## Stack
Python 3.12, aiogram 3, Telethon (stage 4), FastAPI, SQLAlchemy 2 async + Alembic, PostgreSQL (Neon for dev),
cryptography AES-GCM (stage 4), pydantic-settings, pytest.

## Architecture
One process: aiogram polling + FastAPI + (later) worker loop on PostgreSQL (`next_run_at`, FOR UPDATE SKIP LOCKED).
UI = Mini App (plain HTML/JS in app/webapp, served at /webapp/). Bot = entry point + notifications.
Auth for the Mini App: `Authorization: tma <initData>`, HMAC-verified server-side (app/security/telegram_auth.py).
Telegram login (stage 4): phone/code/2FA form inside the Mini App + QR login. Codes are never typed into chat.

## Files
app/main.py, config.py, api/{deps,routes}.py, bot/{handlers,setup}.py, security/telegram_auth.py,
services/users.py, database/{models,session}.py, webapp/index.html, alembic/, tests/

## DB
users(id, tg_id unique, language, status, created_at). Migration 0001.

## Done
Stage 2: infrastructure, /health, migration, tests, code on GitHub (private).
Stage 3: bot /start registers user, Mini App button, /api/me with initData verification.

## Env vars (no values here)
APP_ENV, DATABASE_URL, BOT_TOKEN, WEBAPP_URL, RUN_BOT, INITDATA_MAX_AGE

## Run locally (Windows, PowerShell)
.\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt ; alembic upgrade head ; pytest ; uvicorn app.main:app
Mini App needs HTTPS: cloudflared tunnel --url http://localhost:8000, then WEBAPP_URL=https://<tunnel>/webapp/

## Known limits
Railway deploys were paused during their Oct 2026 security incident; developing locally for now.
Rotate any secret ever pasted into a chat.

## Next
Stage 4: connect Telegram account (Telethon), encrypted session storage, disconnect/delete session.
