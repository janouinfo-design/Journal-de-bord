"""Access control V1 — modules par client (entitlement) + permissions par utilisateur.

Lot 1 : catalogues en code, résolution des permissions effectives, dépendances
`require_module` / `require_permission`, mode de transition
ACCESS_CONTROL_MODE = legacy | shadow | enforce (env, surchargeable par tenant).
"""
import logging
import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request

logger = logging.getLogger(__name__)


async def get_current_user(request: Request):
    """Import paresseux (évite le cycle auth ↔ access_control) ; résultat mis en cache par requête."""
    from app.auth import get_current_user as _gcu
    return await _gcu(request)

MODES = ("legacy", "shadow", "enforce")
DEFAULT_MODE = "legacy"

# ---------------------------------------------------------------------------
# Catalogue des modules (code → définition). legacy_default = état implicite
# d'un tenant sans `modules_enabled` (migration non exécutée).
# ---------------------------------------------------------------------------
MODULES = {
    "journal":             {"label": "Journal de bord", "category": "core", "depends_on": [], "legacy_default": True},
    "trip_classification": {"label": "Privé / Professionnel", "category": "core", "depends_on": ["journal"], "legacy_default": True},
    "private_mode":        {"label": "Mode privé des traceurs", "category": "business", "depends_on": ["trip_classification"], "legacy_default": True},
    "drivers":             {"label": "Conducteurs & identification", "category": "core", "depends_on": ["journal"], "legacy_default": True},
    "energy":              {"label": "Énergie", "category": "business", "depends_on": ["journal"], "legacy_default": True},
    "fuel":                {"label": "Carburant", "category": "business", "depends_on": ["journal"], "legacy_default": True},
    "fuel_cards":          {"label": "Cartes carburant", "category": "business", "depends_on": ["fuel"], "legacy_default": True},
    "ev_charging":         {"label": "Recharge EV", "category": "reserved", "depends_on": ["energy"], "legacy_default": False},
    "fines":               {"label": "Amendes", "category": "business", "depends_on": ["journal"], "legacy_default": True},
    "reports":             {"label": "Rapports", "category": "business", "depends_on": ["journal"], "legacy_default": True},
    "notifications":       {"label": "Notifications", "category": "business", "depends_on": [], "legacy_default": True},
    "documents":           {"label": "Documents", "category": "reserved", "depends_on": [], "legacy_default": False},
    "costs":               {"label": "Coûts / factures", "category": "reserved", "depends_on": [], "legacy_default": False},
    "budget":              {"label": "Budget", "category": "reserved", "depends_on": [], "legacy_default": False},
    "maintenance":         {"label": "Maintenance / échéances", "category": "reserved", "depends_on": [], "legacy_default": False},
    "utilization":         {"label": "Sous-/sur-utilisation", "category": "reserved", "depends_on": ["journal"], "legacy_default": False},
    "kboard_advanced":     {"label": "K-Board Advanced", "category": "reserved", "depends_on": [], "legacy_default": False},
}

