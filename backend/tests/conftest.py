"""Shared pytest config — loads env so tests can reach the backend."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # /app

# Load /app/backend/.env (JWT_SECRET, MONGO_URL, …) AND /app/frontend/.env
# (REACT_APP_BACKEND_URL used to compose the API base URL).
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / "backend" / ".env")
    load_dotenv(ROOT / "frontend" / ".env")
except Exception:
    pass

# Make the backend `app` package importable from any test.
sys.path.insert(0, str(ROOT / "backend"))
