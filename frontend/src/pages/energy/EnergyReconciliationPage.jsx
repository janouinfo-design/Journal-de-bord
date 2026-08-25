import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from "@/components/ui/sheet";
import { EnergyBadge } from "@/components/energy/EnergyBadge";
import { POWERTRAIN_LABEL } from "@/components/energy/TripEnergyBlock";
import {
  Scale, AlertTriangle, Loader2, Info, Fuel, Zap, Car, CheckCircle2,
  SearchCheck, HelpCircle, XCircle, FileSpreadsheet, FileText, BellOff, Settings2,
} from "lucide-react";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

const STATUS_META = {
  OK: { label: "OK", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  A_CONTROLER: { label: "À contrôler", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  INDICATIF: { label: "Indicatif", cls: "bg-blue-50 text-blue-700 border-blue-200" },
  IMPOSSIBLE: { label: "Impossible", cls: "bg-slate-100 text-slate-500 border-slate-200" },
};
const MEASUREMENT_LABEL = { MEASURED: "Mesuré", ESTIMATED: "Estimé", REFERENCE: "Référence", NONE: "Aucun" };
const RELIABILITY_LABEL = { EXPLOITABLE: "Exploitable", INDICATIF: "Indicatif", IMPOSSIBLE: "Impossible" };
const SOURCE_TX_LABEL = { csv: "Import CSV", manual: "Manuel", card: "Carte", inconnu: "Inconnue" };

function StatusBadge({ status, reason, testId }) {
  const s = STATUS_META[status] || STATUS_META.IMPOSSIBLE;
  return (
    <Badge variant="outline" title={reason} data-testid={testId}
           className={`${s.cls} font-medium text-[10px] px-1.5 py-0 cursor-help`}>
      {s.label}
    </Badge>
  );
}

function localIso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function presetRange(p) {
  const today = new Date();
  if (p === "month") return { from: localIso(new Date(today.getFullYear(), today.getMonth(), 1)), to: localIso(today) };
  if (p === "prev_month") {
    return { from: localIso(new Date(today.getFullYear(), today.getMonth() - 1, 1)),
             to: localIso(new Date(today.getFullYear(), today.getMonth(), 0)) };
  }
  if (p === "last30") { const f = new Date(today); f.setDate(f.getDate() - 30); return { from: localIso(f), to: localIso(today) }; }
  if (p === "year") return { from: `${today.getFullYear()}-01-01`, to: localIso(today) };
  return null;
}

function Kpi({ label, value, icon: Icon, cls = "text-slate-800", testId }) {
  return (
    <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4" data-testid={testId}>
      <p className="text-[10px] uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
        <Icon className="w-3 h-3" /> {label}
      </p>
      <p className={`text-xl font-semibold mt-1 ${cls}`}>{value}</p>
    </Card>
  );
}

const ALL = "all";
const DEFAULT_FILTERS = {
  vehicle: ALL, group: ALL, powertrain: ALL, measurement: ALL, reliability: ALL, status: ALL,
};

function FilterSelect({ k, label, options, value, onChange, testId }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">{label}</p>
      <Select value={value} onValueChange={(v) => onChange(k, v)}>
        <SelectTrigger data-testid={testId}><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>Tous</SelectItem>
          {options.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
        </SelectContent>
      </Select>
    </div>
  );
}

/* Préparation des alertes « À contrôler » — APERÇU uniquement, aucun envoi.
   L'envoi reste verrouillé backend tant que REAL ENERGY n'est pas validé. */
function AlertsPreparationPanel({ range, canGenerate }) {
  const [data, setData] = useState(null);
  const [generating, setGenerating] = useState(false);

  const load = () =>
    api.get("/livre/energy/reconciliation/alerts/candidates")
      .then(r => setData(r.data)).catch(() => setData(null));
  useEffect(() => { load(); }, []);

  async function generate() {
    setGenerating(true);
    try {
      const { data: res } = await api.post(
        "/livre/energy/reconciliation/alerts/candidates/generate", null,
        { params: { date_from: range.from, date_to: range.to } });
      toast.success(`${res.created} candidat(s) créé(s) · ${res.duplicates} doublon(s) ignoré(s) — aucun message envoyé`);
      load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Erreur lors de la génération de l'aperçu");
    } finally {
      setGenerating(false);
    }
  }

  const items = data?.items || [];
  return (
    <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4 space-y-3" data-testid="recon-alerts-panel">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
            <BellOff className="w-4 h-4 text-slate-400" /> Alertes « À contrôler » — préparation
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Envoi verrouillé tant que la campagne REAL ENERGY n&apos;est pas validée pour ce client.
            Seuls les écarts <strong>mesurés</strong> au statut « À contrôler » peuvent devenir candidats.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {canGenerate && (
            <Button size="sm" variant="outline" className="text-xs h-7"
                    onClick={generate} disabled={generating}
                    data-testid="recon-alerts-generate-btn">
              {generating ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <BellOff className="w-3.5 h-3.5 mr-1" />}
              Générer l&apos;aperçu des candidats
            </Button>
          )}
          <Link to="/livre/settings" data-testid="recon-alerts-settings-link"
                className="text-xs text-[#2196F3] hover:underline flex items-center gap-1">
            <Settings2 className="w-3.5 h-3.5" /> Configurer
          </Link>
        </div>
      </div>
      <div data-testid="recon-alerts-preview-banner"
           className="bg-slate-100 border border-slate-200 text-slate-700 rounded-md px-3 py-2 text-xs font-semibold">
        APERÇU — AUCUN MESSAGE ENVOYÉ (e-mail, SMS et push désactivés)
      </div>
      <p className="text-xs text-slate-500" data-testid="recon-alerts-count">
        {items.length === 0
          ? "Aucun candidat d'alerte enregistré."
          : `${items.length} candidat(s) d'alerte enregistré(s) — anti-doublonnage par véhicule + période.`}
      </p>
      {items.length > 0 && (
        <ul className="space-y-1" data-testid="recon-alerts-candidates">
          {items.slice(0, 5).map(c => (
            <li key={c.id} className="text-xs text-slate-600 flex items-center gap-2 flex-wrap">
              <span className="font-mono">{c.plate || c.vehicle_id}</span>
              <span className="text-slate-400">{c.period_from} au {c.period_to}</span>
              {c.gap_l != null && <span className="text-amber-700">écart {c.gap_l > 0 ? "+" : ""}{c.gap_l} L</span>}
              <Badge variant="outline" className="bg-slate-50 text-slate-500 border-slate-200 text-[10px] px-1.5 py-0">
                Non envoyé
              </Badge>
            </li>
          ))}
          {items.length > 5 && <li className="text-xs text-slate-400">… et {items.length - 5} autre(s)</li>}
        </ul>
      )}
    </Card>
  );
}

export default function EnergyReconciliationPage() {
  const { user } = useAuth();
  const [preset, setPreset] = useState("year");
  const [range, setRange] = useState(presetRange("year"));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const setFilter = (k, v) => setFilters(f => ({ ...f, [k]: v }));
  const [exporting, setExporting] = useState(null);

  function activeFilterParams() {
    const params = { date_from: range.from, date_to: range.to };
    if (filters.vehicle !== ALL) params.vehicle_id = filters.vehicle;
    if (filters.group !== ALL) params.group = filters.group;
    if (filters.powertrain !== ALL) params.powertrain = filters.powertrain;
    if (filters.measurement !== ALL) params.measurement = filters.measurement;
    if (filters.reliability !== ALL) params.reliability = filters.reliability;
    if (filters.status !== ALL) params.status = filters.status;
    return params;
  }

  async function doExport(kind) {
    setExporting(kind);
    const isPdf = kind === "pdf";
    try {
      const res = await api.get(`/livre/energy/reconciliation/export.${isPdf ? "pdf" : "xlsx"}`,
        { params: activeFilterParams(), responseType: "blob" });
      const ct = res.headers["content-type"] || "";
      if (!(isPdf ? ct.includes("pdf") : ct.includes("spreadsheetml"))) {
        throw new Error("réponse inattendue");
      }
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `rapprochement_carburant_${range.from}_${range.to}.${isPdf ? "pdf" : "xlsx"}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(isPdf ? "Export PDF généré" : "Export Excel généré");
    } catch (e) {
      const d = e?.response?.data?.detail;
      toast.error(typeof d === "string" ? d
        : (isPdf ? "Erreur lors de l'export PDF" : "Erreur lors de l'export Excel"));
    } finally {
      setExporting(null);
    }
  }

  useEffect(() => {
    if (!range?.from || !range?.to) return;
    setLoading(true);
    api.get("/livre/energy/reconciliation/preview",
      { params: { date_from: range.from, date_to: range.to } })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [range?.from, range?.to]);

  const rows = data?.rows || [];
  const groups = useMemo(
    () => [...new Set(rows.map(r => (r.plate || "").split(" ")[0]).filter(Boolean))].sort(),
    [rows]);

  const filtered = useMemo(() => rows.filter(r => (
    (filters.vehicle === ALL || r.vehicle_id === filters.vehicle)
    && (filters.group === ALL || (r.plate || "").split(" ")[0] === filters.group)
    && (filters.powertrain === ALL || r.powertrain === filters.powertrain)
    && (filters.measurement === ALL || r.consumption_measurement_type === filters.measurement)
    && (filters.reliability === ALL || r.reliability === filters.reliability)
    && (filters.status === ALL || r.status === filters.status)
  )), [rows, filters]);

  const kpi = useMemo(() => ({
    analyzable: rows.filter(r => r.status === "OK" || r.status === "A_CONTROLER").length,
    check: rows.filter(r => r.status === "A_CONTROLER").length,
    indicative: rows.filter(r => r.status === "INDICATIF").length,
    impossible: rows.filter(r => r.status === "IMPOSSIBLE").length,
  }), [rows]);

  const periodLabel = data?.period ? `${data.period.from} → ${data.period.to}` : "—";
  const notConnected = data && !data.connected;
  const fixture = data?.mode === "fixture";

  return (
    <div data-testid="recon-page" className="space-y-5">
      <p className="text-sm text-slate-500 flex items-start gap-2">
        <Scale className="w-4 h-4 text-[#2196F3] shrink-0 mt-0.5" />
        <span>
          Comparaison achats (cartes carburant) vs consommation (module Énergie).
          Écran diagnostic / preview — alertes automatiques désactivées.
        </span>
      </p>

      {fixture && (
        <div data-testid="recon-fixture-banner"
             className="bg-violet-50 border border-violet-200 text-violet-800 rounded-md px-4 py-3 text-sm flex items-center gap-2">
          <Zap className="w-4 h-4 shrink-0" />
          Mode FIXTURE actif — consommations de démonstration contractuelles, PAS le module Énergie réel.
        </div>
      )}
      {notConnected && (
        <div data-testid="recon-banner-disconnected"
             className="bg-amber-50 border border-amber-200 text-amber-800 rounded-md px-4 py-3 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          Module Énergie non connecté — aucune consommation disponible : tous les rapprochements sont
          « Impossible » tant que <code className="font-mono text-xs">ENERGY_API_BASE_URL</code> n&apos;est pas configurée.
        </div>
      )}

      {/* KPI — catégories jamais mélangées, pas de score global artificiel */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Véhicules analysables" value={kpi.analyzable} icon={CheckCircle2} cls="text-emerald-600" testId="recon-kpi-analyzable" />
        <Kpi label="À contrôler" value={kpi.check} icon={SearchCheck} cls="text-amber-600" testId="recon-kpi-check" />
        <Kpi label="Indicatifs" value={kpi.indicative} icon={HelpCircle} cls="text-blue-600" testId="recon-kpi-indicative" />
        <Kpi label="Impossibles" value={kpi.impossible} icon={XCircle} cls="text-slate-500" testId="recon-kpi-impossible" />
      </div>

      {/* Filtres */}
      <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4 space-y-3">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Période</p>
            <Select value={preset} onValueChange={(v) => { setPreset(v); const r = presetRange(v); if (r) setRange(r); }}>
              <SelectTrigger data-testid="recon-filter-period"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="month">Ce mois</SelectItem>
                <SelectItem value="prev_month">Mois précédent</SelectItem>
                <SelectItem value="last30">30 derniers jours</SelectItem>
                <SelectItem value="year">Année en cours</SelectItem>
                <SelectItem value="custom">Personnalisé</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {preset === "custom" && (
            <>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Du</p>
                <Input type="date" data-testid="recon-filter-from" value={range?.from || ""}
                       onChange={(e) => setRange(r => ({ ...r, from: e.target.value }))} />
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Au</p>
                <Input type="date" data-testid="recon-filter-to" value={range?.to || ""}
                       onChange={(e) => setRange(r => ({ ...r, to: e.target.value }))} />
              </div>
            </>
          )}
          <FilterSelect k="vehicle" label="Véhicule" testId="recon-filter-vehicle"
                        value={filters.vehicle} onChange={setFilter}
                        options={rows.map(r => ({ value: r.vehicle_id, label: r.plate || r.model }))} />
          <FilterSelect k="group" label="Groupe (plaque)" testId="recon-filter-group"
                        value={filters.group} onChange={setFilter}
                        options={groups.map(g => ({ value: g, label: g }))} />
          <FilterSelect k="powertrain" label="Motorisation" testId="recon-filter-powertrain"
                        value={filters.powertrain} onChange={setFilter}
                        options={["ICE", "HEV", "PHEV", "BEV", "UNKNOWN"].map(p => ({ value: p, label: POWERTRAIN_LABEL[p] }))} />
          <FilterSelect k="measurement" label="Type de mesure" testId="recon-filter-measurement"
                        value={filters.measurement} onChange={setFilter}
                        options={["MEASURED", "ESTIMATED", "REFERENCE", "NONE"].map(m => ({ value: m, label: MEASUREMENT_LABEL[m] }))} />
          <FilterSelect k="reliability" label="Fiabilité" testId="recon-filter-reliability"
                        value={filters.reliability} onChange={setFilter}
                        options={["EXPLOITABLE", "INDICATIF", "IMPOSSIBLE"].map(m => ({ value: m, label: RELIABILITY_LABEL[m] }))} />
          <FilterSelect k="status" label="Statut" testId="recon-filter-status"
                        value={filters.status} onChange={setFilter}
                        options={Object.keys(STATUS_META).map(s => ({ value: s, label: STATUS_META[s].label }))} />
        </div>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="text-xs text-slate-500" data-testid="recon-threshold-info">
            {data?.thresholds?.configured ? (
              <>Seuil configuré : {[
                data.thresholds.percent != null ? `${data.thresholds.percent} %` : null,
                data.thresholds.liters != null ? `${data.thresholds.liters} L` : null,
              ].filter(Boolean).join(" · ")} — alertes automatiques désactivées.</>
            ) : (
              "Aucun seuil configuré — rapprochement en mode diagnostic."
            )}
          </p>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" data-testid="recon-export-btn"
                    className="text-xs h-7"
                    onClick={() => doExport("xlsx")} disabled={!!exporting || loading}>
              {exporting === "xlsx" ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <FileSpreadsheet className="w-3.5 h-3.5 mr-1" />}
              Exporter Excel
            </Button>
            <Button size="sm" variant="outline" data-testid="recon-export-pdf-btn"
                    className="text-xs h-7"
                    onClick={() => doExport("pdf")} disabled={!!exporting || loading}>
              {exporting === "pdf" ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <FileText className="w-3.5 h-3.5 mr-1" />}
              Exporter PDF
            </Button>
            <Button size="sm" variant="outline" data-testid="recon-filter-reset"
                    className="text-xs h-7"
                    onClick={() => setFilters(DEFAULT_FILTERS)}>
              Réinitialiser les filtres
            </Button>
          </div>
        </div>
      </Card>

      {/* Tableau principal */}
      <Card className="bg-white border-slate-200 shadow-sm rounded-md overflow-x-auto">
        {loading ? (
          <div className="py-16 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" /></div>
        ) : filtered.length === 0 ? (
          <div className="py-16 text-center text-slate-500 text-sm">Aucun véhicule ne correspond aux filtres.</div>
        ) : (
          <table className="w-full text-sm" data-testid="recon-table">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-400">
                <th className="py-3 px-4">Véhicule</th>
                <th className="py-3 px-4 hidden md:table-cell">Modèle</th>
                <th className="py-3 px-4 hidden lg:table-cell">Période</th>
                <th className="py-3 px-4 hidden md:table-cell">Motorisation</th>
                <th className="py-3 px-4 text-right">Achats</th>
                <th className="py-3 px-4 text-right">Consommation</th>
                <th className="py-3 px-4 text-right">Écart</th>
                <th className="py-3 px-4 text-right hidden md:table-cell">Écart %</th>
                <th className="py-3 px-4 hidden lg:table-cell">Type de mesure</th>
                <th className="py-3 px-4 hidden lg:table-cell">Fiabilité</th>
                <th className="py-3 px-4">Statut</th>
                <th className="py-3 px-4 text-center">Détails</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(r => {
                const cf = r.consumed_fuel;
                return (
                  <tr key={r.vehicle_id} data-testid={`recon-row-${r.vehicle_id}`}
                      className="border-t border-slate-100 hover:bg-slate-50 transition-colors">
                    <td className="py-3 px-4">
                      <span className="font-medium text-slate-800 font-mono text-xs">{r.plate || r.model || "—"}</span>
                      {!r.mapped && (
                        <Badge variant="outline" data-testid={`recon-unmapped-${r.vehicle_id}`}
                               className="ml-2 bg-rose-50 text-rose-600 border-rose-200 text-[10px] px-1.5 py-0"
                               title="Véhicule sans tracker Navixy associé — rapprochement impossible">
                          Non mappé
                        </Badge>
                      )}
                    </td>
                    <td className="py-3 px-4 text-xs text-slate-500 hidden md:table-cell">{r.model || "—"}</td>
                    <td className="py-3 px-4 text-xs text-slate-500 hidden lg:table-cell whitespace-nowrap">{periodLabel}</td>
                    <td className="py-3 px-4 text-xs text-slate-600 hidden md:table-cell">{POWERTRAIN_LABEL[r.powertrain] || r.powertrain}</td>
                    <td className="py-3 px-4 text-right text-slate-700 whitespace-nowrap">
                      {r.purchased.tx_count > 0 ? `${r.purchased.liters.toFixed(1)} L` : "—"}
                      {r.purchased.kwh > 0 && <span className="text-xs text-slate-400"> + {r.purchased.kwh.toFixed(1)} kWh</span>}
                    </td>
                    <td className="py-3 px-4 text-right whitespace-nowrap">
                      {cf && cf.value != null ? (
                        <span className="inline-flex items-center gap-1.5">
                          <span className="text-slate-700">{Number(cf.value).toFixed(1)} L</span>
                          <EnergyBadge metric={cf} />
                        </span>
                      ) : (
                        <span className="text-slate-400 italic">Non disponible</span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-right font-medium whitespace-nowrap">
                      {r.gap_l != null
                        ? <span className={r.gap_l >= 0 ? "text-slate-700" : "text-rose-600"}>{r.gap_l > 0 ? "+" : ""}{r.gap_l.toFixed(1)} L</span>
                        : <span className="text-slate-400">—</span>}
                    </td>
                    <td className="py-3 px-4 text-right text-slate-600 hidden md:table-cell">
                      {r.gap_pct != null ? `${r.gap_pct > 0 ? "+" : ""}${r.gap_pct.toFixed(1)} %` : "—"}
                    </td>
                    <td className="py-3 px-4 hidden lg:table-cell text-xs text-slate-600">
                      {MEASUREMENT_LABEL[r.consumption_measurement_type] || "Aucun"}
                    </td>
                    <td className="py-3 px-4 hidden lg:table-cell text-xs text-slate-600">
                      {RELIABILITY_LABEL[r.reliability]}
                    </td>
                    <td className="py-3 px-4">
                      <StatusBadge status={r.status} reason={r.status_reason} testId={`recon-status-${r.vehicle_id}`} />
                    </td>
                    <td className="py-3 px-4 text-center">
                      <Button size="sm" variant="ghost" className="h-7 text-slate-400 hover:text-[#2196F3]"
                              onClick={() => setDetail(r)} data-testid={`recon-details-${r.vehicle_id}`}>
                        <Info className="w-3.5 h-3.5" />
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>

      {/* Préparation des alertes — aperçu uniquement, aucun envoi */}
      <AlertsPreparationPanel range={range}
                              canGenerate={user?.role === "admin" || user?.role === "manager"} />

      {/* Drawer détail */}
      <Sheet open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <SheetContent className="w-full sm:max-w-md overflow-y-auto" data-testid="recon-drawer">
          {detail && (
            <>
              <SheetHeader>
                <SheetTitle className="flex items-center gap-2">
                  <Car className="w-4 h-4 text-[#2196F3]" /> {detail.plate || detail.model}
                </SheetTitle>
                <SheetDescription>Rapprochement achats ↔ consommation · {periodLabel}</SheetDescription>
              </SheetHeader>
              <div className="mt-5 space-y-5 text-sm">
                {/* Explication du statut — toujours visible */}
                <div className={`rounded-md border px-3 py-2.5 ${STATUS_META[detail.status]?.cls || ""}`}
                     data-testid="recon-drawer-reason">
                  <p className="text-[10px] uppercase tracking-wider font-semibold mb-1">
                    Statut : {STATUS_META[detail.status]?.label}
                  </p>
                  <p className="text-xs">{detail.status_reason}</p>
                </div>

                <section className="space-y-1.5">
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Véhicule</p>
                  <div className="text-xs text-slate-600 space-y-1">
                    <p>Modèle : <strong className="text-slate-800">{detail.model || "—"}</strong></p>
                    <p>Plaque : <span className="font-mono">{detail.plate || "—"}</span></p>
                    <p>vehicle_id : <span className="font-mono text-[10px]">{detail.vehicle_id}</span></p>
                    <p>Tracker Navixy : {detail.navixy_tracker_id
                      ? <span className="font-mono">{detail.navixy_tracker_id}</span>
                      : <span className="text-rose-600">absent — rapprochement impossible</span>}</p>
                    <p>Motorisation : {POWERTRAIN_LABEL[detail.powertrain] || detail.powertrain}</p>
                  </div>
                </section>

                <section className="space-y-1.5">
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1">
                    <Fuel className="w-3 h-3" /> Achats (source commerciale)
                  </p>
                  <div className="text-xs text-slate-600 space-y-1" data-testid="recon-drawer-purchases">
                    <p>Transactions : <strong className="text-slate-800">{detail.purchased.tx_count}</strong></p>
                    <p>Litres achetés : <strong className="text-slate-800">{detail.purchased.liters.toFixed(2)} L</strong></p>
                    {detail.purchased.kwh > 0 && <p>Recharges achetées : {detail.purchased.kwh.toFixed(2)} kWh</p>}
                    <p>Montant : {detail.purchased.amount_chf.toFixed(2)} CHF</p>
                    {Object.keys(detail.purchased.sources || {}).length > 0 && (
                      <p>Sources : {Object.entries(detail.purchased.sources)
                        .map(([s, n]) => `${SOURCE_TX_LABEL[s] || s} (${n})`).join(", ")}</p>
                    )}
                  </div>
                </section>

                <section className="space-y-1.5">
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1">
                    <Zap className="w-3 h-3" /> Consommation (source opérationnelle)
                  </p>
                  <div className="text-xs text-slate-600 space-y-1" data-testid="recon-drawer-consumption">
                    {detail.consumed_fuel && detail.consumed_fuel.value != null ? (
                      <>
                        <p className="flex items-center gap-2">Carburant consommé :
                          <strong className="text-slate-800">{Number(detail.consumed_fuel.value).toFixed(2)} {detail.consumed_fuel.unit}</strong>
                          <EnergyBadge metric={detail.consumed_fuel} />
                        </p>
                        <p>Source : {detail.consumed_fuel.source || "—"}</p>
                        <p>Horodatage : {detail.consumed_fuel.timestamp || "—"}</p>
                        <p>Disponibilité : {detail.consumed_fuel.availability}</p>
                      </>
                    ) : (
                      <p className="italic text-slate-400">Non disponible</p>
                    )}
                    {detail.powertrain === "PHEV" && (
                      <div className="mt-2 pt-2 border-t border-slate-100">
                        <p className="text-[10px] uppercase tracking-wider text-slate-400">Électricité (séparée — jamais comparée aux litres)</p>
                        {detail.consumed_electric && detail.consumed_electric.value != null ? (
                          <p className="flex items-center gap-2 mt-1">kWh consommés :
                            <strong className="text-slate-800">{Number(detail.consumed_electric.value).toFixed(2)} kWh</strong>
                            <EnergyBadge metric={detail.consumed_electric} />
                          </p>
                        ) : (
                          <p className="italic text-slate-400 mt-1">kWh consommés : Non disponible</p>
                        )}
                      </div>
                    )}
                  </div>
                </section>

                <section className="space-y-1.5">
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1">
                    <Scale className="w-3 h-3" /> Rapprochement
                  </p>
                  <div className="text-xs text-slate-600 space-y-1" data-testid="recon-drawer-gap">
                    <p>Écart absolu : {detail.gap_l != null ? `${detail.gap_l > 0 ? "+" : ""}${detail.gap_l.toFixed(2)} L` : "—"}</p>
                    <p>Écart % : {detail.gap_pct != null ? `${detail.gap_pct > 0 ? "+" : ""}${detail.gap_pct.toFixed(1)} %` : "—"}</p>
                    <p>Type de mesure : {MEASUREMENT_LABEL[detail.consumption_measurement_type] || "Aucun"}</p>
                    <p>Fiabilité : {RELIABILITY_LABEL[detail.reliability]}</p>
                  </div>
                </section>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