# ---------------------------------------------------------------------------
# Catalogue des permissions : code → (module | None = plateforme-tenant, libellé).
# Actions : view / view_self / edit / edit_self / admin / export / … ;
# « write » = toute action hors view / view_self / export / manage_self.
# ---------------------------------------------------------------------------
_P = [
    # journal
    ("journal.view", "journal", "Consulter le Journal (sans positions GPS)"),
    ("journal.view_self", "journal", "Consulter ses propres trajets"),
    ("journal.export", "journal", "Exporter le Journal"),
    ("positions.view", "journal", "Positions GPS, traces et localisation détaillée"),
    ("vehicles.edit", "journal", "Modifier les véhicules (mode, affectations)"),
    ("vehicles.admin", "journal", "Administrer les véhicules (motorisation, capacités, odomètre)"),
    # trip_classification
    ("trips.classify", "trip_classification", "Reclassifier tout trajet"),
    ("trips.classify_self", "trip_classification", "Reclassifier ses propres trajets"),
    ("work_schedule.view", "trip_classification", "Consulter les plages horaires"),
    ("work_schedule.edit", "trip_classification", "Modifier les plages horaires"),
    ("privacy_policy.edit", "trip_classification", "Modifier la politique de confidentialité"),
    # private_mode
    ("private_mode.view", "private_mode", "Voir l'état du mode privé"),
    ("private_mode.edit", "private_mode", "Appliquer / configurer le mode privé"),
    ("private_mode.admin", "private_mode", "Kill-switch du mode privé"),
    # drivers
    ("drivers.view", "drivers", "Consulter les conducteurs"),
    ("drivers.edit", "drivers", "Modifier les conducteurs"),
    ("drivers.admin", "drivers", "Inviter / accès / mot de passe conducteurs"),
    ("identification.view", "drivers", "Consulter identification et sessions"),
    ("identification.edit", "drivers", "Corriger identification et sessions"),
    ("identification.self", "drivers", "Console chauffeur"),
    # energy
    ("energy.view", "energy", "Consulter l'énergie"),
    ("energy.view_self", "energy", "Consulter l'énergie de ses trajets"),
    ("energy.edit", "energy", "Configurer rapprochement / alertes énergie"),
    ("energy.admin", "energy", "Mapping tenant Energy"),
    ("energy.export", "energy", "Exporter l'énergie"),
    # fuel
    ("fuel.view", "fuel", "Consulter le carburant"),
    ("fuel.view_self", "fuel", "Consulter ses transactions"),
    ("fuel.edit_self", "fuel", "Justificatifs / signalements sur ses transactions"),
    ("fuel.edit", "fuel", "Saisir / documenter des transactions"),
    ("fuel.import", "fuel", "Importer des transactions"),
    ("fuel.reconcile", "fuel", "Rapprocher et traiter les anomalies"),
    ("fuel.statements", "fuel", "Gérer les décomptes"),
    ("fuel.admin", "fuel", "Paramètres carburant, FX, motorisation"),
    ("fuel.export", "fuel", "Exporter le carburant"),
    # fuel_cards
    ("fuel_cards.view", "fuel_cards", "Consulter les cartes carburant"),
    ("fuel_cards.edit", "fuel_cards", "Gérer les cartes carburant"),
    # fines
    ("fines.view", "fines", "Consulter les amendes"),
    ("fines.view_self", "fines", "Consulter ses amendes"),
    ("fines.edit", "fines", "Créer / modifier les amendes"),
    ("fines.pay", "fines", "Payer / annuler / clôturer une amende"),
    ("fines.admin", "fines", "Supprimer une amende"),
    ("fines.export", "fines", "Exporter les amendes"),
    # reports
    ("reports.view", "reports", "Consulter / télécharger les rapports"),
    ("reports.admin", "reports", "Configurer les rapports"),
    # notifications
    ("notifications.manage_self", "notifications", "Gérer ses notifications"),
    ("notifications.manage_company", "notifications", "Gérer les notifications de l'entreprise"),
    # plateforme-tenant (toujours disponibles, aucun module)
    ("users.view", None, "Consulter les utilisateurs"),
    ("users.edit", None, "Créer / modifier / désactiver les utilisateurs"),
    ("users.permissions", None, "Gérer rôles et permissions"),
    ("users.impersonate", None, "Se connecter comme un utilisateur"),
    ("settings.view", None, "Consulter les paramètres"),
    ("settings.edit", None, "Modifier les paramètres"),
    ("audit.view", None, "Consulter l'audit"),
]
PERMISSIONS = {code: {"module": mod, "label": label} for code, mod, label in _P}

_READ_ACTIONS = ("view", "view_self", "export", "manage_self")
WRITE_PERMISSIONS = frozenset(p for p in PERMISSIONS if p.split(".", 1)[1] not in _READ_ACTIONS)

