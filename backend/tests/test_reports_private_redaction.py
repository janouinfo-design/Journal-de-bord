"""Test confidentialité des EXPORTS de rapports : un trajet en Mode Privé ne doit
jamais exporter de localisation (adresses/coords). Km/durée conservés.

Teste la logique de redaction appliquée par la route export (sans serveur HTTP) :
on reproduit le même pipeline (trip_is_private -> redact + label) puis on vérifie
que les sorties CSV/XLSX/PDF ne contiennent aucune adresse privée.
"""
from app.private_mode_engine import redact_private_trip, trip_is_private
from app.reports import trips_to_csv, trips_to_xlsx, trips_to_pdf


PRIVATE_TRIP = {
    "id": "p1", "private_mode": True, "mode_status": "PRIVATE",
    "start_time": "2026-09-07T08:14:00+00:00", "end_time": "2026-09-07T08:42:00+00:00",
    "driver_name": "Jean Dupont", "vehicle_plate": "GE 123456",
    "start_address": "SECRET_HOME_ADDRESS_LAUSANNE", "end_address": "SECRET_CLINIC_GENEVE",
    "start_lat": 46.5197, "start_lng": 6.6323, "end_lat": 46.2044, "end_lng": 6.1432,
    "distance_km": 18.4, "duration_min": 28, "fuel_l": 1.7, "avg_speed": 60, "max_speed": 92,
    "classification": "professional",
}

BUSINESS_TRIP = {
    "id": "b1", "start_time": "2026-09-07T09:00:00+00:00", "end_time": "2026-09-07T09:20:00+00:00",
    "driver_name": "Jean Dupont", "vehicle_plate": "GE 123456",
    "start_address": "Dépôt Genève", "end_address": "Client Migros",
    "distance_km": 12.0, "duration_min": 20, "fuel_l": 1.1, "avg_speed": 50, "max_speed": 80,
    "classification": "professional",
}

_FORBIDDEN = ["SECRET_HOME_ADDRESS_LAUSANNE", "SECRET_CLINIC_GENEVE",
              "46.5197", "6.6323", "46.2044", "6.1432"]


def _export_pipeline(trips):
    """Reproduit la redaction de la route /reports/export."""
    out = []
    for t in trips:
        if trip_is_private(t):
            rt = redact_private_trip(t)
            rt["start_address"] = "Privé — position masquée"
            rt["end_address"] = "Privé — position masquée"
            out.append(rt)
        else:
            out.append(t)
    return out


def test_private_trip_marked_for_export():
    assert trip_is_private(PRIVATE_TRIP) is True
    assert trip_is_private(BUSINESS_TRIP) is False


def test_csv_export_no_private_location():
    trips = _export_pipeline([PRIVATE_TRIP, BUSINESS_TRIP])
    data = trips_to_csv(trips, "Professionnel").decode("utf-8-sig")
    for bad in _FORBIDDEN:
        assert bad not in data, f"fuite {bad} dans CSV"
    # champs métier conservés + libellé privé présent
    assert "18.4" in data and "Privé — position masquée" in data
    # trajet business intact
    assert "Dépôt Genève" in data


def test_xlsx_export_no_private_location():
    trips = _export_pipeline([PRIVATE_TRIP, BUSINESS_TRIP])
    blob = trips_to_xlsx(trips, "Professionnel", "Rapport")
    # openpyxl xlsx = zip ; les chaînes vivent dans sharedStrings — on scanne l'octet brut
    for bad in _FORBIDDEN:
        assert bad.encode() not in blob, f"fuite {bad} dans XLSX"


def test_pdf_export_no_private_location():
    trips = _export_pipeline([PRIVATE_TRIP, BUSINESS_TRIP])
    blob = trips_to_pdf(trips, "Professionnel", "Rapport", "")
    for bad in _FORBIDDEN:
        assert bad.encode() not in blob, f"fuite {bad} dans PDF"


def test_business_trip_addresses_preserved_in_export():
    trips = _export_pipeline([BUSINESS_TRIP])
    data = trips_to_csv(trips, "Professionnel").decode("utf-8-sig")
    assert "Dépôt Genève" in data and "Client Migros" in data


def test_redacted_private_trip_has_no_coords():
    rt = redact_private_trip(PRIVATE_TRIP)
    for k in ("start_lat", "start_lng", "end_lat", "end_lng"):
        assert rt[k] is None
    assert rt["distance_km"] == 18.4 and rt["duration_min"] == 28  # métier conservé
