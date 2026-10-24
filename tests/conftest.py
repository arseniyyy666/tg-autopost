import os

# Must be set before the app is imported; no real DB or bot is needed for tests.
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db?sslmode=require")
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_TESTS")
os.environ.setdefault("RUN_BOT", "false")