# Non attribuables par surcharge aux rôles driver / lecture_seule.
SENSITIVE_PERMISSIONS = frozenset({
    "positions.view", "private_mode.edit", "private_mode.admin", "privacy_policy.edit",
    "users.edit", "users.permissions", "users.impersonate", "settings.edit", "energy.admin",
    "audit.view",
})
_NO_SENSITIVE_GRANT_ROLES = ("driver", "lecture_seule")

# ---------------------------------------------------------------------------
# Rôles = modèles de permissions (parité stricte avec la matrice legacy).
# ---------------------------------------------------------------------------
_ALL = frozenset(PERMISSIONS)
ROLE_TEMPLATES = {
    "admin": _ALL,
    "manager": frozenset({
        "journal.view", "journal.export", "positions.view", "vehicles.edit",
        "trips.classify", "work_schedule.view", "work_schedule.edit", "privacy_policy.edit",
        "private_mode.view",
        "drivers.view", "identification.view", "identification.edit",
        "energy.view", "energy.edit", "energy.export",
        "fuel.view", "fuel.reconcile", "fuel.export", "fuel_cards.view",
        "fines.view", "fines.edit", "fines.pay", "fines.export",
        "reports.view", "reports.admin",
        "notifications.manage_self", "settings.view",
    }),
    "office": frozenset({
        "journal.view", "journal.export", "work_schedule.view", "drivers.view",
        "energy.view", "energy.export",
        "fuel.view", "fuel.edit", "fuel.import", "fuel.statements", "fuel.export",
        "fuel_cards.view", "fuel_cards.edit",
        "fines.view", "fines.edit", "fines.pay", "fines.export",
        "reports.view", "notifications.manage_self",
    }),
    "driver": frozenset({
        "journal.view_self", "trips.classify_self", "work_schedule.view", "identification.self",
        "energy.view_self", "fuel.view_self", "fuel.edit_self", "fines.view_self",
        "notifications.manage_self",
    }),
    "lecture_seule": frozenset({
        "journal.view", "journal.export", "positions.view", "work_schedule.view",
        "energy.view", "energy.export", "fuel.view", "fuel.export", "fuel_cards.view",
        "fines.view", "fines.export", "reports.view", "notifications.manage_self",
    }),
}
TENANT_ROLES = tuple(ROLE_TEMPLATES)

# Champs de géolocalisation retirés des réponses quand `positions.view` manque (enforce).
POSITION_FIELDS = frozenset({
    "lat", "lng", "lon", "latitude", "longitude", "start_lat", "start_lng", "end_lat", "end_lng",
    "station_lat", "station_lng", "points", "polyline", "track", "coords", "position", "last_position",
})

# Registre des dépendances déclarées (test de parité legacy ↔ permissions).
REGISTRY: list[dict] = []


# ---------------------------------------------------------------------------
# Résolution
# ---------------------------------------------------------------------------
def resolve_mode(tenant_doc: dict | None) -> str:
    mode = (tenant_doc or {}).get("access_control_mode") or os.environ.get("ACCESS_CONTROL_MODE") or DEFAULT_MODE
    return mode if mode in MODES else DEFAULT_MODE


def module_enabled(tenant_doc: dict | None, code: str) -> bool:
    spec = MODULES.get(code)
    if not spec:
        return False
    flags = (tenant_doc or {}).get("modules_enabled")
    enabled = spec["legacy_default"] if flags is None else bool(flags.get(code, False))
    return enabled and all(module_enabled(tenant_doc, dep) for dep in spec["depends_on"])


def enabled_modules(tenant_doc: dict | None) -> list[str]:
    return [c for c in MODULES if module_enabled(tenant_doc, c)]


