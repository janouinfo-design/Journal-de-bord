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

import pytest  # noqa: E402

_SHARED_ACCOUNTS = [
    "superadmin@logitrak.ch", "admin@logitrak.ch", "manager@logitrak.ch",
    "chauffeur@logitrak.ch", "paul.test@client.ch", "admin-b@test.ch",
    "lecteur@logitrak.ch",
]


@pytest.fixture(autouse=True, scope="module")
def _reset_login_attempts():
    """La protection brute force (5 échecs/15 min) est volontairement globale.
    Les suites cumulent des logins ratés sur les comptes partagés : on purge le
    compteur au début de chaque module pour éviter les verrous en cascade."""
    try:
        import pymongo
        mc = pymongo.MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=3000)
        mc[os.environ["DB_NAME"]].login_attempts.delete_many(
            {"identifier": {"$in": _SHARED_ACCOUNTS}})
        mc.close()
    except Exception:
        pass
    yield
