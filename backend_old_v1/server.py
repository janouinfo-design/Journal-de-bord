from fastapi import FastAPI, APIRouter, Request, Response
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List
import uuid
from datetime import datetime, timezone
import httpx


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Upstream Logitrak API (existing backend). The mobile (native) app calls this
# API directly; the reverse proxy below exists ONLY so the WEB PREVIEW can reach
# the API without hitting browser CORS restrictions. It adds NO business logic
# and fabricates NO data — it forwards requests and returns real responses as-is.
UPSTREAM_BASE = os.environ.get('LOGITRAK_UPSTREAM', 'https://journal.logitrak.ch').rstrip('/')

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Ignore MongoDB's _id field

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)

    # Convert to dict and serialize datetime to ISO string for MongoDB
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()

    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    # Exclude MongoDB's _id field from the query results
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)

    # Convert ISO string timestamps back to datetime objects
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])

    return status_checks


# ---------------------------------------------------------------------------
# Reverse proxy for the Logitrak Livre-de-Bord API (WEB PREVIEW ONLY).
# Forwards /api/livre/... and /api/auth/... to the real upstream, preserving
# method, JSON body and the Authorization (Bearer JWT) header. Multi-tenant
# isolation is enforced by the UPSTREAM server via the JWT — we never inject
# or trust any tenant id here.
# ---------------------------------------------------------------------------
_PROXY_PREFIXES = ("auth/", "livre/")
_HOP_BY_HOP = {
    "content-length", "transfer-encoding", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade", "host",
}


@api_router.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def logitrak_proxy(full_path: str, request: Request):
    # Only proxy known Logitrak API namespaces; everything else -> 404.
    if not any(full_path.startswith(p) for p in _PROXY_PREFIXES):
        return Response(content='{"detail":"Not Found"}', status_code=404,
                        media_type="application/json")

    upstream_url = f"{UPSTREAM_BASE}/api/{full_path}"

    # Forward safe headers only.
    fwd_headers = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in _HOP_BY_HOP or lk == "host":
            continue
        fwd_headers[k] = v

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=20.0) as hc:
            upstream_resp = await hc.request(
                request.method,
                upstream_url,
                params=dict(request.query_params),
                content=body if body else None,
                headers=fwd_headers,
            )
    except httpx.RequestError as e:
        logger.warning("Proxy upstream error for %s: %s", upstream_url, e)
        return Response(
            content='{"detail":"Le serveur Logitrak est momentanément indisponible."}',
            status_code=502,
            media_type="application/json",
        )

    # Return upstream response as-is (filter hop-by-hop headers).
    resp_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=upstream_resp.headers.get("content-type", "application/json"),
    )


# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
