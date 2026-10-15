#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GO 2 (PRÉPARATION) — Application CHIRURGICALE du hotfix « Fin de service ».

SÛR, RÉVERSIBLE, FAIL-FAST. Par défaut = DRY-RUN (0 écriture PROD).

Garde-fous :
  * REFUSE si sha256(identification.py) != EXPECTED_ID_SHA256 (PROD exact).
  * REFUSE si backend/app/end_service_policy.py existe déjà (affiche son SHA).
  * Vérifie que chaque bloc/ancre apparaît EXACTEMENT une fois (sinon STOP).
  * DRY-RUN : génère la copie transformée dans /tmp (JAMAIS dans PROD),
    affiche le diff unifié complet, les SHA avant/après, le contenu du nouveau
    end_service_policy.py, valide la syntaxe (ast.parse), et PROUVE que
    driver_km_summary est byte-identique avant/après.
  * --write : backup byte-exact horodaté AVANT écriture, puis écrit UNIQUEMENT
    identification.py + end_service_policy.py. Jamais auto après DRY-RUN.
  * Aucun build / restart / docker / git / Navixy / device.

Usage :
    python3 apply_hotfix_end_service.py --backend /opt/apps/journal-logitrak/backend
    python3 apply_hotfix_end_service.py --backend /opt/apps/journal-logitrak/backend --write
