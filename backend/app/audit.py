"""Journal d'audit global — traçabilité des actions sensibles par tenant."""
import uuid
from datetime import datetime, timezone


async def log_audit(action: str, user: dict | None = None, details: dict | None = None,
                    tenant_id: str | None = None):
    from app.db import get_raw_db
    from app.tenant_context import get_effective_tenant_id
    doc = {
        "id": str(uuid.uuid4()),
        "action": action,
        "at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id or get_effective_tenant_id() or (user or {}).get("tenant_id"),
        "user_id": (user or {}).get("id"),
        "user_email": (user or {}).get("email"),
        "user_role": (user or {}).get("role"),
        "details": details or {},
    }
    imp = (user or {}).get("impersonated_by")
    if imp:
        doc["impersonation"] = {"actor_id": imp.get("user_id"), "actor_email": imp.get("email"),
                                "session_id": imp.get("session_id")}
        doc["note"] = (f"Action réalisée par {imp.get('email')} en mode "
                       f"« Se connecter comme {(user or {}).get('email')} »")
    try:
        await get_raw_db().audit_log.insert_one(doc)
    except Exception:
        pass
