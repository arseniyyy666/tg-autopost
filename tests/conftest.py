import os

# Must be set before the app is imported; no real DB is needed for these tests.
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db?sslmode=require")
