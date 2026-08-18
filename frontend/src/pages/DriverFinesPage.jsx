/* Read-only fines view for chauffeurs. Lists their OWN fines only.
 *
 * Backend endpoint /api/livre/fines/mine resolves the current user's driver
 * record and filters by driver_id. internal_notes are stripped server-side.
 */
import { useEffect, useState } from "react";
import { api, fmtAmount, fmtDate, fmtDateTime } from "@/lib/api";
import {
  FINE_STATUS_MAP, STATUS_TONE_CLASS, INFRACTION_LABEL, isOverdue,
} from "@/constants/fines";
import { Card } from "@/components/ui/card";
import { Loader2, Receipt, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

export default function DriverFinesPage() {
  const [data, setData] = useState({ rows: [], total: 0, totals: {} });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/livre/fines/mine")
      .then(r => setData(r.data))
      .catch(e => toast.error(e?.response?.data?.detail || "Erreur"))
      .finally(() => setLoading(false));
  }, []);

  const { rows, total, totals } = data;

  return (
    <div className="space-y-6" data-testid="driver-fines-page">
      <div>
        <p className="text-[10px] uppercase tracking-[0.18em] text-slate-400 font-semibold">
          Mon livre
        </p>
        <h1 className="text-2xl font-semibold text-slate-900 flex items-center gap-2 mt-1">
          <Receipt className="w-5 h-5 text-[#2196F3]" />
          Mes amendes
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Liste de vos amendes — lecture seule. Contactez votre gestionnaire pour toute modification.
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard label="Total" value={total} testId="dfines-kpi-total" />
        <KpiCard label="Montant total" value={fmtAmount(totals?.total_amount)} testId="dfines-kpi-amount" />
        <KpiCard label="Montant payé" value={fmtAmount(totals?.paid_amount)} tone="success" testId="dfines-kpi-paid" />
        <KpiCard label="Montant en attente" value={fmtAmount(totals?.open_amount)} tone="warning" testId="dfines-kpi-open" />
      </div>

      <Card className="bg-white border-slate-200 overflow-hidden">
        {loading ? (
          <div className="py-16 flex justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" />
          </div>
        ) : rows.length === 0 ? (
          <div className="py-16 text-center text-slate-500 text-sm" data-testid="dfines-empty">
            🎉 Aucune amende enregistrée à votre nom.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-[10px] uppercase tracking-[0.12em] text-slate-500">
                  <th className="px-3 py-2 text-left">Dossier</th>
                  <th className="px-3 py-2 text-left">Date infraction</th>
                  <th className="px-3 py-2 text-left">Véhicule</th>
                  <th className="px-3 py-2 text-left">Type</th>
                  <th className="px-3 py-2 text-left">Lieu</th>
                  <th className="px-3 py-2 text-right">Montant</th>
                  <th className="px-3 py-2 text-left">Échéance</th>
                  <th className="px-3 py-2 text-left">Statut</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const s = FINE_STATUS_MAP[r.status] || { label: r.status, tone: "neutral" };
                  const overdue = isOverdue(r);
                  return (
                    <tr key={r.id} data-testid={`dfines-row-${r.id}`}
                        className="border-t border-slate-100 hover:bg-slate-50/60">
                      <td className="px-3 py-2 font-mono text-[12px] text-slate-700">{r.dossier_number}</td>
                      <td className="px-3 py-2 whitespace-nowrap">{fmtDateTime(r.infraction_at)}</td>
                      <td className="px-3 py-2">{r.vehicle_plate || "—"}</td>
                      <td className="px-3 py-2 text-[12px] text-slate-600">{INFRACTION_LABEL[r.infraction_type] || r.infraction_type}</td>
                      <td className="px-3 py-2 text-[12px] text-slate-600 max-w-[200px] truncate" title={r.location}>{r.location || "—"}</td>
                      <td className="px-3 py-2 text-right font-mono text-[13px]">{fmtAmount(r.total_amount, r.currency || "CHF")}</td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        {fmtDate(r.due_date)}
                        {overdue && (
                          <span className="ml-1.5 inline-flex items-center gap-0.5 text-[10px] text-rose-600 font-semibold">
                            <AlertTriangle className="w-3 h-3" /> retard
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[11px] font-medium ${STATUS_TONE_CLASS[overdue ? "danger" : s.tone]}`}>
                          {overdue ? "En retard" : s.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
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
      <p className={`mt-1 text-2xl font-semibold ${toneCls}`}>{value ?? 0}</p>
    </Card>
  );
}
