import { useCallback, useEffect, useMemo, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { RefreshCw } from "lucide-react";

const STATUS = {
  active:  { label: "Actif",      cls: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  ended:   { label: "Terminé",    cls: "bg-slate-100 text-slate-600 border-slate-200" },
  expired: { label: "Expiré",     cls: "bg-amber-100 text-amber-700 border-amber-200" },
  denied:  { label: "Refusé",     cls: "bg-rose-100 text-rose-700 border-rose-200" },
  pending: { label: "En attente", cls: "bg-sky-100 text-sky-700 border-sky-200" },
};
const ROLE_LABEL = { admin: "Admin", manager: "Gestionnaire", driver: "Chauffeur", lecture_seule: "Lecture seule" };
const SOURCE_LABEL = {
  super_admin_impersonation: "Super Admin",
  admin_client_impersonation: "Admin Client",
};

function fmtDuration(sec) {
  if (sec == null) return "—";
  if (sec < 60) return `${sec} s`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m} min ${sec % 60} s`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

const EMPTY_FILTERS = { tenant: "all", actor: "", target: "", role: "all", status: "all", from: "", to: "" };

export default function TeamImpersonationPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "superadmin";
  const [rows, setRows] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [loading, setLoading] = useState(true);

  const tenantName = (tid) => tenants.find((t) => t.id === tid)?.name || tid || "—";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (isSuperAdmin) params.tenant_id = filters.tenant;
      const { data } = await api.get("/livre/team/impersonation-sessions", { params });
      setRows(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  }, [isSuperAdmin, filters.tenant]);

  useEffect(() => {
    if (isSuperAdmin) api.get("/admin/tenants").then(({ data }) => setTenants(data)).catch(() => {});
  }, [isSuperAdmin]);
  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => rows.filter((r) => {
    if (filters.actor && !(r.actor_email || "").toLowerCase().includes(filters.actor.toLowerCase())
        && !(r.actor_name || "").toLowerCase().includes(filters.actor.toLowerCase())) return false;
    if (filters.target && !(r.target_email || "").toLowerCase().includes(filters.target.toLowerCase())
        && !(r.target_name || "").toLowerCase().includes(filters.target.toLowerCase())) return false;
    if (filters.role !== "all" && r.target_role !== filters.role) return false;
    if (filters.status !== "all" && r.status !== filters.status) return false;
    const at = r.created_at || "";
    if (filters.from && at < filters.from) return false;
    if (filters.to && at > `${filters.to}T23:59:59`) return false;
    return true;
  }), [rows, filters]);

  const set = (k, v) => setFilters((f) => ({ ...f, [k]: v }));

  return (
    <div data-testid="team-impersonation-page" className="space-y-4">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <p className="text-xs text-slate-400 max-w-xl">
          Historique en lecture seule des sessions « Se connecter comme… » — non modifiable, pour
          garantir la traçabilité.
        </p>
        <Button data-testid="imp-sessions-refresh" variant="outline" size="sm" onClick={load}>
          <RefreshCw className="w-4 h-4 mr-1.5" /> Actualiser
        </Button>
      </div>

      <div className="flex items-end gap-2 flex-wrap bg-white rounded-lg border border-slate-200 p-3">
        {isSuperAdmin && (
          <Select value={filters.tenant} onValueChange={(v) => set("tenant", v)}>
            <SelectTrigger data-testid="imp-filter-tenant" className="w-[180px] h-9">
              <SelectValue placeholder="Entreprise" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Toutes les entreprises</SelectItem>
              {tenants.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}
            </SelectContent>
          </Select>
        )}
        <Input data-testid="imp-filter-actor" className="w-[180px] h-9" placeholder="Administrateur…"
               value={filters.actor} onChange={(e) => set("actor", e.target.value)} />
        <Input data-testid="imp-filter-target" className="w-[180px] h-9" placeholder="Utilisateur consulté…"
               value={filters.target} onChange={(e) => set("target", e.target.value)} />
        <Select value={filters.role} onValueChange={(v) => set("role", v)}>
          <SelectTrigger data-testid="imp-filter-role" className="w-[150px] h-9"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tous les rôles</SelectItem>
            {Object.entries(ROLE_LABEL).map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={filters.status} onValueChange={(v) => set("status", v)}>
          <SelectTrigger data-testid="imp-filter-status" className="w-[150px] h-9"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tous les statuts</SelectItem>
            {Object.entries(STATUS).map(([v, s]) => <SelectItem key={v} value={v}>{s.label}</SelectItem>)}
          </SelectContent>
        </Select>
        <Input data-testid="imp-filter-from" type="date" className="w-[150px] h-9"
               value={filters.from} onChange={(e) => set("from", e.target.value)} />
        <Input data-testid="imp-filter-to" type="date" className="w-[150px] h-9"
               value={filters.to} onChange={(e) => set("to", e.target.value)} />
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              {isSuperAdmin && <th className="px-4 py-3">Entreprise</th>}
              <th className="px-4 py-3">Administrateur réel</th>
              <th className="px-4 py-3">Utilisateur consulté</th>
              <th className="px-4 py-3">Rôle</th>
              <th className="px-4 py-3">Début</th>
              <th className="px-4 py-3">Fin</th>
              <th className="px-4 py-3">Durée</th>
              <th className="px-4 py-3">Statut</th>
              <th className="px-4 py-3">Source</th>
              <th className="px-4 py-3">Motif</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={10} className="px-4 py-8 text-center text-slate-400">Chargement…</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={10} className="px-4 py-8 text-center text-slate-400">Aucune session d'aperçu</td></tr>
            ) : filtered.map((r) => {
              const s = STATUS[r.status] || STATUS.ended;
              return (
                <tr key={r.id} data-testid={`imp-session-row-${r.id}`}
                    className="border-b border-slate-100 hover:bg-slate-50/60">
                  {isSuperAdmin && <td className="px-4 py-2.5 text-xs">{tenantName(r.tenant_id)}</td>}
                  <td className="px-4 py-2.5 text-xs font-medium text-slate-800">{r.actor_email}</td>
                  <td className="px-4 py-2.5 text-xs">{r.target_name || r.target_email}
                    <span className="block text-[10px] text-slate-400">{r.target_email}</span>
                  </td>
                  <td className="px-4 py-2.5 text-xs">{ROLE_LABEL[r.target_role] || r.target_role || "—"}</td>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap">{fmtDateTime(r.used_at || r.created_at)}</td>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap">{r.ended_at ? fmtDateTime(r.ended_at) : "—"}</td>
                  <td className="px-4 py-2.5 text-xs">{fmtDuration(r.duration_seconds)}</td>
                  <td className="px-4 py-2.5">
                    <span data-testid={`imp-session-status-${r.id}`}
                          className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[11px] font-medium ${s.cls}`}>
                      {s.label}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs">{SOURCE_LABEL[r.auth_source] || r.auth_source}</td>
                  <td className="px-4 py-2.5 text-xs text-slate-500 max-w-[200px] truncate" title={r.reason || ""}>
                    {r.reason || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