def expand(perms: set[str]) -> set[str]:
    """admin ⇒ edit ⇒ view (lorsque ces permissions existent pour la ressource)."""
    out = set(perms)
    for p in perms:
        res, action = p.split(".", 1)
        if action == "admin":
            for a in ("edit", "view"):
                if f"{res}.{a}" in PERMISSIONS:
                    out.add(f"{res}.{a}")
        elif action == "edit" and f"{res}.view" in PERMISSIONS:
            out.add(f"{res}.view")
    return out


def effective_permissions(user: dict, tenant_doc: dict | None) -> set[str]:
    role = user.get("role")
    if role == "superadmin":
        base = set(_ALL)
    else:
        base = set(ROLE_TEMPLATES.get(role, ROLE_TEMPLATES["lecture_seule"]))
    ov = user.get("permissions_override") or {}
    grant = {p for p in (ov.get("grant") or []) if p in PERMISSIONS}
    revoke = {p for p in (ov.get("revoke") or []) if p in PERMISSIONS}
    eff = expand(base | grant) - revoke
    if role == "lecture_seule":
        eff -= WRITE_PERMISSIONS
    return {p for p in eff
            if PERMISSIONS[p]["module"] is None or module_enabled(tenant_doc, PERMISSIONS[p]["module"])}


def validate_override(role: str, grant: list[str], revoke: list[str], tenant_doc: dict | None) -> None:
    """Règles anti-escalade (Lot 3). Lève ValueError(code)."""
    for p in list(grant) + list(revoke):
        if p not in PERMISSIONS:
            raise ValueError("unknown_permission")
    for p in grant:
        mod = PERMISSIONS[p]["module"]
        if mod and not module_enabled(tenant_doc, mod):
            raise ValueError("module_disabled")
        if p in SENSITIVE_PERMISSIONS and role in _NO_SENSITIVE_GRANT_ROLES:
            raise ValueError("sensitive_not_allowed_for_role")
        if role == "lecture_seule" and p in WRITE_PERMISSIONS:
            raise ValueError("write_not_allowed_for_read_only")


def strip_positions(obj):
    """Retire récursivement les champs de géolocalisation d'une réponse."""
    if isinstance(obj, dict):
        return {k: strip_positions(v) for k, v in obj.items() if k not in POSITION_FIELDS}
    if isinstance(obj, list):
        return [strip_positions(x) for x in obj]
    return obj


def must_strip_positions(request: Request, user: dict) -> bool:
    tenant_doc = getattr(request.state, "tenant_doc", None)
    if resolve_mode(tenant_doc) != "enforce" or user.get("role") == "superadmin":
        return False
    return "positions.view" not in effective_permissions(user, tenant_doc)


# ---------------------------------------------------------------------------
# Journalisation des refus en mode shadow (1 par utilisateur / clé / jour)
# ---------------------------------------------------------------------------
_SHADOW_SEEN: set = set()


async def _shadow_deny(user: dict, kind: str, key: str, request: Request):
    day = datetime.now(timezone.utc).date().isoformat()
    sig = (user.get("id"), kind, key, day)
    if sig in _SHADOW_SEEN:
        return
    if len(_SHADOW_SEEN) > 10000:
        _SHADOW_SEEN.clear()
    _SHADOW_SEEN.add(sig)
    from app.audit import log_audit
    await log_audit("access.shadow_deny", user,
                    {"kind": kind, "key": key, "method": request.method, "path": request.url.path,
                     "role": user.get("role")})


