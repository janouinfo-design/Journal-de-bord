import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import SubTabs from "@/components/layout/SubTabs";
import { MATCH_STATUS, fmtAmount } from "@/lib/fuelLabels";
import TxDetailDialog from "@/components/fuel/TxDetailDialog";
import { PlayCircle } from "lucide-react";

const QUEUES = [
  { value: "unmatched", label: "À vérifier", testId: "fuel-match-tab-unmatched" },
  { value: "matched_review", label: "Contrôle recommandé", testId: "fuel-match-tab-review" },
  { value: "auto_matched", label: "Rapprochés auto", testId: "fuel-match-tab-auto" },
  { value: "manual", label: "Attribués manuellement", testId: "fuel-match-tab-manual" },
];

export default function FuelMatchingPage() {
  const [queue, setQueue] = useState("unmatched");
  const [data, setData] = useState({ items: [], total: 0 });
  const [detailId, setDetailId] = useState(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(() => {
    api.get("/livre/fuel/transactions", { params: { match_status: queue, page_size: 100 } })
      .then(({ data }) => setData(data))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
  }, [queue]);
  useEffect(() => { load(); }, [load]);

  async function runMatching() {
    setRunning(true);
    try {
      const { data: r } = await api.post("/livre/fuel/match/run", { only_unmatched: true });
      toast.success(
        `Rapprochement terminé : ${r.processed} traitée(s) — ${r.auto_matched || 0} auto, ` +
        `${r.matched_review || 0} à contrôler, ${r.unmatched || 0} restent à vérifier`);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setRunning(false); }
  }

  return (
    <div data-testid="fuel-matching-page" className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-slate-500 max-w-2xl">
          Le score de rapprochement est <strong>explicable</strong> : chaque transaction affiche les règles
          appliquées (carte affectée, véhicule fourni, proximité GPS…). Une attribution manuelle exige toujours un motif.
        </p>
        <Button data-testid="fuel-match-run-btn" onClick={runMatching} disabled={running}
                className="bg-[#2196F3] hover:bg-[#1976D2] text-white h-9 shrink-0">
          <PlayCircle className="w-4 h-4 mr-1.5" />
          {running ? "Rapprochement…" : "Lancer le rapprochement automatique"}
        </Button>
      </div>

      <SubTabs tabs={QUEUES} current={queue} onChange={setQueue} />

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Date</th><th className="px-4 py-3">Carte</th>
              <th className="px-4 py-3">Station</th><th className="px-4 py-3">Montant</th>
              <th className="px-4 py-3">Véhicule</th><th className="px-4 py-3">Indice relevé</th>
              <th className="px-4 py-3">Score</th><th className="px-4 py-3">Statut</th>
            </tr>
          </thead>
          <tbody>
            {data.items.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-400">
                Aucune transaction dans cette file
              </td></tr>
            ) : data.items.map((t) => {
              const s = MATCH_STATUS[t.match_status] || MATCH_STATUS.unmatched;
              return (
                <tr key={t.id} data-testid={`fuel-match-row-${t.id}`}
                    className="border-b border-slate-100 hover:bg-slate-50/60 cursor-pointer"
                    onClick={() => setDetailId(t.id)}>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap">{fmtDateTime(t.tx_datetime)}</td>
                  <td className="px-4 py-2.5 text-xs font-mono">{t.card_last4 ? `•••• ${t.card_last4}` : "—"}</td>
                  <td className="px-4 py-2.5 text-xs">{t.station_name || "—"}</td>
                  <td className="px-4 py-2.5 text-xs font-medium">{fmtAmount(t.amount_total, t.currency)}</td>
                  <td className="px-4 py-2.5 text-xs">{t.vehicle_plate || "—"}</td>
                  <td className="px-4 py-2.5 text-xs text-slate-400">{t.vehicle_hint || "—"}</td>
                  <td className="px-4 py-2.5 text-xs font-semibold">
                    {t.match_score != null ? `${t.match_score}/100` : "—"}
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
      <p className="text-xs text-slate-400">Cliquez sur une ligne pour voir le détail du score et attribuer manuellement.</p>

      {detailId && <TxDetailDialog txId={detailId} onClose={() => setDetailId(null)} onChanged={load} />}
    </div>
  );
}
