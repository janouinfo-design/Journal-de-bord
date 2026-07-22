/* Gestion des amendes — main list page.
 *
 * Phase 1 scope:
 *   - Filters (status, vehicle, driver, type, date range, free-text search)
 *   - Sortable table with pagination
 *   - Create / edit via FineFormDialog
 *   - Delete (admin only) with confirm
 *   - KPI summary band (count + total / paid / open amounts on the filtered set)
 *
 * Out of scope (later phases): auto-driver detection, GPS link, OCR upload,
 * email reminders, dashboard analytics page.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api, fmtAmount, fmtDate, fmtDateTime, formatApiErrorDetail, downloadBlob } from "@/lib/api";
import {
  FINE_STATUSES, FINE_STATUS_MAP, STATUS_TONE_CLASS,
  INFRACTION_TYPES, INFRACTION_LABEL, isOverdue,
} from "@/constants/fines";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Loader2, Plus, Pencil, Trash2, RefreshCw, Search, AlertTriangle,
  Receipt, Filter, FileSpreadsheet, FileText, FileDown, BarChart3,
} from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import SubTabs from "@/components/layout/SubTabs";
import FineFormDialog from "@/components/fines/FineFormDialog";

const PAGE_SIZE = 25;

const DEFAULT_FILTERS = {
  q: "", status: "all", vehicle_id: "all", driver_id: "all",
  infraction_type: "all", start: "", end: "",
};

export default function FinesPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const canEdit = user?.role === "admin" || user?.role === "manager";
  const [rows, setRows] = useState([]);
  const [totals, setTotals] = useState({ total_amount: 0, paid_amount: 0, open_amount: 0 });
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [meta, setMeta] = useState({ vehicles: [], drivers: [] });
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [sort, setSort] = useState("-infraction_at");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editId, setEditId] = useState(null);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const loadMeta = useCallback(async () => {
    try {
      const { data } = await api.get("/livre/fines/meta");
      setMeta(data);
    } catch (e) { /* surfaces in list error */ }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { sort, page, page_size: PAGE_SIZE };
      if (filters.q.trim()) params.q = filters.q.trim();
      if (filters.status !== "all") params.status = filters.status;
      if (filters.vehicle_id !== "all") params.vehicle_id = filters.vehicle_id;
      if (filters.driver_id !== "all") params.driver_id = filters.driver_id;
      if (filters.infraction_type !== "all") params.infraction_type = filters.infraction_type;
      if (filters.start) params.start = filters.start;
      if (filters.end) params.end = filters.end;
      const { data } = await api.get("/livre/fines", { params });
      setRows(data.rows || []);
      setTotal(data.total || 0);
      setTotals(data.totals || { total_amount: 0, paid_amount: 0, open_amount: 0 });
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail));
    } finally { setLoading(false); }
  }, [filters, sort, page]);

  useEffect(() => { loadMeta(); }, [loadMeta]);
  useEffect(() => { load(); }, [load]);

  function applyFilter(field, value) {
    setFilters(f => ({ ...f, [field]: value }));
    setPage(1);
  }

  function openCreate() { setEditId(null); setDialogOpen(true); }
  function openEdit(id) { setEditId(id); setDialogOpen(true); }

  async function onDelete(row) {
    if (!window.confirm(
      `Supprimer définitivement l'amende ${row.dossier_number} ?\n\nCette action est IRRÉVERSIBLE.`,
    )) return;
    try {
      await api.delete(`/livre/fines/${row.id}`);
      toast.success(`Amende ${row.dossier_number} supprimée`);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail));
    }
  }

  function toggleSort(key) {
    setSort(prev => (prev === key ? `-${key}` : (prev === `-${key}` ? key : `-${key}`)));
    setPage(1);
  }

  async function exportAs(fmt) {
    const params = { fmt, sort };
    if (filters.q.trim()) params.q = filters.q.trim();
    if (filters.status !== "all") params.status = filters.status;
    if (filters.vehicle_id !== "all") params.vehicle_id = filters.vehicle_id;
    if (filters.driver_id !== "all") params.driver_id = filters.driver_id;
    if (filters.infraction_type !== "all") params.infraction_type = filters.infraction_type;
    if (filters.start) params.start = filters.start;
    if (filters.end) params.end = filters.end;
    try {
      const res = await api.get("/livre/fines/export", { params, responseType: "blob" });
      const cd = res.headers["content-disposition"] || "";
      const m = cd.match(/filename="([^"]+)"/);
      const ext = fmt === "excel" ? "xlsx" : fmt;
      const fallback = `logitrak_amendes.${ext}`;
      downloadBlob(res.data, m?.[1] || fallback);
      toast.success(`Export ${fmt.toUpperCase()} prêt`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Échec de l'export");
    }
  }

  const filtersDirty = useMemo(
    () => JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS),
    [filters],
  );

  return (
    <div className="space-y-6" data-testid="fines-page">
      {/* Page header */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.18em] text-slate-400 font-semibold">
            Administration
          </p>
          <h1 className="text-2xl font-semibold text-slate-900 flex items-center gap-2 mt-1">
            <Receipt className="w-5 h-5 text-[#2196F3]" />
            Gestion des amendes
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Suivi complet des amendes de la flotte — création, statut, paiement.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/livre/amendes/dashboard">
            <Button variant="outline" size="sm" data-testid="fines-open-dashboard"
                    className="h-9 text-[#2196F3] border-blue-200 hover:bg-blue-50">
              <BarChart3 className="w-4 h-4 mr-1.5" /> Statistiques
            </Button>
          </Link>
          <Button variant="outline" size="sm" onClick={() => exportAs("pdf")}
                  data-testid="fines-export-pdf"
                  className="h-9 text-rose-600 border-rose-200 hover:bg-rose-50">
            <FileText className="w-4 h-4 mr-1.5" /> PDF
          </Button>
          <Button variant="outline" size="sm" onClick={() => exportAs("excel")}
                  data-testid="fines-export-excel"
                  className="h-9 text-emerald-700 border-emerald-200 hover:bg-emerald-50">
            <FileSpreadsheet className="w-4 h-4 mr-1.5" /> Excel
          </Button>
          <Button variant="outline" size="sm" onClick={() => exportAs("csv")}
                  data-testid="fines-export-csv"
                  className="h-9 text-slate-600 border-slate-200 hover:bg-slate-50">
            <FileDown className="w-4 h-4 mr-1.5" /> CSV
          </Button>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}
                  data-testid="fines-refresh" className="h-9">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          </Button>
          {canEdit && (
            <Button onClick={openCreate} data-testid="fines-create"
                    className="bg-[#2196F3] hover:bg-[#1976D2] text-white h-9">
              <Plus className="w-4 h-4 mr-1.5" /> Nouvelle amende
            </Button>
          )}
        </div>
      </div>

      {/* Quick status sub-tabs (mirrors the status filter dropdown) */}
      <SubTabs
        current={filters.status}
        onChange={(v) => applyFilter("status", v)}
        tabs={[
          { value: "all",         label: "Toutes",       testId: "fines-tab-all" },
          { value: "received",    label: "Reçues",       testId: "fines-tab-received" },
          { value: "to_pay",      label: "À payer",      testId: "fines-tab-to_pay" },
          { value: "disputed",    label: "Contestées",   testId: "fines-tab-disputed" },
          { value: "paid",        label: "Payées",       testId: "fines-tab-paid" },
          { value: "closed",      label: "Clôturées",    testId: "fines-tab-closed" },
          { value: "cancelled",   label: "Annulées",     testId: "fines-tab-cancelled" },
        ]}
      />

      {/* KPI band */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard label="Total amendes" value={total} testId="fines-kpi-total" />
        <KpiCard label="Montant total" value={fmtAmount(totals.total_amount)} testId="fines-kpi-amount" />
        <KpiCard label="Montant payé" value={fmtAmount(totals.paid_amount)} tone="success" testId="fines-kpi-paid" />
        <KpiCard label="Montant en attente" value={fmtAmount(totals.open_amount)} tone="warning" testId="fines-kpi-open" />
      </div>

      {/* Filters */}
      <Card className="p-4 bg-white border-slate-200">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="w-4 h-4 text-slate-400" />
          <p className="text-[10px] uppercase tracking-[0.14em] font-semibold text-slate-500">Filtres</p>
          {filtersDirty && (
            <button onClick={() => { setFilters(DEFAULT_FILTERS); setPage(1); }}
                    className="ml-auto text-[11px] text-[#2196F3] hover:underline"
                    data-testid="fines-filters-reset">
              Réinitialiser
            </button>
          )}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
            <Input data-testid="fines-search" placeholder="N° dossier, plaque, lieu…"
                   className="pl-8 h-9 text-sm"
                   value={filters.q}
                   onChange={e => applyFilter("q", e.target.value)} />
          </div>
          <Select value={filters.status} onValueChange={v => applyFilter("status", v)}>
            <SelectTrigger data-testid="fines-filter-status" className="h-9 text-sm"><SelectValue placeholder="Statut" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous les statuts</SelectItem>
              {FINE_STATUSES.map(s => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={filters.vehicle_id} onValueChange={v => applyFilter("vehicle_id", v)}>
            <SelectTrigger data-testid="fines-filter-vehicle" className="h-9 text-sm"><SelectValue placeholder="Véhicule" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous les véhicules</SelectItem>
              {meta.vehicles?.map(v => <SelectItem key={v.id} value={v.id}>{v.plate}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={filters.driver_id} onValueChange={v => applyFilter("driver_id", v)}>
            <SelectTrigger data-testid="fines-filter-driver" className="h-9 text-sm"><SelectValue placeholder="Chauffeur" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous les chauffeurs</SelectItem>
              {meta.drivers?.map(d => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={filters.infraction_type} onValueChange={v => applyFilter("infraction_type", v)}>
            <SelectTrigger data-testid="fines-filter-type" className="h-9 text-sm"><SelectValue placeholder="Type" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous les types</SelectItem>
              {INFRACTION_TYPES.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input type="date" data-testid="fines-filter-start" className="h-9 text-sm"
                 value={filters.start} onChange={e => applyFilter("start", e.target.value)} />
          <Input type="date" data-testid="fines-filter-end" className="h-9 text-sm"
                 value={filters.end} onChange={e => applyFilter("end", e.target.value)} />
        </div>
      </Card>

      {/* Table */}
      <Card className="bg-white border-slate-200 overflow-hidden">
        {loading ? (
          <div className="py-16 flex justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" />
          </div>
        ) : rows.length === 0 ? (
          <div className="py-16 text-center text-slate-500 text-sm" data-testid="fines-empty">
            Aucune amende ne correspond aux filtres.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 text-[10px] uppercase tracking-[0.12em] text-slate-500">
                    <Th onClick={() => toggleSort("dossier_number")} active={sort.endsWith("dossier_number")} sort={sort}>Dossier</Th>
                    <Th onClick={() => toggleSort("infraction_at")} active={sort.endsWith("infraction_at")} sort={sort}>Date infraction</Th>
                    <th className="px-3 py-2 text-left">Véhicule</th>
                    <th className="px-3 py-2 text-left">Chauffeur</th>
                    <th className="px-3 py-2 text-left">Type</th>
                    <Th onClick={() => toggleSort("total_amount")} active={sort.endsWith("total_amount")} sort={sort} align="right">Montant</Th>
                    <Th onClick={() => toggleSort("due_date")} active={sort.endsWith("due_date")} sort={sort}>Échéance</Th>
                    <th className="px-3 py-2 text-left">Statut</th>
                    <th className="px-3 py-2 text-right w-[100px]">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => {
                    const s = FINE_STATUS_MAP[r.status] || { label: r.status, tone: "neutral" };
                    const overdue = isOverdue(r);
                    return (
                      <tr key={r.id} data-testid={`fines-row-${r.id}`}
                          className="border-t border-slate-100 hover:bg-slate-50/60">
                        <td className="px-3 py-2 font-mono text-[12px] text-slate-700">{r.dossier_number}</td>
                        <td className="px-3 py-2 whitespace-nowrap">{fmtDateTime(r.infraction_at)}</td>
                        <td className="px-3 py-2">{r.vehicle_plate || "—"}</td>
                        <td className="px-3 py-2">
                          {r.driver_name ? (
                            <div className="flex items-center gap-1.5">
                              <span>{r.driver_name}</span>
                              {r.driver_validated_manually ? (
                                <span className="text-[9px] font-mono px-1 py-0 rounded bg-slate-100 text-slate-600 border border-slate-200">
                                  M
                                </span>
                              ) : r.driver_confidence ? (
                                <span title={`Sources : ${(r.driver_sources || []).join(", ") || "—"}`}
                                      className={`text-[9px] font-mono px-1 py-0 rounded border ${
                                        r.driver_confidence >= 90 ? "bg-emerald-50 text-emerald-700 border-emerald-200" :
                                        r.driver_confidence >= 70 ? "bg-blue-50 text-blue-700 border-blue-200" :
                                                                    "bg-amber-50 text-amber-700 border-amber-200"
                                      }`}>
                                  {r.driver_confidence}%
                                </span>
                              ) : null}
                            </div>
                          ) : <span className="text-slate-400 italic">Non identifié</span>}
                        </td>
                        <td className="px-3 py-2 text-[12px] text-slate-600">{INFRACTION_LABEL[r.infraction_type] || r.infraction_type}</td>
                        <td className="px-3 py-2 text-right font-mono text-[13px]">{fmtAmount(r.total_amount, r.currency || "CHF")}</td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {fmtDate(r.due_date)}
                          {overdue && (
                            <span className="ml-1.5 inline-flex items-center gap-0.5 text-[10px] text-rose-600 font-semibold"
                                  title="En retard">
                              <AlertTriangle className="w-3 h-3" /> retard
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[11px] font-medium ${STATUS_TONE_CLASS[overdue ? "danger" : s.tone]}`}
                                data-testid={`fines-row-status-${r.id}`}>
                            {overdue ? "En retard" : s.label}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right whitespace-nowrap">
                          {canEdit && (
                            <Button variant="ghost" size="sm" onClick={() => openEdit(r.id)}
                                    data-testid={`fines-edit-${r.id}`}
                                    className="h-7 w-7 p-0 text-slate-500 hover:text-[#2196F3]">
                              <Pencil className="w-3.5 h-3.5" />
                            </Button>
                          )}
                          {isAdmin && (
                            <Button variant="ghost" size="sm" onClick={() => onDelete(r)}
                                    data-testid={`fines-delete-${r.id}`}
                                    className="h-7 w-7 p-0 text-slate-500 hover:text-rose-600">
                              <Trash2 className="w-3.5 h-3.5" />
                            </Button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {/* Pagination */}
            <div className="flex items-center justify-between px-3 py-2 border-t border-slate-100 text-[12px] text-slate-500">
              <span>Page {page} / {totalPages} · {total} amende{total > 1 ? "s" : ""}</span>
              <div className="flex gap-1">
                <Button size="sm" variant="outline" onClick={() => setPage(p => Math.max(1, p - 1))}
                        disabled={page <= 1} data-testid="fines-prev">Précédent</Button>
                <Button size="sm" variant="outline" onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                        disabled={page >= totalPages} data-testid="fines-next">Suivant</Button>
              </div>
            </div>
          </>
        )}
      </Card>

      <FineFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        fineId={editId}
        meta={meta}
        onSaved={() => load()}
      />
    </div>
  );
}

function KpiCard({ label, value, tone = "neutral", testId }) {
  const toneCls = {
    success: "text-emerald-600",
    warning: "text-amber-600",
    neutral: "text-slate-900",
  }[tone];
  return (
    <Card className="p-4 bg-white border-slate-200" data-testid={testId}>
      <p className="text-[10px] uppercase tracking-[0.14em] text-slate-400 font-semibold">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${toneCls}`}>{value}</p>
    </Card>
  );
}

function Th({ children, onClick, active, sort, align = "left" }) {
  const arrow = active ? (sort.startsWith("-") ? "↓" : "↑") : "";
  return (
    <th onClick={onClick}
        className={`px-3 py-2 cursor-pointer hover:text-slate-700 select-none text-${align}`}>
      <span className="inline-flex items-center gap-1">{children} <span className="text-[10px]">{arrow}</span></span>
    </th>
  );
}
