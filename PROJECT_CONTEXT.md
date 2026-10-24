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
telegram_accounts(id, user_id FK cascade, tg_account_id UNIQUE, display_name, username, session_enc bytea, key_version, auth_status, connected_at, last_checked_at),
audit_events(id, user_id FK set null, event_type, meta json w/o secrets, created_at). Migration 0002.
users.terms_accepted_at (consent to account use, enforced by backend before login start). Migration 0003.

## Done
Stage 2: infrastructure, /health, migration, tests, code on GitHub (private).
Stage 3: bot /start registers user, Mini App button, /api/me with initData verification.
Stage 4: connect/disconnect a Telegram account from the Mini App (phone -> code -> optional 2FA), sessions encrypted
with AES-GCM (key rotation via SESSION_KEYS, AAD binds ciphertext to owner), login state in memory with TTL and attempt limits,
disconnect = remote log_out + delete row + audit event. Orphan sessions are revoked if storing fails. QR login NOT done yet.
Stage 4.1: consent stored once per user (not asked each time); UI tells where Telegram delivered the code (app/sms/call).

## Env vars (no values here)
APP_ENV, DATABASE_URL, BOT_TOKEN, WEBAPP_URL, RUN_BOT, INITDATA_MAX_AGE, API_ID, API_HASH, SESSION_KEYS (+ optional limits)

## Run locally (Windows, PowerShell)
.\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt ; alembic upgrade head ; pytest ; uvicorn app.main:app
Mini App needs HTTPS: cloudflared tunnel --url http://localhost:8000, then WEBAPP_URL=https://<tunnel>/webapp/

## Known limits
Railway deploys were paused during their Oct 2026 security incident; developing locally for now.
Rotate any secret ever pasted into a chat.

Tests: `pytest` (41 pass, 2 DB tests skipped). DB integration test wipes the DB: only with RUN_DB_TESTS=1 on a throwaway database.

## Next
Verify Stage 4 on a test account. Then Stage 5: campaigns CRUD (no real sending). Optional later: QR login.