def enforce_readiness(tenant: dict, users: list[dict], denies: list[dict], shadow_since: str | None,
                      now: datetime) -> dict:
    """Bilan de préparation au mode enforce (pur, testable). Aucun `fail` ⇒ ready."""
    checks: list[dict] = []

    def add(cid, status, label, detail=None):
        checks.append({"id": cid, "status": status, "label": label, "detail": detail})

    add("tenant_active", "ok" if tenant.get("status") == "active" else "fail",
        "Client actif", f"statut : {tenant.get('status')}")
    days = None
    if shadow_since:
        days = (now - datetime.fromisoformat(shadow_since)).days
    if days is None:
        add("observation", "warn", "Période d'observation", "jamais passé en mode Observation")
    else:
        add("observation", "ok" if days >= 7 else "warn", "Période d'observation",
            f"{days} jour(s) en Observation (recommandé ≥ 7)")
    by_key: dict[tuple, dict] = {}
    for d in denies:
        det = d.get("details") or {}
        k = (det.get("kind"), det.get("key"))
        row = by_key.setdefault(k, {"kind": k[0], "key": k[1], "count": 0, "users": set(), "roles": set()})
        row["count"] += 1
        row["users"].add(d.get("user_email"))
        if det.get("role"):
            row["roles"].add(det["role"])
    denies_out = sorted(({**r, "users": len(r["users"]), "roles": sorted(r["roles"])} for r in by_key.values()),
                        key=lambda r: -r["count"])
    add("shadow_denies", "ok" if not denies else "warn", "Refus observés (30 j)",
        f"{len(denies)} refus → deviendraient des 403" if denies else "aucun refus observé")
    unknown = [u["email"] for u in users if u.get("role") not in TENANT_ROLES]
    add("roles_known", "ok" if not unknown else "fail", "Rôles reconnus",
        f"{len(unknown)} utilisateur(s) avec un rôle inconnu" if unknown else "tous les rôles sont connus")
    enabled = set(enabled_modules(tenant))
    invalid = []
    for u in users:
        ov = u.get("permissions_override") or {}
        for kind in ("grant", "revoke"):
            for p in ov.get(kind) or []:
                spec = PERMISSIONS.get(p)
                if not spec:
                    invalid.append({"email": u["email"], kind: p, "reason": "unknown_permission"})
                elif spec["module"] and spec["module"] not in enabled:
                    invalid.append({"email": u["email"], kind: p, "reason": "module_disabled"})
    add("overrides_valid", "ok" if not invalid else "warn", "Surcharges cohérentes",
        f"{len(invalid)} surcharge(s) à nettoyer" if invalid else "aucune surcharge invalide")
    inactive = sum(1 for u in users if u.get("active") is False)
    by_role: dict[str, int] = {}
    for u in users:
        by_role[u.get("role") or "?"] = by_role.get(u.get("role") or "?", 0) + 1
    return {
        "tenant_id": tenant["id"], "mode_effective": resolve_mode(tenant), "modules_effective": sorted(enabled),
        "observation": {"since": shadow_since, "days": days, "shadow_denies": len(denies), "by_key": denies_out},
        "users": {"total": len(users), "inactive": inactive, "by_role": by_role, "unknown_role": unknown,
                  "with_override": sum(1 for u in users if u.get("permissions_override"))},
        "invalid_overrides": invalid,
        "checks": checks,
        "ready": all(c["status"] != "fail" for c in checks),
    }


# ---------------------------------------------------------------------------
# Dépendances FastAPI
# ---------------------------------------------------------------------------
def _module_disabled(code: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"code": "module_disabled", "module": code,
                                                  "msg": f"Module « {MODULES[code]['label']} » non activé pour ce client."})


def require_module(code: str):
    if code not in MODULES:
        raise ValueError(f"module inconnu: {code}")

    async def _dep(request: Request, user=Depends(get_current_user)):
        tenant_doc = getattr(request.state, "tenant_doc", None)
        mode = resolve_mode(tenant_doc)
        if mode == "legacy":
            return user
        if not module_enabled(tenant_doc, code):
            if mode == "enforce":
                raise _module_disabled(code)
            await _shadow_deny(user, "module", code, request)
        return user
    return _dep


