#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — DIAGNOSTIC LOGIN (READ-ONLY) — pourquoi 401 pour un chauffeur ?
==========================================================================
Inspecte l'etat du compte dans la base courante (Preview) SANS RIEN MODIFIER :
  * compte users present ? active ? role ? tenant ?
  * password_hash present ? le mot de passe fourni (ENV) VERIFIE-t-il ?
  * lien db.drivers actif ?
  * lockout actif dans login_attempts (locked_until futur) ? combien d'essais ?

STRICTEMENT READ-ONLY : aucune ecriture, aucun deverrouillage, aucun reset.
Le mot de passe (ENV DIAG_DRIVER_PWD) n'est JAMAIS affiche.

Execution (dans le conteneur backend Preview) :
  docker exec -e DIAG_DRIVER_EMAIL="orhan@logitrak.ch" -e DIAG_DRIVER_PWD="***" \
    -i journal_preview_backend python - < login_diag.py
"""
from __future__ import annotations

import os
import sys
import asyncio
from datetime import datetime, timezone


def _b(v):
    return "OUI" if v else "non"


async def main() -> int:
    try:
        from app.db import init_db, get_raw_db  # type: ignore
        from app.auth import verify_password
    except Exception as e:
        print(f"ERREUR import : {type(e).__name__}: {e}")
        return 2

    try:
        init_db()
        db = get_raw_db()
        if db is None:
            raise RuntimeError("DB non initialisee")
    except Exception as e:
        print(f"ERREUR connexion DB : {type(e).__name__}: {e}")
        return 2

    email = (os.getenv("DIAG_DRIVER_EMAIL") or "orhan@logitrak.ch").strip().lower()
    pwd = os.getenv("DIAG_DRIVER_PWD") or ""
    now_iso = datetime.now(timezone.utc).isoformat()

    print("=" * 74)
    print("DIAGNOSTIC LOGIN (READ-ONLY) —", email)
    print("=" * 74)
    print("Instant UTC :", now_iso)
    print("DB_NAME     :", os.getenv("DB_NAME"))

    # --- users ---
    u = await db.users.find_one({"email": email},
                                {"_id": 0, "id": 1, "email": 1, "role": 1,
                                 "tenant_id": 1, "active": 1, "password_hash": 1,
                                 "private_mode_enabled": 1})
    if not u:
        print("\n[USERS] AUCUN compte pour cet email dans CETTE base.")
        print("  -> Mauvaise base (Preview vs PROD) OU email different.")
        return 0
    has_hash = bool(u.get("password_hash"))
    print("\n[USERS]")
    print("  id                  :", u.get("id"))
    print("  role                :", u.get("role"))
    print("  tenant_id           :", u.get("tenant_id"))
    print("  active              :", u.get("active"))
    print("  private_mode_enabled:", u.get("private_mode_enabled"))
    print("  password_hash       :", "<present>" if has_hash else "<ABSENT>")

    # --- verification mot de passe (sans afficher) ---
    if pwd and has_hash:
        try:
            ok = verify_password(pwd, u["password_hash"])
        except Exception as e:
            ok = None
            print("  verif password     : ERREUR", type(e).__name__, e)
        if ok is True:
            print("  verif password     : OK (le mot de passe fourni correspond)")
        elif ok is False:
            print("  verif password     : ECHEC (mot de passe fourni != hash en base)")
    elif not pwd:
        print("  verif password     : (DIAG_DRIVER_PWD non fourni -> non teste)")

    # --- driver lie ---
    drv = await db.drivers.find_one(
        {"tenant_id": u.get("tenant_id"), "$or": [{"user_id": u["id"]}, {"email": email}]},
        {"_id": 0, "id": 1, "active": 1})
    print("\n[DRIVERS]")
    if not drv:
        print("  AUCUN driver lie (tenant+user_id/email) -> login driver possible mais",
              "profil chauffeur non trouve.")
    else:
        print("  driver id :", drv.get("id"), " active :", drv.get("active"),
              "  (active=False -> login REFUSE)")

    # --- lockout ---
    att = await db.login_attempts.find_one({"identifier": email}, {"_id": 0})
    print("\n[LOGIN_ATTEMPTS]")
    if not att:
        print("  Aucun compteur d'echec -> PAS de lockout.")
    else:
        locked_until = att.get("locked_until") or ""
        locked_active = locked_until > now_iso
        print("  attempts      :", att.get("attempts") or att.get("count"))
        print("  locked_until  :", locked_until or "(aucun)")
        print("  LOCKOUT ACTIF :", _b(locked_active),
              "-> tout login renvoie 401 jusqu'a expiration." if locked_active else "")

    # --- verdict ---
    print("\n=== VERDICT ===")
    if att and (att.get("locked_until") or "") > now_iso:
        print("  Cause probable : LOCKOUT TEMPORAIRE actif. Attendre l'expiration")
        print("  (locked_until ci-dessus), puis reessayer. Aucune action destructive requise.")
    elif has_hash and pwd:
        # ok deja calcule plus haut, on recalcule prudemment
        try:
            if verify_password(pwd, u["password_hash"]):
                print("  Le mot de passe fourni EST correct et pas de lockout actif :")
                print("  -> le 401 venait d'un lockout desormais expire, ou d'un essai anterieur.")
                print("     Reessayez le login applicatif maintenant.")
            else:
                print("  Le mot de passe fourni NE correspond PAS au hash en base (Preview).")
                print("  -> Utilisez le bon mot de passe Preview pour orhan.")
        except Exception:
            print("  (verification impossible)")
    else:
        print("  Compte sans password_hash ou mot de passe non fourni : verifier le provisioning.")

    print("\n" + "=" * 74)
    print("FIN — READ-ONLY. Collez la sortie (aucun secret affiche).")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
