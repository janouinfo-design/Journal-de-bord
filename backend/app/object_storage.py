"""Emergent Object Storage — stockage persistant des fichiers uploadés.

Remplace le stockage pod-local (perdu au redéploiement). Un seul bucket par
compte : tous les chemins sont préfixés APP_PREFIX. Pas d'API delete côté
storage → soft-delete via les métadonnées Mongo (source de vérité).
"""
from __future__ import annotations

import os

import httpx

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
APP_PREFIX = "logitrak-journal"

_storage_key: str | None = None


async def init_storage(force: bool = False) -> str:
    """Clé de session storage, mintée une fois et réutilisée (force = re-mint)."""
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    emergent_key = os.environ.get("EMERGENT_LLM_KEY")
    if not emergent_key:
        raise RuntimeError("EMERGENT_LLM_KEY manquante — object storage indisponible")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{STORAGE_URL}/init", json={"emergent_key": emergent_key})
        r.raise_for_status()
        _storage_key = r.json()["storage_key"]
    return _storage_key


async def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Upload. Retourne {"path", "size", "etag"} — utiliser result["path"] comme canonical."""
    key = await init_storage()
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.put(f"{STORAGE_URL}/objects/{path}",
                             headers={"X-Storage-Key": key, "Content-Type": content_type},
                             content=data)
        if r.status_code == 404:  # storage_key inactive → re-mint une fois
            key = await init_storage(force=True)
            r = await client.put(f"{STORAGE_URL}/objects/{path}",
                                 headers={"X-Storage-Key": key, "Content-Type": content_type},
                                 content=data)
        r.raise_for_status()
        return r.json()


async def get_object(path: str) -> tuple[bytes, str] | None:
    """Download. None si l'objet n'existe pas."""
    key = await init_storage()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{STORAGE_URL}/objects/{path}",
                             headers={"X-Storage-Key": key})
        if r.status_code == 404:
            key = await init_storage(force=True)
            r = await client.get(f"{STORAGE_URL}/objects/{path}",
                                 headers={"X-Storage-Key": key})
            if r.status_code == 404:
                return None
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type", "application/octet-stream")
