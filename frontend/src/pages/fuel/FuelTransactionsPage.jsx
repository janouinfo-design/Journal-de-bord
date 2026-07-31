import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { MATCH_STATUS, SOURCE_LABEL, PRODUCT_LABEL, fmtAmount, fmtQty } from "@/lib/fuelLabels";
import TxDetailDialog from "@/components/fuel/TxDetailDialog";
import ManualTxDialog from "@/components/fuel/ManualTxDialog";
import { Plus, ChevronLeft, ChevronRight, Search } from "lucide-react";

const EMPTY_FILTERS = { date_from: "", date_to: "", match_status: "", card_id: "", vehicle_id: "", q: "" };

export default function FuelTransactionsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 50 });
  const [refs, setRefs] = useState({ vehicles: [], drivers: [], cards: [], product_types: [] });
  const [page, setPage] = useState(1);
  const [detailId, setDetailId] = useState(null);
  const [manualOpen, setManualOpen] = useState(false);

  const load = useCallback(() => {
    const params = { page, page_size: 50 };
    Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
    api.get("/livre/fuel/transactions", { params })
      .then(({ data }) => setData(data))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
  }, [filters, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get("/livre/fuel/refs").then(({ data }) => setRefs(data)).catch(() => {}); }, []);

  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  const setF = (k) => (v) => { setFilters((f) => ({ ...f, [k]: v })); setPage(1); };

  return (
    <div data-testid="fuel-transactions-page" className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <p className="text-[10px] uppercase text-slate-400 font-semibold">Du</p>
          <Input data-testid="fuel-tx-filter-from" type="date" className="h-9 w-36"
                 value={filters.date_from} onChange={(e) => setF("date_from")(e.target.value)} />
        </div>
        <div className="space-y-1">
          <p className="text-[10px] uppercase text-slate-400 font-semibold">Au</p>
          <Input data-testid="fuel-tx-filter-to" type="date" className="h-9 w-36"
                 value={filters.date_to} onChange={(e) => setF("date_to")(e.target.value)} />
        </div>
        <Select value={filters.match_status || "all"} onValueChange={(v) => setF("match_status")(v === "all" ? "" : v)}>
          <SelectTrigger data-testid="fuel-tx-filter-status" className="h-9 w-44"><SelectValue placeholder="Statut" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tous les statuts</SelectItem>
            {Object.entries(MATCH_STATUS).map(([v, s]) => <SelectItem key={v} value={v}>{s.label}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={filters.card_id || "all"} onValueChange={(v) => setF("card_id")(v === "all" ? "" : v)}>
          <SelectTrigger data-testid="fuel-tx-filter-card" className="h-9 w-44"><SelectValue placeholder="Carte" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Toutes les cartes</SelectItem>
            {refs.cards.map((c) => <SelectItem key={c.id} value={c.id}>{c.provider} •••• {c.last4}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={filters.vehicle_id || "all"} onValueChange={(v) => setF("vehicle_id")(v === "all" ? "" : v)}>
          <SelectTrigger data-testid="fuel-tx-filter-vehicle" className="h-9 w-40"><SelectValue placeholder="Véhicule" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tous les véhicules</SelectItem>
            {refs.vehicles.map((v) => <SelectItem key={v.id} value={v.id}>{v.plate}</SelectItem>)}
          </SelectContent>
        </Select>
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input data-testid="fuel-tx-filter-search" placeholder="Station…" className="h-9 w-40 pl-8"
                 value={filters.q} onChange={(e) => setF("q")(e.target.value)} />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-slate-400" data-testid="fuel-tx-total">{data.total} transaction(s)</span>
          {isAdmin && (
            <Button data-testid="fuel-tx-create-btn" className="bg-[#2196F3] hover:bg-[#1976D2] text-white h-9"
                    onClick={() => setManualOpen(true)}>
              <Plus className="w-4 h-4 mr-1.5" /> Nouvelle transaction
            </Button>
          )}
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Date</th><th className="px-4 py-3">Carte</th>
              <th className="px-4 py-3">Station</th><th className="px-4 py-3">Produit</th>
              <th className="px-4 py-3">Quantité</th><th className="px-4 py-3">Montant</th>
              <th className="px-4 py-3">Véhicule</th><th className="px-4 py-3">Chauffeur</th>
              <th className="px-4 py-3">Source</th><th className="px-4 py-3">Statut</th>
            </tr>
          </thead>
          <tbody>
            {data.items.length === 0 ? (
              <tr><td colSpan={10} className="px-4 py-8 text-center text-slate-400">Aucune transaction</td></tr>
            ) : data.items.map((t) => {
              const s = MATCH_STATUS[t.match_status] || MATCH_STATUS.unmatched;
              return (
                <tr key={t.id} data-testid={`fuel-tx-row-${t.id}`}
                    className="border-b border-slate-100 hover:bg-slate-50/60 cursor-pointer"
                    onClick={() => setDetailId(t.id)}>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap">{fmtDateTime(t.tx_datetime)}</td>
                  <td className="px-4 py-2.5 text-xs font-mono">{t.card_last4 ? `•••• ${t.card_last4}` : "—"}</td>
                  <td className="px-4 py-2.5 text-xs">{t.station_name || "—"}</td>
                  <td className="px-4 py-2.5 text-xs">{PRODUCT_LABEL[t.product_type] || t.product_type || "—"}</td>
                  <td className="px-4 py-2.5 text-xs">{t.quantity != null ? fmtQty(t.quantity, t.unit) : "—"}</td>
                  <td className="px-4 py-2.5 text-xs font-medium">
                    {fmtAmount(t.amount_total, t.currency)}
                    {t.currency !== "CHF" && (t.fx_status === "pending"
                      ? <span className="block text-[10px] text-amber-600 font-semibold">Conversion en attente</span>
                      : t.amount_chf != null && <span className="block text-[10px] text-slate-400">≈ {fmtAmount(t.amount_chf)}</span>)}
                  </td>
                  <td className="px-4 py-2.5 text-xs">{t.vehicle_plate || "—"}</td>
                  <td className="px-4 py-2.5 text-xs">{t.driver_name || "—"}</td>
                  <td className="px-4 py-2.5 text-xs">{SOURCE_LABEL[t.source] || t.source}</td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex px-2 py-0.5 rounded-full border text-[11px] font-medium ${s.cls}`}>{s.label}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-xs text-slate-500">
          <Button data-testid="fuel-tx-prev" variant="outline" size="sm" disabled={page <= 1}
                  onClick={() => setPage(page - 1)}><ChevronLeft className="w-4 h-4" /></Button>
          Page {page} / {pages}
          <Button data-testid="fuel-tx-next" variant="outline" size="sm" disabled={page >= pages}
                  onClick={() => setPage(page + 1)}><ChevronRight className="w-4 h-4" /></Button>
        </div>
      )}

      {detailId && <TxDetailDialog txId={detailId} onClose={() => setDetailId(null)} onChanged={load} />}
      <ManualTxDialog open={manualOpen} onClose={() => setManualOpen(false)} refs={refs} onCreated={load} />
    </div>
  );
}
