import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { ScrollText, RefreshCw } from "lucide-react";

function detailsToText(row) {
  const d = row.details && Object.keys(row.details).length ? row.details : null;
  if (d) return JSON.stringify(d);
  const extra = Object.entries(row)
    .filter(([k]) => !["id", "action", "at", "ts", "tenant_id", "user_id",
                       "user_email", "user_role", "details"].includes(k))
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`);
  return extra.join(" · ");
}

export default function AdminAuditPage() {
  const [rows, setRows] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [tenant, setTenant] = useState("all");
  const [action, setAction] = useState("");
  const [loading, setLoading] = useState(true);

  const tenantName = (tid) => tenants.find((t) => t.id === tid)?.name || tid || "—";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 300 };
      if (tenant !== "all") params.tenant_id = tenant;
      if (action.trim()) params.action = action.trim();
      const { data } = await api.get("/admin/audit", { params });
      setRows(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  }, [tenant, action]);

  useEffect(() => {
    api.get("/admin/tenants").then(({ data }) => setTenants(data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div data-testid="admin-audit-page" className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400 font-semibold">Super Admin</p>
          <h1 className="text-2xl font-semibold text-slate-900 flex items-center gap-2">
            <ScrollText className="w-6 h-6" /> Journal d'audit
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Connexions, exports, modifications — traçabilité complète par client.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={tenant} onValueChange={setTenant}>
            <SelectTrigger data-testid="audit-tenant-filter" className="w-[190px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous les clients</SelectItem>
              {tenants.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input data-testid="audit-action-filter" className="w-[180px]" placeholder="Filtrer par action…"
                 value={action} onChange={(e) => setAction(e.target.value)} />
          <Button data-testid="audit-refresh" variant="outline" size="icon" onClick={load}>
            <RefreshCw className="w-4 h-4" />
          </Button>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3">Client</th>
              <th className="px-4 py-3">Utilisateur</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">Détails</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">Chargement…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">Aucune entrée</td></tr>
            ) : rows.map((r, i) => (
              <tr key={r.id || i} className="border-b border-slate-100 hover:bg-slate-50/60">
                <td className="px-4 py-2.5 text-xs text-slate-500 whitespace-nowrap">
                  {fmtDateTime(r.at || r.ts)}
                </td>
                <td className="px-4 py-2.5 text-xs">{tenantName(r.tenant_id)}</td>
                <td className="px-4 py-2.5 text-xs">{r.user_email || r.actor || "—"}</td>
                <td className="px-4 py-2.5">
                  <span className="font-mono text-xs bg-slate-100 rounded px-1.5 py-0.5">
                    {r.action || "—"}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-xs text-slate-500 max-w-md truncate">
                  {detailsToText(r)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
