import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  Bluetooth, Loader2, RefreshCw, Filter, CheckCircle2, XCircle,
  Edit3, AlertTriangle, Smartphone, History, Radio, Users, Tag, Bug, Trash2, Eraser, Sparkles,
} from "lucide-react";
import { useRealtime } from "@/hooks/useRealtime";
import BleTagsManager from "@/components/livre/BleTagsManager";
import BleDebugDialog from "@/components/livre/BleDebugDialog";
import SubTabs from "@/components/layout/SubTabs";
import { SourceBadge } from "@/components/livre/SourceBadge";

const STATUS_BADGE = {
  open:       { color: "bg-blue-50 text-blue-700 border-blue-200",         label: "Ouverte" },
  automatic:  { color: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Automatique" },
  confirmed:  { color: "bg-emerald-100 text-emerald-800 border-emerald-300", label: "Confirmé" },
  pending:    { color: "bg-amber-50 text-amber-700 border-amber-200",       label: "En attente" },
  manual:     { color: "bg-violet-50 text-violet-700 border-violet-200",    label: "Manuel" },
  conflict:   { color: "bg-rose-50 text-rose-700 border-rose-200",          label: "Conflit" },
  closed:     { color: "bg-slate-100 text-slate-600 border-slate-200",      label: "Clôturée" },
  cancelled:  { color: "bg-slate-100 text-slate-500 border-slate-200",      label: "Annulée" },
};

function fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-CH", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
}

function Confidence({ value }) {
  const v = value ?? 0;
  const color = v >= 75 ? "bg-emerald-500" : v >= 50 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="flex items-center gap-2 min-w-[110px]">
      <div className="h-1.5 w-16 bg-slate-200 rounded overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${v}%` }} />
      </div>
      <span className="text-xs font-mono text-slate-600 w-8 text-right">{v}</span>
    </div>
  );
}