"""
import argparse
import ast
import base64
import difflib
import hashlib
import os
import re
import sys
from datetime import datetime, timezone

EXPECTED_ID_SHA256 = "443469b351cb495b6c14247e3ddf222ded61016e8d8064d940fbf9c1e503b592"
EXPECTED_POLICY_SHA256 = "e662690cd836cb6caec5101d33b5c8334c4a255439d583e8d74689605ea1002f"

# Contenu EXACT (base64) du nouveau end_service_policy.py (SHA256 e662690...).
END_SERVICE_POLICY_B64 = (
    "IiIiUG9saXRpcXVlIEFVVE9SSVRBSVJFIMKrIEZpbiBkZSBzZXJ2aWNlIMK7IOKGlCBNb2RlIFByaXbDqS4KClPDiVBBUkFUSU9OIFNUUklDVEUgKGNvcnJpZ2UgbGEgZmFpbGxlIDogY2FuX3VzZV9wcml2YXRlX21vZGUoKS5hbGxvd2VkIE3DiUxBTkdFCmFwcGxpY2FiaWxpdMOpIGR1cmFibGUgZXQgY29uZGl0aW9ucyB0cmFuc2l0b2lyZXMg4oCUIGtpbGwgc3dpdGNoLCBmZWF0dXJlIGZsYWcsCmludMOpZ3JhdGlvbiBOYXZpeHkgaW5kaXNwb25pYmxlIOKAlCBkb25jIGFsbG93ZWQ9RmFsc2UgTkUgc2lnbmlmaWUgUEFTIMKrIE1vZGUgUHJpdsOpCm5vbiBhcHBsaWNhYmxlIMK7KS4KCkRldXggbm90aW9ucyBkaXN0aW5jdGVzIDoKCiAgMSkgcHJpdmF0ZV9tb2RlX2FwcGxpY2FibGUgPSBBUFBMSUNBQklMSVTDiSBEVVJBQkxFIGR1IGNvdXBsZSAoY2hhdWZmZXVyLCB2w6loaWN1bGUpLgogICAgIEVsbGUgTkUgZMOpcGVuZCBRVUUgZGUgc2lnbmF1eCBkdXJhYmxlcyA6CiAgICAgICAgLSByb2xsb3V0IEFDQ09VTlRfTU9ERUwgOiBjb21wdGUgY2hhdWZmZXVyIGxpw6kgKyBwcml2YXRlX21vZGVfZW5hYmxlZD1UcnVlCiAgICAgICAgICArIG1vZMOobGUgc3VwcG9ydMOpICsgY2FwYWJpbGl0eS9wcm9maWxlIHBlcnNpc3RhbnQgcHLDqnQgcG91ciBjZSB0cmFja2VyIDsKICAgICAgICAtIHJvbGxvdXQgbGVnYWN5ICAgICAgIDogdGVuYW50IHBpbG90ZSArIHbDqWhpY3VsZS90cmFja2VyIHBpbG90ZQogICAgICAgICAgKyBjYXBhYmlsaXR5IGNvbXBhdGlibGUuCiAgICAgTGVzIGNvbmRpdGlvbnMgVFJBTlNJVE9JUkVTIChmZWF0dXJlIGdsb2JhbGUsIGtpbGwgc3dpdGNoLCBpbnTDqWdyYXRpb24gTmF2aXh5CiAgICAgaW5kaXNwb25pYmxlLCBlcnJldXIgdGVjaG5pcXVlIGRlIGxlY3R1cmUpIE5FIHRyYW5zZm9ybWVudCBKQU1BSVMgYXBwbGljYWJsZQogICAgIGVuIEZhbHNlLgoKICAyKSBlbmRfc2VydmljZV9hbGxvd2VkID0gZMOpY2lzaW9uIEZpbiBkZSBzZXJ2aWNlLCDDoCBwYXJ0aXIgZGUgKGFwcGxpY2FibGUsIHN0YXRlKSA6CiAgICAgICAgYXBwbGljYWJsZT1mYWxzZSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA9PiBFTkQgQVVUT1JJU8OJRQogICAgICAgIGFwcGxpY2FibGU9dHJ1ZSArIEJVU0lORVNTIGNvbmZpcm3DqSAgICAgICAgICAgICAgID0+IEVORCBBVVRPUklTw4lFCiAgICAgICAgYXBwbGljYWJsZT10cnVlICsgUFJJVkFURS9QRU5ESU5HL1JFUVVFU1RFRC8KICAgICAgICAgICAgICAgICAgICAgICAgICBVTktOT1dOIC8gcmVhZF9lcnJvciAgICAgICAgICAgID0+IEVORCBCTE9RVcOJRSAoZmFpbC1jbG9zZWQpCgpBaW5zaSwgcG91ciB1biB2w6loaWN1bGUgUsOJRUxMRU1FTlQgTW9kZSBQcml2w6kgKGFwcGxpY2FibGU9dHJ1ZSkgZG9udCBsJ8OpdGF0IG4nZXN0CnBhcyBwcm91dsOpIEJVU0lORVNTIChraWxsIHN3aXRjaCBhY3RpZiwgTmF2aXh5IGluZGlzcG9uaWJsZSwgZXJyZXVyIGxlY3R1cmUuLi4pLApsYSBGaW4gZGUgc2VydmljZSByZXN0ZSBCTE9RVcOJRSDigJQgamFtYWlzIG91dmVydGUgcGFyIGVycmV1ci4KCk5FIE1PRElGSUUgTkkgbGUgbW90ZXVyIEFWTDE2IE5JIGxhIGxvZ2lxdWUgZGUgY29uZmlybWF0aW9uIFBSSVZBVEUvQlVTSU5FU1MuCiIiIgpmcm9tIF9fZnV0dXJlX18gaW1wb3J0IGFubm90YXRpb25zCgpmcm9tIHR5cGluZyBpbXBvcnQgT3B0aW9uYWwKCl9CVVNJTkVTUyA9ICJCVVNJTkVTUyIKCiMgUmFpc29ucyBhcHBsaWNhYmlsaXTDqSAoc3RhYmxlcywgdGVzdGFibGVzKS4KUl9BUFBMSUNBQkxFX0FDQ09VTlQgPSAiQVBQTElDQUJMRV9BQ0NPVU5UX01PREVMIgpSX0FQUExJQ0FCTEVfTEVHQUNZID0gIkFQUExJQ0FCTEVfTEVHQUNZX1BJTE9UIgpSX05PVF9BUFBMSUNBQkxFX0FDQ09VTlQgPSAiTk9UX0FQUExJQ0FCTEVfQUNDT1VOVCIKUl9OT1RfQVBQTElDQUJMRV9MRUdBQ1kgPSAiTk9UX0FQUExJQ0FCTEVfTEVHQUNZIgoKIyBSYWlzb25zIGTDqWNpc2lvbiBFTkQuClJfRU5EX09LX05PVF9BUFBMSUNBQkxFID0gIkVORF9PS19QUklWQVRFX01PREVfTk9UX0FQUExJQ0FCTEUiClJfRU5EX09LX0JVU0lORVNTID0gIkVORF9PS19CVVNJTkVTU19DT05GSVJNRUQiClJfRU5EX0JMT0NLRURfTk9UX0JVU0lORVNTID0gIkVORF9CTE9DS0VEX1BSSVZBVEVfTU9ERV9OT1RfQlVTSU5FU1MiClJfRU5EX0JMT0NLRURfVU5SRUFEQUJMRSA9ICJFTkRfQkxPQ0tFRF9QUklWQVRFX01PREVfVU5SRUFEQUJMRSIKCgpkZWYgY29tcHV0ZV9wcml2YXRlX21vZGVfYXBwbGljYWJsZSgKICAgICosCiAgICByb2xsb3V0OiBzdHIsCiAgICBhY2NvdW50X29rOiBib29sID0gRmFsc2UsCiAgICB0ZW5hbnRfcGlsb3Q6IGJvb2wgPSBGYWxzZSwKICAgIHZlaGljbGVfcGlsb3Q6IGJvb2wgPSBGYWxzZSwKICAgIHRyYWNrZXJfcHJlc2VudDogYm9vbCA9IEZhbHNlLAogICAgbW9kZWxfc3VwcG9ydGVkOiBib29sID0gRmFsc2UsCiAgICBjYXBhYmlsaXR5X3JlYWR5OiBib29sID0gRmFsc2UsCiAgICBwcm9maWxlX3JlYWR5OiBib29sID0gRmFsc2UsCikgLT4gZGljdDoKICAgICIiIkFQUExJQ0FCSUxJVMOJIERVUkFCTEUgKHB1cmUpLiBOJ3V0aWxpc2UgQVVDVU4gc2lnbmFsIHRyYW5zaXRvaXJlLgoKICAgIEFsaWduw6kgc3VyIGxlcyBoZWxwZXJzIFBST0QgKHByaXZhdGVfbW9kZV9nYXRlKSA6CgogICAgICBBQ0NPVU5UX01PREVMIChnYXRlLmFjY291bnRfbW9kZWxfZ2F0ZV9lbmFibGVkKCkgPT0gVHJ1ZSkgOgogICAgICAgIGFwcGxpY2FibGUgPSB0cmFja2VyX3ByZXNlbnQgQU5EIGFjY291bnRfb2sgQU5EIG1vZGVsX3N1cHBvcnRlZAogICAgICAgICAgICAgICAgICAgICBBTkQgcHJvZmlsZV9yZWFkeQogICAgICAgIC0gYWNjb3VudF9vayAgICAgID0gZ2F0ZS5kcml2ZXJfYWNjb3VudF9wcml2YXRlX21vZGVfZW5hYmxlZCguLi4pWzBdCiAgICAgICAgICAoY29tcHRlIGxpw6kgYWN0aWYgKyByb2xlIGRyaXZlciArIHByaXZhdGVfbW9kZV9lbmFibGVkID09IFRydWUpCiAgICAgICAgLSBtb2RlbF9zdXBwb3J0ZWQgPSBtb2RlbF9wcml2YXRlX21vZGVfc3VwcG9ydGVkKG1vZGVsKQogICAgICAgIC0gcHJvZmlsZV9yZWFkeSAgID0gdmVoaWNsZV9wcml2YXRlX3Byb2ZpbGVfcmVhZHkobW9kZWwsIGNhcGFiaWxpdHksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB0cmFja2VyX2lkPXRyYWNrZXJfaWQpCgogICAgICBMRUdBQ1kgKHJvbGxvdXQgcGFyIGTDqWZhdXQsIGFjdHVlbGxlbWVudCBhY3RpZiBlbiBQUk9EKSA6CiAgICAgICAgYXBwbGljYWJsZSA9IHRlbmFudF9waWxvdCBBTkQgdmVoaWNsZV9waWxvdCBBTkQgdHJhY2tlcl9wcmVzZW50CiAgICAgICAgICAgICAgICAgICAgIEFORCBjYXBhYmlsaXR5X3JlYWR5CiAgICAgICAgLSB0ZW5hbnRfcGlsb3QgICAgID0gZ2F0ZS50ZW5hbnRfYWxsb3dlZCh0ZW5hbnRfZG9jLCB0ZW5hbnRfaWQpCiAgICAgICAgLSB2ZWhpY2xlX3BpbG90ICAgID0gZ2F0ZS52ZWhpY2xlX2lzX3BpbG90KHZlaGljbGUpCiAgICAgICAgLSBjYXBhYmlsaXR5X3JlYWR5ID0gdmVoaWNsZV9wcml2YXRlX21vZGVfYWxsb3dlZChtb2RlbCwgY2FwYWJpbGl0eSkKCiAgICBJTVBPUlRBTlQgOiBjZXR0ZSBmb25jdGlvbiBuZSBjb25uYcOudCBQQVMgZmVhdHVyZSBmbGFnIC8ga2lsbCBzd2l0Y2ggLwogICAgaW50w6lncmF0aW9uIE5hdml4eSAvIERFVklDRV9XUklURSAvIMOpdGF0IGNvdXJhbnQgLyBlcnJldXJzIHRlY2huaXF1ZXMuCiAgICBDZXMgY29uZGl0aW9ucyB0cmFuc2l0b2lyZXMgTkUgUEVVVkVOVCBQQVMgcmVuZHJlIGFwcGxpY2FibGU9RmFsc2UuCiAgICAiIiIKICAgIGlmIHJvbGxvdXQgPT0gIkFDQ09VTlRfTU9ERUwiOgogICAgICAgIGFwcGxpY2FibGUgPSBib29sKAogICAgICAgICAgICB0cmFja2VyX3ByZXNlbnQKICAgICAgICAgICAgYW5kIGFjY291bnRfb2sKICAgICAgICAgICAgYW5kIG1vZGVsX3N1cHBvcnRlZAogICAgICAgICAgICBhbmQgcHJvZmlsZV9yZWFkeQogICAgICAgICkKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAicHJpdmF0ZV9tb2RlX2FwcGxpY2FibGUiOiBhcHBsaWNhYmxlLAogICAgICAgICAgICAicmVhc29uIjogUl9BUFBMSUNBQkxFX0FDQ09VTlQgaWYgYXBwbGljYWJsZSBlbHNlIFJfTk9UX0FQUExJQ0FCTEVfQUNDT1VOVCwKICAgICAgICB9CgogICAgIyBMRUdBQ1kgKGTDqWZhdXQgOyBjaGVtaW4gYWN0dWVsbGVtZW50IGFjdGlmIGVuIFBST0QpLgogICAgYXBwbGljYWJsZSA9IGJvb2woCiAgICAgICAgdGVuYW50X3BpbG90CiAgICAgICAgYW5kIHZlaGljbGVfcGlsb3QKICAgICAgICBhbmQgdHJhY2tlcl9wcmVzZW50CiAgICAgICAgYW5kIGNhcGFiaWxpdHlfcmVhZHkKICAgICkKICAgIHJldHVybiB7CiAgICAgICAgInByaXZhdGVfbW9kZV9hcHBsaWNhYmxlIjogYXBwbGljYWJsZSwKICAgICAgICAicmVhc29uIjogUl9BUFBMSUNBQkxFX0xFR0FDWSBpZiBhcHBsaWNhYmxlIGVsc2UgUl9OT1RfQVBQTElDQUJMRV9MRUdBQ1ksCiAgICB9CgoKZGVmIGRlY2lkZV9lbmRfc2VydmljZSgKICAgICosCiAgICBwcml2YXRlX21vZGVfYXBwbGljYWJsZTogYm9vbCwKICAgIHN0YXRlOiBPcHRpb25hbFtzdHJdLAogICAgcmVhZF9lcnJvcjogYm9vbCA9IEZhbHNlLAopIC0+IGRpY3Q6CiAgICAiIiJEw6ljaXNpb24gYXV0b3JpdGFpcmUgZGUgRmluIGRlIHNlcnZpY2Ugw6AgcGFydGlyIGRlIChhcHBsaWNhYmxlLCBzdGF0ZSkuCgogICAgYHByaXZhdGVfbW9kZV9hcHBsaWNhYmxlYCBET0lUIMOqdHJlIGwnYXBwbGljYWJpbGl0w6kgRFVSQUJMRSAoamFtYWlzIGTDqXJpdsOpZQogICAgZCd1biBhbGxvd2VkIHRyYW5zaXRvaXJlKS4gYHJlYWRfZXJyb3JgL2tpbGwgc3dpdGNoL2ludMOpZ3JhdGlvbiBuJ2luZmx1ZW5jZW50CiAgICBQQVMgYXBwbGljYWJsZSA6IHMnaWxzIGVtcMOqY2hlbnQgZGUgcHJvdXZlciBCVVNJTkVTUyBhbG9ycyBxdWUgYXBwbGljYWJsZT10cnVlLAogICAgbGEgZMOpY2lzaW9uIGVzdCBmYWlsLWNsb3NlZCAoYmxvcXXDqWUpLgoKICAgIFJldHVybnM6CiAgICAgICAgeyJwcml2YXRlX21vZGVfYXBwbGljYWJsZSI6IGJvb2wsICJlbmRfc2VydmljZV9hbGxvd2VkIjogYm9vbCwgInJlYXNvbiI6IHN0cn0KICAgICIiIgogICAgaWYgbm90IHByaXZhdGVfbW9kZV9hcHBsaWNhYmxlOgogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJwcml2YXRlX21vZGVfYXBwbGljYWJsZSI6IEZhbHNlLAogICAgICAgICAgICAiZW5kX3NlcnZpY2VfYWxsb3dlZCI6IFRydWUsCiAgICAgICAgICAgICJyZWFzb24iOiBSX0VORF9PS19OT1RfQVBQTElDQUJMRSwKICAgICAgICB9CgogICAgaWYgcmVhZF9lcnJvciBvciBub3Qgc3RhdGU6CiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgInByaXZhdGVfbW9kZV9hcHBsaWNhYmxlIjogVHJ1ZSwKICAgICAgICAgICAgImVuZF9zZXJ2aWNlX2FsbG93ZWQiOiBGYWxzZSwKICAgICAgICAgICAgInJlYXNvbiI6IFJfRU5EX0JMT0NLRURfVU5SRUFEQUJMRSwKICAgICAgICB9CgogICAgaWYgc3RhdGUgPT0gX0JVU0lORVNTOgogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJwcml2YXRlX21vZGVfYXBwbGljYWJsZSI6IFRydWUsCiAgICAgICAgICAgICJlbmRfc2VydmljZV9hbGxvd2VkIjogVHJ1ZSwKICAgICAgICAgICAgInJlYXNvbiI6IFJfRU5EX09LX0JVU0lORVNTLAogICAgICAgIH0KCiAgICByZXR1cm4gewogICAgICAgICJwcml2YXRlX21vZGVfYXBwbGljYWJsZSI6IFRydWUsCiAgICAgICAgImVuZF9zZXJ2aWNlX2FsbG93ZWQiOiBGYWxzZSwKICAgICAgICAicmVhc29uIjogUl9FTkRfQkxPQ0tFRF9OT1RfQlVTSU5FU1MsCiAgICB9Cg=="
)

RESOLVER_FUNC = '''async def _resolve_end_service_decision(db, tenant_id: str, driver_id: str,
                                        resolve_pending: bool = True) -> dict:
    """Décision AUTORITAIRE « Fin de service » (applicabilité DURABLE, pas allowed).

    Rollout dynamique : ACCOUNT_MODEL si gate.account_model_gate_enabled() sinon
    LEGACY. Conditions transitoires (feature/kill switch/intégration/DEVICE_WRITE)
    NE rendent JAMAIS applicable=False ; si elles empêchent de lire l'état ->
    read_error -> END bloquée (fail-closed). Erreur technique -> fail-closed.

    resolve_pending :
      - True  (POST END) : reproduit TOUTE la résolution tardive PROD du GET
        (PENDING_CONFIRMATION, TIMEOUT->BUSINESS awaiting_async_confirm,
        TIMEOUT->PRIVATE), via resolve_pending_confirmation() (aucune commande device).
      - False (retours anticipés GET) : lecture d'état simple, AUCUNE résolution
        tardive (ne pas changer le comportement historique des gates FEATURE/KILL).
    """
    from app import private_mode_engine as pm
    from app import private_mode_gate as gate
    from app import vehicle_assignment as va
    from app.end_service_policy import compute_private_mode_applicable, decide_end_service
    from app.tenant_context import get_tenant_doc

    # Résolution du véhicule actif. DISTINGUER :
    #  - vrai "aucun véhicule" (sans erreur) -> non applicable -> END autorisée ;
    #  - EXCEPTION technique de résolution    -> fail-closed (END bloquée).
    try:
        vehicle_id = await va.resolve_active_vehicle(db, driver_id, tenant_id)
        if not vehicle_id:
            sess = await ble_engine.get_current_session(db, driver_id)
            vehicle_id = sess.get("vehicle_id") if sess else None
    except Exception:
        return decide_end_service(private_mode_applicable=True, state=None,
                                  read_error=True)
    if not vehicle_id:
        return decide_end_service(private_mode_applicable=False, state=None)

    try:
        vehicle = await db.vehicles.find_one(
            {"id": vehicle_id, "tenant_id": tenant_id}, {"_id": 0}) or {}
        tracker_id = vehicle.get("navixy_tracker_id")
        model = pm.resolve_model(vehicle.get("model"))
        vc = await pm.resolve_vehicle_capability(db, tracker_id, model)

        generalized = False
        _acct_gate = getattr(gate, "account_model_gate_enabled", None)
        if callable(_acct_gate):
            generalized = bool(_acct_gate())

        if generalized:
            account_ok = False
            _acct_enabled = getattr(gate, "driver_account_private_mode_enabled", None)
            if callable(_acct_enabled):
                res_acct = await _acct_enabled(db, tenant_id, driver_id)
                account_ok = bool(res_acct[0] if isinstance(res_acct, (tuple, list))
                                  else res_acct)
            from app.odometer_capability import (model_private_mode_supported,
                                                 vehicle_private_profile_ready)
            applicable_res = compute_private_mode_applicable(
                rollout="ACCOUNT_MODEL",
                tracker_present=bool(tracker_id),
                account_ok=account_ok,
                model_supported=bool(model_private_mode_supported(model)),
                profile_ready=bool(vehicle_private_profile_ready(
                    model, vc, tracker_id=tracker_id)),
            )
        else:
            from app.odometer_capability import vehicle_private_mode_allowed
            applicable_res = compute_private_mode_applicable(
                rollout="LEGACY",
                tenant_pilot=gate.tenant_allowed(get_tenant_doc(tenant_id), tenant_id),
                vehicle_pilot=gate.vehicle_is_pilot(vehicle),
                tracker_present=bool(tracker_id),
                capability_ready=bool(vehicle_private_mode_allowed(model, vc)),
            )
        applicable = applicable_res["private_mode_applicable"]
    except Exception:
        return decide_end_service(private_mode_applicable=True, state=None,
                                  read_error=True)

    if not applicable:
        return decide_end_service(private_mode_applicable=False, state=None)

    # Éligible durable : lecture de l'état (fail-closed si illisible).
    try:
        st = await pm.get_mode_state(db, vehicle_id)
        if resolve_pending:
            # MÊMES conditions que le GET PROD (résolution tardive READ-ONLY).
            _should_resolve = (
                st.get("state") == pm.PENDING_CONFIRMATION
                or (
                    st.get("state") == pm.UNKNOWN
                    and st.get("transition_result") == pm.TRANSITION_TIMEOUT
                    and st.get("requested_target") == pm.BUSINESS
                    and bool(st.get("awaiting_async_confirm"))
                )
                or (
                    st.get("state") == pm.UNKNOWN
                    and st.get("transition_result") == pm.TRANSITION_TIMEOUT
                    and st.get("requested_target") == pm.PRIVATE
                )
            )
            if _should_resolve:
                st = await pm.resolve_pending_confirmation(db, vehicle_id, tenant_id)
        state_now = st.get("state", pm.UNKNOWN)
        return decide_end_service(private_mode_applicable=True, state=state_now)
    except Exception:
        return decide_end_service(private_mode_applicable=True, state=None,
                                  read_error=True)


'''

# ---- 9 remplacements de BLOCS EXACTS (AVANT -> APRÈS) ----
REPLACEMENTS = []

REPLACEMENTS.append((
    "from fastapi import APIRouter, Depends, HTTPException, Query\n",
    "from fastapi import APIRouter, Depends, HTTPException, Query\n"
    "from fastapi.responses import JSONResponse\n",
))

_END_BEFORE = '''@router.post("/driver/vehicle-assignment/end")
async def vehicle_assignment_end(payload: AssignEndIn, user=Depends(get_current_user)):
    """« Fin de service » — libère le véhicule (idempotent).

    La désaffectation Navixy est anti-race : sur retry d'une ancienne requête,
    on relit l'event d'origine au lieu de toucher un véhicule actif plus récent.
    """
    from app import vehicle_assignment as va
    db = get_db()
    tenant_id = user.get("tenant_id") or "default"
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")

    before = await va.get_active(db, tenant_id, driver_id)
'''
_END_AFTER = RESOLVER_FUNC + '''@router.post("/driver/vehicle-assignment/end")
async def vehicle_assignment_end(payload: AssignEndIn, user=Depends(get_current_user)):
    """« Fin de service » — libère le véhicule (idempotent).

    La désaffectation Navixy est anti-race : sur retry d'une ancienne requête,
    on relit l'event d'origine au lieu de toucher un véhicule actif plus récent.

    AUTORITÉ BACKEND (hotfix End-Service) : la décision end_service_allowed est
    évaluée AVANT va.end(). La logique Navixy anti-race ci-dessous est inchangée.
    """
    from app import vehicle_assignment as va
    db = get_db()
    tenant_id = user.get("tenant_id") or "default"
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")

    _end_gate = await _resolve_end_service_decision(db, tenant_id, driver_id)
    if not _end_gate["end_service_allowed"]:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "result": "blocked",
                "reason": _end_gate["reason"],
                "private_mode_applicable": _end_gate["private_mode_applicable"],
                "end_service_allowed": False,
                "http_status": 409,
            },
        )

    before = await va.get_active(db, tenant_id, driver_id)
'''
REPLACEMENTS.append((_END_BEFORE, _END_AFTER))

REPLACEMENTS.append((
    '''            res["navixy_sync"] = await _safe_navixy_assignment_stop(
                db,
                driver_id,
                vehicle_id,
                actor=user.get("email", "?"),
            )

    return {"ok": res.get("result") in ("ok", "noop"), **res}''',
    '''            res["navixy_sync"] = await _safe_navixy_assignment_stop(
                db,
                driver_id,
                vehicle_id,
                actor=user.get("email", "?"),
            )

    return {
        "ok": res.get("result") in ("ok", "noop"),
        **res,
        "private_mode_applicable": _end_gate["private_mode_applicable"],
        "end_service_allowed": True,
    }''',
))

# R3 — forme PROD EXACTE : PAS de ligne vide entre `raise` et le commentaire.
REPLACEMENTS.append((
    '''    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    # Fail-closed niveau 1/2 : feature globale + kill switch AVANT toute résolution.
    if not gate.feature_enabled():''',
    '''    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    # Décision autoritaire Fin de service (applicabilité durable) pour enrichir
    # les retours anticipés. resolve_pending=False : NE déclenche PAS de résolution
    # tardive (ne change pas le comportement historique des gates FEATURE/KILL).
    _end_decision = await _resolve_end_service_decision(db, tenant_id, driver_id, resolve_pending=False)
    # Fail-closed niveau 1/2 : feature globale + kill switch AVANT toute résolution.
    if not gate.feature_enabled():''',
))

# R4/R5/R6 — retours anticipés COMPACTS (forme PROD exacte, dict condensé).
for _reason in ("gate.R_FEATURE_DISABLED", "gate.R_KILL_SWITCH", "gate.R_NO_VEHICLE"):
    REPLACEMENTS.append((
        f'''        return {{"state": pm.UNKNOWN, "allowed": False, "reason": {_reason},
                "can_switch": False, "can_switch_reason": {_reason},
                "vehicle_id": None, "tracker_id": None, "last_transition_at": None,
                "private_odometer_supported": False}}''',
        f'''        return {{"state": pm.UNKNOWN, "allowed": False, "reason": {_reason},
                "can_switch": False, "can_switch_reason": {_reason},
                "vehicle_id": None, "tracker_id": None, "last_transition_at": None,
                "private_odometer_supported": False,
                "private_mode_applicable": _end_decision["private_mode_applicable"],
                "end_service_allowed": _end_decision["end_service_allowed"],
                "end_service_reason": _end_decision["reason"]}}''',
    ))

# R7 — forme PROD EXACTE : PAS de ligne vide avant `return {`.
REPLACEMENTS.append((
    '''    if state_now == pm.PRIVATE:
        exposed_private_distance_km = None
    else:
        exposed_private_distance_km = st.get("private_distance_km")
    return {
        "state": state_now,''',
    '''    if state_now == pm.PRIVATE:
        exposed_private_distance_km = None
    else:
        exposed_private_distance_km = st.get("private_distance_km")
    # Décision END FINALE : applicabilité durable (stable) + ÉTAT FINAL state_now
    # (après résolution tardive PRIVATE/BUSINESS). On NE réutilise PAS la décision
    # précoce : un état PENDING -> BUSINESS doit autoriser END.
    from app.end_service_policy import decide_end_service as _decide_end
    _final_end = _decide_end(
        private_mode_applicable=_end_decision["private_mode_applicable"],
        state=state_now,
    )
    return {
        "state": state_now,''',
))

# R8 — forme PROD EXACTE : commentaires inline conservés.
REPLACEMENTS.append((
    '''        "last_command": st.get("last_command"),                 # dernière commande envoyée
        "command_sent_at": st.get("command_sent_at"),           # horodatage envoi
        "odometer_snapshot_status": st.get("odometer_snapshot_status"),  # OK|UNAVAILABLE|INVALID
    }''',
    '''        "last_command": st.get("last_command"),                 # dernière commande envoyée
        "command_sent_at": st.get("command_sent_at"),           # horodatage envoi
        "odometer_snapshot_status": st.get("odometer_snapshot_status"),  # OK|UNAVAILABLE|INVALID
        "private_mode_applicable": _final_end["private_mode_applicable"],
        "end_service_allowed": _final_end["end_service_allowed"],
        "end_service_reason": _final_end["reason"],
    }''',
))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_block(text: str, name: str) -> str:
    """Extrait une fonction `async def <name>(` ou `def <name>(` jusqu'au prochain
    début de fonction/décorateur de MÊME indentation (niveau module). Best-effort,
    pour comparer byte-identité avant/après d'une zone sensible (driver_km_summary)."""
    pat = re.compile(r"^(?:@[^\n]*\n)*(?:async\s+)?def\s+" + re.escape(name) + r"\s*\(",
                     re.MULTILINE)
    m = pat.search(text)
    if not m:
        return ""
    start = m.start()
    # fin = prochain début de def/async def/@router au niveau module après start
    nxt = re.compile(r"^(?:@router|@app|async\s+def|def)\s", re.MULTILINE)
    m2 = nxt.search(text, m.end())
    end = m2.start() if m2 else len(text)
    return text[start:end]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default=".", help="chemin du dossier backend PROD")
    ap.add_argument("--write", action="store_true", help="appliquer (sinon DRY-RUN)")
    args = ap.parse_args()

    id_path = os.path.join(args.backend, "app", "routes", "identification.py")
    policy_path = os.path.join(args.backend, "app", "end_service_policy.py")
    policy_text = base64.b64decode(END_SERVICE_POLICY_B64).decode("utf-8")
    policy_sha = _sha256(policy_text.encode("utf-8"))

    print("=" * 72)
    print("HOTFIX END-SERVICE — application CHIRURGICALE (mode:",
          "WRITE" if args.write else "DRY-RUN", ")")
    print("=" * 72)

    # Contrôle du SHA de la policy embarquée (fail-fast).
    if policy_sha != EXPECTED_POLICY_SHA256:
        print(f"STOP: SHA end_service_policy.py embarquée inattendu "
              f"({policy_sha} != {EXPECTED_POLICY_SHA256}). AUCUNE action.",
              file=sys.stderr)
        sys.exit(9)
    print(f"OK: policy embarquée SHA256 = {policy_sha}")

    if not os.path.isfile(id_path):
        print(f"STOP: introuvable {id_path}", file=sys.stderr); sys.exit(2)

    original = open(id_path, "rb").read()
    cur_sha = _sha256(original)
    print(f"identification.py SHA256 actuel  = {cur_sha}")
    print(f"identification.py SHA256 attendu = {EXPECTED_ID_SHA256}")
    if cur_sha != EXPECTED_ID_SHA256:
        print("STOP: SHA d'entrée != attendu. AUCUNE action.", file=sys.stderr)
        sys.exit(3)
    print("OK: fichier PROD exact.")

    if os.path.isfile(policy_path):
        print(f"STOP: {policy_path} existe déjà (SHA256="
              f"{_sha256(open(policy_path, 'rb').read())}). AUCUNE action.",
              file=sys.stderr)
        sys.exit(6)
    print("OK: end_service_policy.py absent (sera créé).")

    text = original.decode("utf-8")
    for i, (before, _after) in enumerate(REPLACEMENTS):
        c = text.count(before)
        if c != 1:
            print(f"STOP: bloc R{i} trouvé {c} fois (attendu 1). AUCUNE action.",
                  file=sys.stderr)
            sys.exit(4)
    print(f"OK: les {len(REPLACEMENTS)} blocs/ancres sont présents et uniques.")

    new_text = text
    for before, after in REPLACEMENTS:
        new_text = new_text.replace(before, after, 1)
    new_bytes = new_text.encode("utf-8")
    new_sha = _sha256(new_bytes)

    # Validation syntaxique du résultat.
    try:
        ast.parse(new_text)
        print("OK: ast.parse(identification.py modifié) — syntaxe valide.")
    except SyntaxError as e:
        print(f"STOP: SyntaxError dans le résultat: {e}", file=sys.stderr); sys.exit(7)
    try:
        ast.parse(policy_text)
        print("OK: ast.parse(end_service_policy.py) — syntaxe valide.")
    except SyntaxError as e:
        print(f"STOP: SyntaxError dans la policy: {e}", file=sys.stderr); sys.exit(7)

    # PREUVE non-régression : driver_km_summary byte-identique avant/après.
    # FAIL-FAST : si la fonction est introuvable, on NE peut PAS prouver la
    # non-régression -> STOP (exigence v3).
    km_before = _extract_block(text, "driver_km_summary")
    km_after = _extract_block(new_text, "driver_km_summary")
    if not km_before:
        print("STOP: driver_km_summary introuvable — preuve de non-régression KPI "
              "impossible. AUCUNE action. (Vérifier le nom réel de la fonction KPI "
              "km dans identification.py.)", file=sys.stderr)
        sys.exit(10)
    same = (km_before == km_after)
    print(f"driver_km_summary présent : byte-identique avant/après = {same} "
          f"(sha_before={_sha256(km_before.encode())[:12]}, "
          f"sha_after={_sha256(km_after.encode())[:12]})")
    if not same:
        print("STOP: driver_km_summary MODIFIÉ (hors périmètre). AUCUNE action.",
              file=sys.stderr)
        sys.exit(8)

    print("-" * 72)
    print(f"SHA256 AVANT  identification.py = {cur_sha}")
    print(f"SHA256 APRÈS  identification.py = {new_sha}")
    print(f"SHA256        end_service_policy.py = {policy_sha}")
    print("-" * 72)
    print("DIFF UNIFIÉ COMPLET (identification.py) :")
    diff = difflib.unified_diff(
        text.splitlines(keepends=True), new_text.splitlines(keepends=True),
        fromfile="a/backend/app/routes/identification.py",
        tofile="b/backend/app/routes/identification.py",
    )
    sys.stdout.writelines(diff)
    print("-" * 72)
    print("CONTENU COMPLET DU NOUVEAU end_service_policy.py :")
    print(policy_text)
    print("-" * 72)
    print("Fichiers concernés UNIQUEMENT :")
    print(f"  (modif)   {id_path}")
    print(f"  (création){policy_path}")

    if not args.write:
        # DRY-RUN : écrire la copie SIMULÉE hors PROD (jamais dans /opt/apps).
        simdir = "/tmp/hotfix_end_service_sim"
        os.makedirs(simdir, exist_ok=True)
        open(os.path.join(simdir, "identification.py"), "w",
             encoding="utf-8").write(new_text)
        open(os.path.join(simdir, "end_service_policy.py"), "w",
             encoding="utf-8").write(policy_text)
        print("-" * 72)
        print(f"DRY-RUN : copies simulées écrites dans {simdir} (HORS PROD).")
        print("AUCUNE écriture dans /opt/apps/journal-logitrak. Aucun build/restart.")
        print("Relancer avec --write (après GO WRITE explicite) pour appliquer.")
        print("=" * 72)
        return

    # ---- WRITE réel ----
    # Backup byte-exact HORS du repo PROD (jamais de .bak sous /opt/apps).
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = os.environ.get("HOTFIX_BACKUP_DIR", "/home/ubuntu/hotfix-end-service-backups")
    os.makedirs(backup_dir, exist_ok=True)
    bak = os.path.join(backup_dir, f"identification.py.bak.{ts}")
    open(bak, "wb").write(original)
    open(f"{bak}.sha256", "w").write(f"{cur_sha}  identification.py\n")
    print(f"Backup byte-exact (HORS PROD): {bak} (sha256={cur_sha})")
    open(id_path, "wb").write(new_bytes)
    open(policy_path, "w", encoding="utf-8").write(policy_text)
    print("ÉCRITURE EFFECTUÉE (2 fichiers).")
    print(f"  identification.py   -> {new_sha}")
    print(f"  end_service_policy  -> {policy_sha}")
    print(f"Rollback: cp {bak} {id_path} ; rm {policy_path} ; "
          "puis rebuild/recreate journal_backend.")
    print("=" * 72)


if __name__ == "__main__":
    main()
