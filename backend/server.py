"""Logitrak Livre de Bord — FastAPI entrypoint."""
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware

from app.db import init_db, close_db, get_db
from app.auth import seed_admin
from app.routes import auth_router, livre_router
from app.routes.admin import router as admin_router
from app.mock_navixy import seed_mock_data
from app.rules import apply_rules_to_all
from app.scheduler import init_scheduler, shutdown_scheduler

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Logitrak — Livre de Bord")

api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"app": "Logitrak — Livre de Bord", "status": "ok"}


@api_router.get("/health")
async def health():
    return {"status": "ok", "service": "journal-logitrak"}


# Sub-routers under /api
api_router.include_router(auth_router)
api_router.include_router(livre_router)
api_router.include_router(admin_router)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    db = init_db()
    await db.users.create_index("email", unique=True)
    await db.trips.create_index("start_time")
    await db.trips.create_index([("classification", 1), ("start_time", -1)])
    await db.trips.create_index("driver_id")
    await db.trips.create_index("vehicle_id")
    await seed_admin()
    from app.tenancy import ensure_tenancy
    await ensure_tenancy(db)
    from app.fuel_engine import ensure_fuel_indexes
    await ensure_fuel_indexes(db)
    from app.fuel_fx import ensure_fx_indexes
    from app.db import get_raw_db
    await ensure_fx_indexes(get_raw_db())
    from app.fuel_statements import ensure_statement_indexes
    await ensure_statement_indexes(get_raw_db())
    from app.fuel_anomalies import ensure_anomaly_indexes
    await ensure_anomaly_indexes(get_raw_db())
    if os.environ.get("SEED_DEMO_DATA", "true").lower() == "true":
        await seed_mock_data(force=False)
    await apply_rules_to_all(db)
    await init_scheduler()
    logger.info("Startup: DB initialised, mock data seeded.")


@app.on_event("shutdown")
async def on_shutdown():
    shutdown_scheduler()
    close_db()
