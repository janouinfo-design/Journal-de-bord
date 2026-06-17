/* Trips polyline map (MapLibre GL) — Phase A maps.
 *
 * Strict rule: when settings_mode === 'masked', personal trips are NEVER
 * rendered on the map regardless of user role. Only `classification ===
 * 'professional'` may be shown. This is enforced client-side AND complements
 * the existing backend invariant.
 *
 * Real polylines: for each visible trip we lazy-fetch GPS points from
 * `/api/livre/trips/{id}/track` (which calls Navixy with a server-side cache).
 * If the fetch fails or returns a fallback, we keep the straight line.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import maplibregl from "maplibre-gl";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Map as MapIcon, EyeOff, Loader2 } from "lucide-react";

const COLORS = {
  professional: "#2196F3",
  personal:     "#F59E0B",
  unclassified: "#94A3B8",
};

const STYLE_OSM = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

function validCoord(t) {
  return Number.isFinite(t?.start_lat) && Number.isFinite(t?.start_lng)
      && Number.isFinite(t?.end_lat)   && Number.isFinite(t?.end_lng);
}

function fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-CH", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
}

export default function TripsMap({ trips, settingsMode, height = 420 }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const popupRef = useRef(null);
  const [ready, setReady] = useState(false);
  // Map trip.id → real polyline `[[lng,lat], ...]` once fetched
  const [polylines, setPolylines] = useState({});
  const [loadingPoly, setLoadingPoly] = useState(0);
  const fetchedRef = useRef(new Set());

  // ✱ Strict masked-mode filter — applied here regardless of role.
  const visibleTrips = useMemo(() => {
    const arr = (trips || []).filter(validCoord);
    if (settingsMode === "masked") {
      return arr.filter(t => t.classification === "professional");
    }
    return arr;
  }, [trips, settingsMode]);

  const hiddenCount = (trips?.filter(validCoord).length || 0) - visibleTrips.length;

  // Lazy load real polylines with a small concurrency pool (avoid spamming the backend).
  useEffect(() => {
    if (!visibleTrips.length) return;
    const toFetch = visibleTrips
      .filter(t => t.id && !fetchedRef.current.has(t.id))
      .slice(0, 200); // hard cap per render
    if (!toFetch.length) return;
    let cancelled = false;
    setLoadingPoly(toFetch.length);

    const CONCURRENCY = 6;
    let cursor = 0;
    const next = async () => {
      while (cursor < toFetch.length && !cancelled) {
        const idx = cursor++;
        const t = toFetch[idx];
        fetchedRef.current.add(t.id);
        try {
          const { data } = await api.get(`/livre/trips/${t.id}/track`);
          if (cancelled) return;
          if (data?.points?.length >= 2) {
            setPolylines(prev => ({ ...prev, [t.id]: data.points }));
          }
        } catch { /* keep fallback straight line */ }
        setLoadingPoly(n => Math.max(0, n - 1));
      }
    };
    Promise.all(Array.from({ length: Math.min(CONCURRENCY, toFetch.length) }, next));
    return () => { cancelled = true; };
  }, [visibleTrips]);

  // Build GeoJSON, using real polyline if cached else straight line
  const geojson = useMemo(() => ({
    type: "FeatureCollection",
    features: visibleTrips.map(t => {
      const coords = polylines[t.id] && polylines[t.id].length >= 2
        ? polylines[t.id]
        : [[t.start_lng, t.start_lat], [t.end_lng, t.end_lat]];
      return {
        type: "Feature",
        properties: {
          id: t.id,
          classification: t.classification || "unclassified",
          start_address: t.start_address || "",
          end_address: t.end_address || "",
          start_time: t.start_time,
          end_time: t.end_time,
          distance_km: t.distance_km,
          driver_name: t.driver_name || "",
          vehicle_plate: t.vehicle_plate || "",
          is_real: !!polylines[t.id],
        },
        geometry: { type: "LineString", coordinates: coords },
      };
    }),
  }), [visibleTrips, polylines]);

  // Init map (once)
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_OSM,
      center: [6.633, 46.519],   // Lausanne fallback
      zoom: 9,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    map.on("load", () => {
      map.addSource("trips", { type: "geojson", data: geojson });
      map.addLayer({
        id: "trips-line",
        type: "line",
        source: "trips",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": [
            "match", ["get", "classification"],
            "professional", COLORS.professional,
            "personal",     COLORS.personal,
            COLORS.unclassified,
          ],
          "line-width": 4,
          "line-opacity": 0.85,
        },
      });
      map.addLayer({
        id: "trip-start",
        type: "circle",
        source: "trips",
        paint: {
          "circle-radius": 6,
          "circle-color": "#10B981",
          "circle-stroke-width": 2,
          "circle-stroke-color": "#ffffff",
        },
        // Render only at the line start
        filter: ["==", ["geometry-type"], "LineString"],
      });
      // Click → popup
      map.on("click", "trips-line", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties;
        const html = `
          <div style="font-family:Inter,system-ui;font-size:12px;min-width:220px">
            <div style="font-weight:600;color:#0F172A">${fmtDate(p.start_time)}</div>
            <div style="color:#64748B;font-size:10px;margin-top:2px;text-transform:uppercase;letter-spacing:0.05em">
              <span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${
                p.classification === "professional" ? COLORS.professional :
                p.classification === "personal"     ? COLORS.personal     :
                COLORS.unclassified
              };margin-right:5px"></span>
              ${p.classification === "professional" ? "Professionnel"
                : p.classification === "personal" ? "Personnel"
                : "Non classifié"}
              ${p.vehicle_plate ? ` · ${p.vehicle_plate}` : ""}
            </div>
            <div style="margin-top:6px;color:#334155">
              <div><strong>De :</strong> ${p.start_address || "—"}</div>
              <div style="margin-top:3px"><strong>À :</strong> ${p.end_address || "—"}</div>
              <div style="margin-top:5px;color:#0F172A">
                ${typeof p.distance_km === "number" ? p.distance_km.toFixed(1) : "—"} km
                ${p.driver_name ? ` · ${p.driver_name}` : ""}
              </div>
            </div>
          </div>`;
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: "320px" })
          .setLngLat(e.lngLat).setHTML(html).addTo(map);
      });
      map.on("mouseenter", "trips-line", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "trips-line", () => { map.getCanvas().style.cursor = ""; });
      setReady(true);
    });
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // Update data on filter change
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const src = map.getSource("trips");
    if (src) src.setData(geojson);
    // Auto-fit bounds
    if (visibleTrips.length) {
      const b = new maplibregl.LngLatBounds();
      for (const t of visibleTrips) {
        b.extend([t.start_lng, t.start_lat]);
        b.extend([t.end_lng, t.end_lat]);
      }
      try { map.fitBounds(b, { padding: 40, maxZoom: 13, duration: 600 }); } catch { /* noop */ }
    }
  }, [geojson, ready, visibleTrips]);

  return (
    <Card className="bg-white border-slate-200 shadow-sm rounded-md overflow-hidden" data-testid="trips-map-card">
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MapIcon className="w-4 h-4 text-[#2196F3]" />
          <h3 className="text-sm font-semibold text-slate-800">Carte des trajets</h3>
          <span className="text-[11px] text-slate-500" data-testid="trips-map-count">
            {visibleTrips.length} trajet(s) affiché(s)
          </span>
          {loadingPoly > 0 && (
            <span className="text-[11px] text-slate-400 flex items-center gap-1" data-testid="trips-map-loading">
              <Loader2 className="w-3 h-3 animate-spin" />
              chargement des traces GPS… ({loadingPoly} restants)
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-[11px]">
          <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-3 rounded-sm" style={{ background: COLORS.professional }}></span>Pro</span>
          <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-3 rounded-sm" style={{ background: COLORS.personal }}></span>Privé</span>
          <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-3 rounded-sm" style={{ background: COLORS.unclassified }}></span>N/C</span>
        </div>
      </div>

      {settingsMode === "masked" && hiddenCount > 0 && (
        <div className="px-4 py-2 bg-amber-50 border-b border-amber-200 text-amber-800 text-[11px] flex items-center gap-2"
             data-testid="trips-map-masked-notice">
          <EyeOff className="w-3.5 h-3.5" />
          Mode Personnel Masqué — {hiddenCount} trajet(s) personnel(s) masqué(s) sur la carte.
        </div>
      )}

      <div ref={containerRef} style={{ height: `${height}px`, width: "100%" }}
           data-testid="trips-map-canvas" />

      {visibleTrips.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="bg-white/90 px-4 py-3 rounded-md shadow text-sm text-slate-500" data-testid="trips-map-empty">
            Aucun trajet géolocalisé à afficher
          </div>
        </div>
      )}
    </Card>
  );
}
