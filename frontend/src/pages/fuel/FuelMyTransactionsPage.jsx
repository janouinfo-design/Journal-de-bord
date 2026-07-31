import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { MATCH_STATUS, PRODUCT_LABEL, fmtAmount, fmtQty } from "@/lib/fuelLabels";
import TxDetailDialog from "@/components/fuel/TxDetailDialog";
import { ChevronLeft, ChevronRight, Paperclip } from "lucide-react";

export default function FuelMyTransactionsPage() {
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 50 });
  const [page, setPage] = useState(1);
  const [detailId, setDetailId] = useState(null);

  const load = useCallback(() => {
    api.get("/livre/fuel/my-transactions", { params: { page, page_size: 50 } })
      .then(({ data }) => setData(data))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
  }, [page]);
  useEffect(() => { load(); }, [load]);

  const pages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div data-testid="fuel-my-transactions-page" className="space-y-4">
      <p className="text-xs text-slate-400" data-testid="fuel-my-tx-total">
        {data.total} transaction(s) vous concernant. Cliquez sur une ligne pour voir le détail,
        joindre un justificatif ou signaler une erreur.
      </p>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Date</th><th className="px-4 py-3">Carte</th>
              <th className="px-4 py-3">Station</th><th className="px-4 py-3">Produit</th>
              <th className="px-4 py-3">Quantité</th><th className="px-4 py-3">Montant</th>
              <th className="px-4 py-3">Véhicule</th><th className="px-4 py-3">Justif.</th>
              <th className="px-4 py-3">Statut</th>
            </tr>
          </thead>
          <tbody>
            {data.items.length === 0 ? (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-slate-400">
                Aucune transaction ne vous est rattachée pour le moment
              </td></tr>
            ) : data.items.map((t) => {
              const s = MATCH_STATUS[t.match_status] || MATCH_STATUS.unmatched;
              return (
                <tr key={t.id} data-testid={`fuel-my-tx-row-${t.id}`}
                    className="border-b border-slate-100 hover:bg-slate-50/60 cursor-pointer"
                    onClick={() => setDetailId(t.id)}>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap">{fmtDateTime(t.tx_datetime)}</td>
                  <td className="px-4 py-2.5 text-xs font-mono">{t.card_last4 ? `•••• ${t.card_last4}` : "—"}</td>
                  <td className="px-4 py-2.5 text-xs">{t.station_name || "—"}</td>
                  <td className="px-4 py-2.5 text-xs">{PRODUCT_LABEL[t.product_type] || t.product_type || "—"}</td>
                  <td className="px-4 py-2.5 text-xs">{t.quantity != null ? fmtQty(t.quantity, t.unit) : "—"}</td>
                  <td className="px-4 py-2.5 text-xs font-medium">{fmtAmount(t.amount_total, t.currency)}</td>
                  <td className="px-4 py-2.5 text-xs">{t.vehicle_plate || "—"}</td>
                  <td className="px-4 py-2.5 text-xs">
                    {(t.documents || []).length > 0
                      ? <span className="inline-flex items-center gap-1 text-emerald-600"><Paperclip className="w-3 h-3" />{t.documents.length}</span>
                      : "—"}
                  </td>
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
          <Button data-testid="fuel-my-tx-prev" variant="outline" size="sm" disabled={page <= 1}
                  onClick={() => setPage(page - 1)}><ChevronLeft className="w-4 h-4" /></Button>
          Page {page} / {pages}
          <Button data-testid="fuel-my-tx-next" variant="outline" size="sm" disabled={page >= pages}
                  onClick={() => setPage(page + 1)}><ChevronRight className="w-4 h-4" /></Button>
        </div>
      )}

      {detailId && <TxDetailDialog txId={detailId} onClose={() => setDetailId(null)} onChanged={load} />}
    </div>
  );
}
