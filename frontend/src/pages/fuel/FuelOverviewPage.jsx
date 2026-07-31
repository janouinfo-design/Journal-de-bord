import { useEffect, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { toast } from "sonner";
import { MATCH_STATUS, CARD_STATUS, fmtAmount, fmtQty, CLASSIFICATION_LABEL } from "@/lib/fuelLabels";
import { ReceiptText, Droplets, Zap, CreditCard } from "lucide-react";

function Stat({ icon: Icon, label, value, sub, testId }) {
  return (
    <div data-testid={testId} className="bg-white rounded-lg border border-slate-200 p-4">
      <div className="flex items-center gap-2 text-slate-400 text-[11px] uppercase tracking-wider font-semibold">
        <Icon className="w-3.5 h-3.5" /> {label}
      </div>
      <div className="text-2xl font-semibold text-slate-900 mt-1">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

export default function FuelOverviewPage() {
  const [data, setData] = useState(null);

  useEffect(() => {
    api.get("/livre/fuel/overview")
      .then(({ data }) => setData(data))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
  }, []);

  if (!data) return <p className="text-sm text-slate-400">Chargement…</p>;

  const chf = data.amount_chf_total ?? (data.amount_by_currency?.CHF || 0);
  const otherCur = Object.entries(data.amount_by_currency || {}).filter(([c]) => c !== "CHF");
  const ms = data.match_statuses || {};
  const amountSub = [
    ...(otherCur.length ? [otherCur.map(([c, v]) => `dont ${fmtAmount(v, c)} (origine)`).join(" · ")] : []),
    ...(data.fx_pending ? [`${data.fx_pending} conversion(s) en attente`] : []),
  ].join(" — ") || null;

  return (
    <div data-testid="fuel-overview-page" className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat icon={ReceiptText} label="Transactions" value={data.transactions_count}
              testId="fuel-stat-count" />
        <Stat icon={ReceiptText} label="Montant total (CHF)" value={fmtAmount(chf)}
              sub={amountSub}
              testId="fuel-stat-amount" />
        <Stat icon={Droplets} label="Litres" value={fmtQty(data.quantities?.L, "L")} testId="fuel-stat-liters" />
        <Stat icon={Zap} label="Recharge" value={fmtQty(data.quantities?.kWh, "kWh")} testId="fuel-stat-kwh" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-3">Rapprochement</p>
          <div className="space-y-2">
            {Object.entries(MATCH_STATUS).map(([k, s]) => (
              <div key={k} className="flex items-center justify-between text-sm">
                <span className={`inline-flex px-2 py-0.5 rounded-full border text-[11px] font-medium ${s.cls}`}>{s.label}</span>
                <span data-testid={`fuel-match-${k}`} className="font-semibold text-slate-800">{ms[k] || 0}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-3">Coûts par classification</p>
          <div className="space-y-2">
            {Object.entries(data.amount_by_classification || {}).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between text-sm">
                <span className="text-slate-600">{CLASSIFICATION_LABEL[k] || k}</span>
                <span className="font-semibold text-slate-800">{fmtAmount(v)}</span>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-slate-400 mt-3">Selon la classification des trajets rattachés (les non rattachés restent « non classé »).</p>
        </div>
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-3 flex items-center gap-1.5">
            <CreditCard className="w-3.5 h-3.5" /> Cartes
          </p>
          <div className="space-y-2">
            {Object.entries(data.cards_by_status || {}).length === 0 && (
              <p className="text-xs text-slate-400">Aucune carte enregistrée</p>
            )}
            {Object.entries(data.cards_by_status || {}).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between text-sm">
                <span className={`inline-flex px-2 py-0.5 rounded-full border text-[11px] font-medium ${(CARD_STATUS[k] || {}).cls || ""}`}>
                  {(CARD_STATUS[k] || {}).label || k}
                </span>
                <span className="font-semibold text-slate-800">{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <p className="px-4 pt-4 text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Dernières transactions</p>
        <table className="w-full text-sm mt-2">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-2">Date</th><th className="px-4 py-2">Carte</th>
              <th className="px-4 py-2">Station</th><th className="px-4 py-2">Montant</th>
              <th className="px-4 py-2">Véhicule</th><th className="px-4 py-2">Statut</th>
            </tr>
          </thead>
          <tbody>
            {(data.recent || []).map((t) => {
              const s = MATCH_STATUS[t.match_status] || MATCH_STATUS.unmatched;
              return (
                <tr key={t.id} className="border-b border-slate-100">
                  <td className="px-4 py-2 text-xs whitespace-nowrap">{fmtDateTime(t.tx_datetime)}</td>
                  <td className="px-4 py-2 text-xs font-mono">•••• {t.card_last4 || "—"}</td>
                  <td className="px-4 py-2 text-xs">{t.station_name || "—"}</td>
                  <td className="px-4 py-2 text-xs font-medium">{fmtAmount(t.amount_total, t.currency)}</td>
                  <td className="px-4 py-2 text-xs">{t.vehicle_plate || "—"}</td>
                  <td className="px-4 py-2">
                    <span className={`inline-flex px-2 py-0.5 rounded-full border text-[11px] font-medium ${s.cls}`}>{s.label}</span>
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