def require_permission(*perms: str, legacy_roles: tuple | None = None, module: str | None = None,
                       parity_exempt: tuple = ()):
    """Autorise si l'utilisateur détient l'UNE des permissions.

    legacy_roles : rôles autorisés par l'ancien `require_roles` (None = tout utilisateur
    authentifié). Appliqués en mode legacy et shadow pour conserver le comportement actuel.
    parity_exempt : rôles dont l'écart legacy ↔ permissions est assumé et documenté (test T24).
    """
    for p in perms:
        if p not in PERMISSIONS:
            raise ValueError(f"permission inconnue: {p}")
    if module and module not in MODULES:
        raise ValueError(f"module inconnu: {module}")
    if module is None:
        # Source unique : si toutes les permissions relèvent du même module, le refus « module coupé »
        # prime sur « permission manquante » (message lisible et audit `kind=module` corrects).
        mods = {PERMISSIONS[p]["module"] for p in perms}
        if len(mods) == 1 and None not in mods:
            module = mods.pop()
    REGISTRY.append({"perms": perms, "legacy_roles": legacy_roles, "module": module,
                     "parity_exempt": tuple(parity_exempt)})

    async def _dep(request: Request, user=Depends(get_current_user)):
        role = user.get("role")
        tenant_doc = getattr(request.state, "tenant_doc", None)
        mode = resolve_mode(tenant_doc)
        if mode != "enforce" and legacy_roles is not None and role != "superadmin" and role not in legacy_roles:
            raise HTTPException(status_code=403, detail="Accès refusé")
        if mode == "legacy":
            return user
        if module and not module_enabled(tenant_doc, module):
            if mode == "enforce":
                raise _module_disabled(module)
            await _shadow_deny(user, "module", module, request)
            return user
        if role == "superadmin":
            return user
        eff = effective_permissions(user, tenant_doc)
        if not any(p in eff for p in perms):
            if mode == "enforce":
                raise HTTPException(status_code=403,
                                    detail={"code": "permission_denied", "permission": perms[0],
                                            "msg": "Permission insuffisante."})
            await _shadow_deny(user, "permission", perms[0], request)
        return user
    return _dep


def me_payload(user: dict, tenant_doc: dict | None) -> dict:
    return {
        "access_control_mode": resolve_mode(tenant_doc),
        "modules_enabled": enabled_modules(tenant_doc),
        "permissions_effective": sorted(effective_permissions(user, tenant_doc)),
    }


# ---------------------------------------------------------------------------
# Lot 2 / Lot 3 — catalogues exposés et normalisation des modules d'un client
# ---------------------------------------------------------------------------
def normalize_modules(flags: dict | None) -> dict:
    """Dict complet code → bool ; un module dont une dépendance est OFF est forcé OFF."""
    flags = flags or {}
    out = {c: bool(flags.get(c, spec["legacy_default"])) for c, spec in MODULES.items()}
    changed = True
    while changed:
        changed = False
        for c, spec in MODULES.items():
            if out[c] and any(not out[d] for d in spec["depends_on"]):
                out[c] = False
                changed = True
    return out


def modules_catalog() -> list[dict]:
    return [{"code": c, **spec} for c, spec in MODULES.items()]


def permissions_catalog(tenant_doc: dict | None) -> dict:
    enabled_list = enabled_modules(tenant_doc)
    enabled = set(enabled_list)
    return {
        "modules": [{"code": c, "label": MODULES[c]["label"], "category": MODULES[c]["category"]} for c in enabled_list],
        "permissions": [
            {"code": p, "module": s["module"], "label": s["label"],
             "sensitive": p in SENSITIVE_PERMISSIONS, "write": p in WRITE_PERMISSIONS,
             "available": s["module"] is None or s["module"] in enabled}
            for p, s in PERMISSIONS.items()
        ],
        "role_templates": {r: sorted(expand(set(t))) for r, t in ROLE_TEMPLATES.items()},
        "roles": list(TENANT_ROLES),
        "sensitive_blocked_roles": list(_NO_SENSITIVE_GRANT_ROLES),
    }
