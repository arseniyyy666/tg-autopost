import os

# Must be set before the app is imported; no real DB or bot is needed for unit tests.
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db?sslmode=require")
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_TESTS")
os.environ.setdefault("RUN_BOT", "false")
os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SESSION_KEYS", "1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