export default function IdentificationPage() {
  const [rows, setRows] = useState([]);
  const [kpis, setKpis] = useState(null);
  const [drivers, setDrivers] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    status: "all", source: "all", driver_id: "all", vehicle_id: "all", start: "", end: "",
  });
  const [occupantsOf, setOccupantsOf] = useState(null);
  const [editing, setEditing] = useState(null);
  const [editForm, setEditForm] = useState({ driver_id: "", vehicle_id: "", status: "" });
  const [resolving, setResolving] = useState(null);    // session_id in conflict
  const [tagsManagerOpen, setTagsManagerOpen] = useState(false);
  const [debugOpen, setDebugOpen] = useState(false);
  const [resolveChoice, setResolveChoice] = useState("");

  async function loadAll() {
    setLoading(true);
    try {
      const params = {};
      if (filters.status && filters.status !== "all") params.status = filters.status;
      if (filters.source && filters.source !== "all") params.source = filters.source;
      if (filters.driver_id && filters.driver_id !== "all") params.driver_id = filters.driver_id;
      if (filters.vehicle_id && filters.vehicle_id !== "all") params.vehicle_id = filters.vehicle_id;
      if (filters.start) params.start = new Date(filters.start).toISOString();
      if (filters.end) params.end = new Date(filters.end).toISOString();
      const [s, k, d, v] = await Promise.all([
        api.get("/livre/ble/sessions", { params }).then(r => r.data),
        api.get("/livre/ble/dashboard", { params }).then(r => r.data),
        api.get("/livre/drivers").then(r => r.data),
        api.get("/livre/vehicles").then(r => r.data),
      ]);
      setRows(s); setKpis(k); setDrivers(d); setVehicles(v);
    } finally { setLoading(false); }
  }
  useEffect(() => { loadAll(); /* eslint-disable-next-line */ },
    [filters.status, filters.source, filters.driver_id, filters.vehicle_id, filters.start, filters.end]);

  // Realtime channel — push toasts and trigger silent refresh
  const { connected } = useRealtime((evt) => {
    if (evt.type === "conflict_detected") {
      const drivers = evt.data?.drivers || [];
      toast.warning(`Conflit BLE détecté · ${drivers.length} chauffeurs sur le même véhicule`,
        { description: "Cliquez pour résoudre depuis la page Identification." });
      loadAll();
    } else if (evt.type === "conflict_resolved") {
      toast.success("Conflit résolu");
      loadAll();
    } else if (evt.type === "session_opened" || evt.type === "session_updated") {
      // Silent refresh for new sessions (avoid spamming toasts)
      loadAll();
    }
  });

  // Find rival sessions for a given conflict session (same vehicle, status=conflict)
  function rivalsOf(r) {
    return rows.filter(x =>
      x.vehicle_id === r.vehicle_id &&
      x.status === "conflict" &&
      x.id !== r.id
    );
  }

  async function resolveConflict() {
    if (!resolving || !resolveChoice) return;
    try {
      const { data } = await api.post(`/livre/ble/sessions/${resolving.id}/resolve`,
        { winner_driver_id: resolveChoice });
      toast.success(`Conflit résolu — ${data.closed_count} session(s) clôturée(s)`);
      setResolving(null); setResolveChoice("");
      loadAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    }
  }

  function openEdit(r) {
    setEditing(r);
    setEditForm({ driver_id: r.driver_id, vehicle_id: r.vehicle_id, status: r.status });
  }

  async function saveEdit() {
    try {
      await api.put(`/livre/ble/sessions/${editing.id}`, editForm);
      toast.success("Session mise à jour");
      setEditing(null);
      loadAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    }
  }

  async function validate(r) {
    try {
      await api.put(`/livre/ble/sessions/${r.id}`, { status: "confirmed" });
      toast.success("Session validée");
      loadAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    }
  }

  async function cancel(r) {
    if (!window.confirm(`Annuler la session de ${r.driver_name || r.driver_id} ?`)) return;
    try {
      await api.put(`/livre/ble/sessions/${r.id}`, { status: "cancelled" });
      toast.success("Session annulée");
      loadAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    }
  }

  async function deleteSession(r) {
    if (!window.confirm(
      `Supprimer définitivement la session de ${r.driver_name || r.driver_id} ?\n\n` +
      `Action IRRÉVERSIBLE — la ligne disparaîtra de l'historique BLE.`
    )) return;
    try {
      await api.delete(`/livre/ble/sessions/${r.id}`);
      toast.success("Session supprimée");
      loadAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Suppression refusée");
    }
  }

  async function clearAllSessions() {
    // Two-step confirm to avoid accidental wipe of historical BLE data.
    const dry = await api.post("/livre/ble/sessions/clear-all", { dry_run: true }).then(r => r.data);
    if (!window.confirm(
      `Supprimer DÉFINITIVEMENT toutes les sessions BLE ?\n\n` +
      `${dry.sessions_to_delete} session(s) seront effacées de l'historique.\n` +
      `Cette action est IRRÉVERSIBLE.`
    )) return;
    try {
      const { data } = await api.post("/livre/ble/sessions/clear-all", { dry_run: false });
      toast.success(`${data.sessions_deleted} session(s) supprimée(s)`);
      loadAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec du nettoyage");
    }
  }

  async function seedDemoSessions() {
    try {
      const { data } = await api.post("/livre/ble/sessions/seed-demo");
      toast.success(`${data.created} sessions démo créées (5 chauffeurs distincts)`);
      loadAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec du seed");
    }
  }

  return (
    <div data-testid="identification-page" className="space-y-5 animate-in fade-in slide-in-from-bottom-2 duration-300 max-w-[1320px]">
      <div>
        <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400">Identification BLE</p>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 flex items-center gap-2.5 mt-1">
          <Bluetooth className="w-5 h-5 text-[#2196F3]" /> Identification chauffeurs
          <span className={`ml-2 inline-flex items-center gap-1.5 text-[10px] font-semibold px-2 py-0.5 rounded-full ${connected ? "bg-emerald-50 text-emerald-700 border border-emerald-200" : "bg-slate-100 text-slate-500 border border-slate-200"}`}
                data-testid="ident-realtime-status">
            <Radio className={`w-3 h-3 ${connected ? "animate-pulse" : ""}`} />
            {connected ? "Live" : "Hors-ligne"}
          </span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setTagsManagerOpen(true)}
            className="ml-auto h-8 text-[#2196F3] border-[#2196F3]/30 hover:bg-[#2196F3]/5"
            data-testid="ident-open-tags-manager"
          >
            <Tag className="w-3.5 h-3.5 mr-1.5" /> Gérer les tags BLE
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setDebugOpen(true)}
            className="h-8 text-amber-600 border-amber-300 hover:bg-amber-50"
            data-testid="ident-open-debug"
          >
            <Bug className="w-3.5 h-3.5 mr-1.5" /> Debug BLE
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={seedDemoSessions}
            className="h-8 text-slate-600 border-slate-300 hover:bg-slate-50"
            data-testid="ident-seed-demo"
            title="Crée 5 sessions démo avec 5 chauffeurs distincts"
          >
            <Sparkles className="w-3.5 h-3.5 mr-1.5" /> Démo (5)
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={clearAllSessions}
            className="h-8 text-rose-600 border-rose-300 hover:bg-rose-50"
            data-testid="ident-clear-all"
            title="Supprime TOUTES les sessions BLE de l'historique (irréversible)"
          >
            <Eraser className="w-3.5 h-3.5 mr-1.5" /> Vider sessions
          </Button>
        </h1>
        <p className="text-xs text-slate-500 mt-1">
          Détection automatique de l&apos;association chauffeur ↔ véhicule grâce aux tags Bluetooth installés à bord.
        </p>
      </div>

      {/* Quick status sub-tabs */}
      <SubTabs
        current={filters.status}
        onChange={(v) => setFilters({ ...filters, status: v })}
        tabs={[
          { value: "all",       label: "Toutes",       testId: "ident-tab-all" },
          { value: "automatic", label: "Automatiques", testId: "ident-tab-auto" },
          { value: "pending",   label: "À valider",    testId: "ident-tab-pending" },
          { value: "conflict",  label: "Conflits",     testId: "ident-tab-conflict" },
          { value: "manual",    label: "Manuelles",    testId: "ident-tab-manual" },
          { value: "closed",    label: "Clôturées",    testId: "ident-tab-closed" },
        ]}
      />

      {/* KPI cards — identité chauffeur (APP/BLE/MANUEL), cliquables ; période = filtres dates */}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3" data-testid="ident-kpis">
        {[
          { k: "total_sessions",     label: "Sessions",         cls: "text-slate-700",
            filter: { status: "all", source: "all" }, title: "Sessions chauffeur↔véhicule de la période — clic : réinitialiser les filtres" },
          { k: "identified_app",     label: "Identifiés APP",   cls: "text-blue-600",   icon: Smartphone,
            filter: { source: "APP" }, title: "Identité issue de l'application (« Je conduis »)" },
          { k: "identified_ble",     label: "Identifiés BLE",   cls: "text-cyan-600",   icon: Bluetooth,
            filter: { source: "BLE" }, title: "Identité issue du BLE uniquement — validation terrain BLE en attente" },
          { k: "identified_app_ble", label: "APP + BLE",        cls: "text-emerald-600", icon: CheckCircle2,
            filter: { source: "APP+BLE" }, title: "Les deux sources sont cohérentes" },
          { k: "pending_validation", label: "À valider",        cls: "text-amber-600",  icon: AlertTriangle,
            filter: { status: "pending" }, title: "Sessions sans attribution suffisamment certaine" },
          { k: "conflicts",          label: "Conflits",         cls: "text-rose-600",   icon: XCircle,
            filter: { status: "conflict" }, title: "Contradiction entre plusieurs identités/sources" },
          { k: "unidentified",       label: "Non identifiés",   cls: "text-slate-500",
            getter: (kk) => kk?.trips?.unidentified, title: "Trajets de la période sans chauffeur identifié (conservés, jamais supprimés)" },
          { k: "success_rate",       label: "Taux d'identification", cls: "text-emerald-600", suffix: "%",
            title: "Formule : (Sessions − À valider − Conflits) ÷ Sessions de la période" },
        ].map(c => {
          const Icon = c.icon;
          const value = kpis ? (c.getter ? (c.getter(kpis) ?? 0) : (kpis[c.k] ?? 0)) : "—";
          return (
            <Card key={c.k} title={c.title}
              onClick={c.filter ? () => setFilters({ ...filters, status: "all", source: "all", ...c.filter }) : undefined}
              className={`bg-white p-3 border-slate-200 shadow-sm rounded-md transition-colors ${c.filter ? "cursor-pointer hover:border-[#2196F3]/50 hover:bg-blue-50/30" : ""}`}
              data-testid={`ident-kpi-${c.k}`}>
              <p className="text-[10px] uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                {Icon && <Icon className="w-3 h-3" />} {c.label}
              </p>
              <p className={`text-xl font-semibold mt-0.5 ${c.cls}`}>
                {value}{c.suffix || ""}
              </p>
            </Card>
          );
        })}
      </div>

      {/* Mode de trajet PRO/PRIVÉ — zone dédiée, DISTINCT de l'identité chauffeur */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 px-1"
           data-testid="ident-trip-mode-strip">
        <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
          Mode de trajet (PRO/PRIVÉ — distinct de l'identité chauffeur) :
        </span>
        <span data-testid="ident-forced-pro">Forcés PRO (app) : <strong className="text-blue-600">{kpis?.trips?.forced_pro ?? 0}</strong></span>
        <span data-testid="ident-forced-perso">Forcés PRIVÉ (app) : <strong className="text-slate-700">{kpis?.trips?.forced_perso ?? 0}</strong></span>
        <span data-testid="ident-detections-count">Détections BLE : <strong className="text-slate-600">{kpis?.detections ?? 0}</strong></span>
      </div>

      {/* Filters */}
      <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="w-4 h-4 text-slate-500" />
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-600">Filtres</p>
          <Button size="sm" variant="ghost" onClick={loadAll} disabled={loading} className="ml-auto h-7"
            data-testid="ident-refresh">
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <RefreshCw className="w-3.5 h-3.5 mr-1" />}
            Rafraîchir
          </Button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Statut</p>
            <Select value={filters.status} onValueChange={(v) => setFilters({ ...filters, status: v })}>
              <SelectTrigger data-testid="ident-filter-status"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                <SelectItem value="automatic">Automatique</SelectItem>
                <SelectItem value="confirmed">Confirmé</SelectItem>
                <SelectItem value="pending">À valider</SelectItem>
                <SelectItem value="conflict">Conflit</SelectItem>
                <SelectItem value="manual">Manuel</SelectItem>
                <SelectItem value="closed">Clôturée</SelectItem>
                <SelectItem value="cancelled">Annulée</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Source</p>
            <Select value={filters.source} onValueChange={(v) => setFilters({ ...filters, source: v })}>
              <SelectTrigger data-testid="ident-filter-source"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Toutes</SelectItem>
                <SelectItem value="APP">APP</SelectItem>
                <SelectItem value="BLE">BLE</SelectItem>
                <SelectItem value="APP+BLE">APP + BLE</SelectItem>
                <SelectItem value="MANUEL">MANUEL</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Chauffeur</p>
            <Select value={filters.driver_id} onValueChange={(v) => setFilters({ ...filters, driver_id: v })}>
              <SelectTrigger data-testid="ident-filter-driver"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                {drivers.map(d => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Véhicule</p>
            <Select value={filters.vehicle_id} onValueChange={(v) => setFilters({ ...filters, vehicle_id: v })}>
              <SelectTrigger data-testid="ident-filter-vehicle"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                {vehicles.map(v => <SelectItem key={v.id} value={v.id}>{v.plate}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Du</p>
            <Input type="date" data-testid="ident-filter-start"
              value={filters.start} onChange={(e) => setFilters({ ...filters, start: e.target.value })} />
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Au</p>
            <Input type="date" data-testid="ident-filter-end"
              value={filters.end} onChange={(e) => setFilters({ ...filters, end: e.target.value })} />
          </div>
        </div>
      </Card>

      {/* Sessions table */}
      <Card className="bg-white border-slate-200 shadow-sm rounded-md overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="ident-table">
            <thead>
              <tr className="bg-slate-50 text-slate-500 text-[10px] font-semibold uppercase tracking-wider">
                <th className="text-left py-3 px-4">Date</th>
                <th className="text-left py-3 px-4">Chauffeur</th>
                <th className="text-left py-3 px-4">Véhicule</th>
                <th className="text-left py-3 px-4">Confiance</th>
                <th className="text-left py-3 px-4">Source</th>
                <th className="text-left py-3 px-4">Mode trajet</th>
                <th className="text-left py-3 px-4">Statut</th>
                <th className="text-left py-3 px-4">Détections</th>
                <th className="text-right py-3 px-4">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9} className="py-10 text-center text-slate-400">
                  <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> Chargement…
                </td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={9} className="py-10 text-center text-slate-400">
                  Aucune session. Activez la console chauffeur PWA ou utilisez la simulation depuis Paramètres.
                </td></tr>
              ) : rows.map(r => {
                const meta = STATUS_BADGE[r.status] || STATUS_BADGE.open;
                return (
                  <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50/60"
                    data-testid={`ident-row-${r.id}`}>
                    <td className="py-3 px-4 text-xs font-mono text-slate-600">
                      {fmtDate(r.started_at)}<br/>
                      <span className="text-slate-400">→ {fmtDate(r.ended_at || r.last_seen)}</span>
                    </td>
                    <td className="py-3 px-4 text-sm text-slate-800 font-medium">
                      {r.driver_name || "—"}
                      {r.occupants_count > 0 && (
                        <button type="button"
                          onClick={() => setOccupantsOf(r)}
                          className="block text-[10px] text-amber-600 hover:underline mt-0.5"
                          title="Autres personnes détectées (présence BLE, non confirmées comme conducteurs)"
                          data-testid={`ident-occupants-${r.id}`}>
                          +{r.occupants_count} détecté{r.occupants_count > 1 ? "s" : ""}
                        </button>
                      )}
                    </td>
                    <td className="py-3 px-4 text-sm">
                      <p className="font-mono text-xs">{r.vehicle_plate || "—"}</p>
                      <p className="text-[10px] text-slate-400">{r.vehicle_model}</p>
                    </td>
                    <td className="py-3 px-4">
                      {r.confidence == null
                        ? (r.status === "confirmed"
                          ? <span className="text-xs font-medium text-emerald-700">Confirmé</span>
                          : <span className="text-xs text-slate-400">—</span>)
                        : <Confidence value={r.confidence} />}
                    </td>
                    <td className="py-3 px-4">
                      <SourceBadge source={r.identification_source} />
                    </td>
                    <td className="py-3 px-4">
                      {r.mobile_override ? (
                        <Badge variant="outline" className={r.mobile_override === "professional"
                          ? "bg-blue-50 text-blue-700 border-blue-200"
                          : "bg-slate-100 text-slate-700 border-slate-300"}>
                          {r.mobile_override === "professional" ? "PRO" : "PRIVÉ"}
                        </Badge>
                      ) : <span className="text-xs text-slate-400">auto</span>}
                    </td>
                    <td className="py-3 px-4">
                      <Badge variant="outline" className={`${meta.color} font-medium`}>{meta.label}</Badge>
                    </td>
                    <td className="py-3 px-4 text-xs text-slate-600 font-mono">{r.detection_count ?? 0}</td>
                    <td className="py-3 px-4 text-right">
                      <div className="inline-flex gap-1">
                        {r.status === "conflict" && (
                          <Button size="sm" variant="outline" className="h-7 text-rose-600 border-rose-200 hover:bg-rose-50"
                            onClick={() => { setResolving(r); setResolveChoice(r.driver_id); }}
                            data-testid={`ident-resolve-${r.id}`}>
                            <Users className="w-3.5 h-3.5 mr-1" /> Résoudre
                          </Button>
                        )}
                        {r.status === "pending" && (
                          <Button size="sm" variant="ghost" className="h-7 text-emerald-600"
                            onClick={() => validate(r)} data-testid={`ident-validate-${r.id}`}>
                            <CheckCircle2 className="w-3.5 h-3.5" />
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" className="h-7 text-slate-500"
                          onClick={() => openEdit(r)} data-testid={`ident-edit-${r.id}`}>
                          <Edit3 className="w-3.5 h-3.5" />
                        </Button>
                        {r.status !== "cancelled" && r.status !== "closed" && (
                          <Button size="sm" variant="ghost" className="h-7 text-rose-500"
                            onClick={() => cancel(r)} data-testid={`ident-cancel-${r.id}`}
                            title="Annuler la session">
                            <XCircle className="w-3.5 h-3.5" />
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" className="h-7 text-rose-700 hover:bg-rose-50"
                          onClick={() => deleteSession(r)} data-testid={`ident-delete-${r.id}`}
                          title="Supprimer définitivement (admin)">
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Edit modal */}
      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="text-base font-semibold flex items-center gap-2">
              <Edit3 className="w-4 h-4 text-slate-500" /> Modifier la session
            </DialogTitle>
            <DialogDescription className="text-xs text-slate-500">
              Réassigner le chauffeur, le véhicule ou changer le statut de la session BLE.
            </DialogDescription>
          </DialogHeader>
          {editing && (
            <div className="space-y-3 py-2">
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Chauffeur</p>
                <Select value={editForm.driver_id} onValueChange={(v) => setEditForm({ ...editForm, driver_id: v })}>
                  <SelectTrigger data-testid="ident-edit-driver"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {drivers.map(d => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Véhicule</p>
                <Select value={editForm.vehicle_id} onValueChange={(v) => setEditForm({ ...editForm, vehicle_id: v })}>
                  <SelectTrigger data-testid="ident-edit-vehicle"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {vehicles.map(v => <SelectItem key={v.id} value={v.id}>{v.plate} — {v.model}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Statut</p>
                <Select value={editForm.status} onValueChange={(v) => setEditForm({ ...editForm, status: v })}>
                  <SelectTrigger data-testid="ident-edit-status"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {Object.keys(STATUS_BADGE).map(k =>
                      <SelectItem key={k} value={k}>{STATUS_BADGE[k].label}</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>Annuler</Button>
            <Button onClick={saveEdit} className="bg-[#2196F3] hover:bg-[#1E88E5]" data-testid="ident-edit-save">
              Enregistrer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Conflict resolution modal */}
      <Dialog open={!!resolving} onOpenChange={(o) => !o && setResolving(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="text-base font-semibold flex items-center gap-2 text-rose-700">
              <Users className="w-4 h-4" /> Conflit BLE — Qui conduisait réellement ?
            </DialogTitle>
            <DialogDescription className="text-xs text-slate-500">
              Plusieurs chauffeurs ont été détectés sur le même véhicule. Sélectionnez celui qui était au volant.
            </DialogDescription>
          </DialogHeader>
          {resolving && (
            <div className="space-y-2 py-2">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">
                Véhicule : <span className="font-mono text-slate-700">{resolving.vehicle_plate}</span>
              </p>
              <div className="space-y-2">
                {[resolving, ...rivalsOf(resolving)].map(s => (
                  <label key={s.id}
                    className={`flex items-center justify-between gap-3 border rounded-md p-3 cursor-pointer ${
                      resolveChoice === s.driver_id ? "border-[#2196F3] bg-blue-50" : "border-slate-200 hover:border-slate-300"
                    }`}
                    data-testid={`ident-resolve-choice-${s.driver_id}`}>
                    <div className="flex items-center gap-2">
                      <input type="radio" name="winner" value={s.driver_id}
                        checked={resolveChoice === s.driver_id}
                        onChange={() => setResolveChoice(s.driver_id)} />
                      <div>
                        <p className="text-sm font-semibold text-slate-800">{s.driver_name}</p>
                        <p className="text-[11px] text-slate-500 font-mono">détections : {s.detection_count ?? 0}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="text-[10px] uppercase tracking-wider text-slate-400">Confiance</p>
                      <p className="font-mono text-sm">{s.confidence}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => { setResolving(null); setResolveChoice(""); }}>
              Annuler
            </Button>
            <Button onClick={resolveConflict} disabled={!resolveChoice}
              className="bg-[#2196F3] hover:bg-[#1E88E5]" data-testid="ident-resolve-save">
              Valider le choix
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Autres personnes détectées */}
      <Dialog open={!!occupantsOf} onOpenChange={(o) => !o && setOccupantsOf(null)}>
        <DialogContent data-testid="ident-occupants-dialog" className="max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Personnes détectées à bord</DialogTitle>
            <DialogDescription className="text-xs text-slate-500">
              Présence BLE détectée — ces personnes ne sont PAS confirmées comme conducteurs.
            </DialogDescription>
          </DialogHeader>
          {occupantsOf && (
            <div className="space-y-2 py-1">
              <p className="text-xs text-slate-500">
                Véhicule : <span className="font-mono text-slate-700">{occupantsOf.vehicle_plate || "—"}</span>
              </p>
              <div className="rounded-md border border-slate-200 p-3">
                <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Chauffeur de la session</p>
                <p className="text-sm font-semibold text-slate-800">{occupantsOf.driver_name || "—"}</p>
              </div>
              <div className="rounded-md border border-amber-200 bg-amber-50/50 p-3">
                <p className="text-[10px] uppercase tracking-wider text-amber-600 mb-1">Autres personnes détectées</p>
                {(occupantsOf.occupants || []).map((o) => (
                  <p key={o.driver_id} className="text-sm text-slate-700" data-testid={`ident-occupant-${o.driver_id}`}>
                    {o.driver_name || o.driver_id}
                  </p>
                ))}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOccupantsOf(null)}>Fermer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* BLE Tags manager */}
      <BleTagsManager
        open={tagsManagerOpen}
        onOpenChange={setTagsManagerOpen}
        vehicles={vehicles}
      />

      {/* BLE Debug live panel */}
      <BleDebugDialog open={debugOpen} onOpenChange={setDebugOpen} />
    </div>
  );
}
