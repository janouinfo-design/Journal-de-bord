/* Gestion des amendes — analytics dashboard (Phase 3).
 *
 * Shows KPIs, breakdowns, monthly evolution and Top 10 rankings.
 * Lives at /livre/amendes/dashboard. Linked from FinesPage header.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtAmount, formatApiErrorDetail } from "@/lib/api";
import { FINE_STATUS_MAP, INFRACTION_LABEL } from "@/constants/fines";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, BarChart3, ArrowLeft, Receipt, AlertTriangle } from "lucide-react";
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { toast } from "sonner";

const PIE_COLORS = ["#2196F3", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#84cc16", "#ec4899"];

export default function FinesDashboardPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/livre/fines/stats/extended")
      .then(r => setData(r.data))
      .catch(e => toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Erreur"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center py-32">
        <Loader2 className="w-7 h-7 animate-spin text-[#2196F3]" />
      </div>
    );
  }
  if (!data) return null;

  const k = data.kpis || {};
  const statusBars = Object.entries(data.by_status || {})
    .filter(([, n]) => n > 0)
    .map(([code, n]) => ({ code, name: FINE_STATUS_MAP[code]?.label || code, count: n }));
  const typePie = Object.entries(data.by_type || {})
    .filter(([, n]) => n > 0)
    .map(([code, n]) => ({ code, name: INFRACTION_LABEL[code] || code, value: n }));

  return (
    <div className="space-y-6" data-testid="fines-dashboard">
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.18em] text-slate-400 font-semibold">
            Administration · Statistiques
          </p>
          <h1 className="text-2xl font-semibold text-slate-900 flex items-center gap-2 mt-1">
            <BarChart3 className="w-5 h-5 text-[#2196F3]" />
            Tableau de bord — Amendes
          </h1>
        </div>
        <Link to="/livre/amendes">
          <Button variant="outline" size="sm" className="h-9" data-testid="fines-dashboard-back">
            <ArrowLeft className="w-4 h-4 mr-1.5" /> Retour à la liste
          </Button>
        </Link>
      </div>

      {/* KPI band */}
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
        <Kpi label="Total amendes" value={k.total} testId="fdb-kpi-total" icon={<Receipt className="w-4 h-4" />} />
        <Kpi label="Montant total" value={fmtAmount(k.total_amount)} testId="fdb-kpi-amount" />
        <Kpi label="Payé" value={fmtAmount(k.paid_amount)} tone="success" testId="fdb-kpi-paid" />
        <Kpi label="En attente" value={fmtAmount(k.pending_amount)} tone="warning" testId="fdb-kpi-pending" />
        <Kpi label="Contestées" value={k.disputed} tone="warning" testId="fdb-kpi-disputed" />
        <Kpi label="En retard" value={k.overdue} tone="danger" testId="fdb-kpi-overdue"
             icon={<AlertTriangle className="w-4 h-4" />} />
      </div>

      {/* Monthly evolution */}
      <Card className="p-4 bg-white border-slate-200">
        <h3 className="text-sm font-semibold text-slate-700 mb-3">Évolution mensuelle (12 derniers mois)</h3>
        <div style={{ width: "100%", height: 260 }}>
          <ResponsiveContainer>
            <LineChart data={data.monthly || []} margin={{ top: 5, right: 30, left: 10, bottom: 5 }}>
              <CartesianGrid stroke="#f1f5f9" />
              <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#64748b" }} />
              <YAxis yAxisId="left" tick={{ fontSize: 11, fill: "#64748b" }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: "#64748b" }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line yAxisId="left" type="monotone" dataKey="count" name="Nombre d'amendes"
                    stroke="#2196F3" strokeWidth={2} dot={{ r: 3 }} />
              <Line yAxisId="right" type="monotone" dataKey="amount" name="Montant (CHF)"
                    stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* Distribution charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-4 bg-white border-slate-200">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Répartition par statut</h3>
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer>
              <BarChart data={statusBars} layout="vertical" margin={{ top: 5, right: 24, left: 24, bottom: 5 }}>
                <CartesianGrid stroke="#f1f5f9" />
                <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: "#475569" }} width={140} />
                <Tooltip />
                <Bar dataKey="count" fill="#2196F3" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="p-4 bg-white border-slate-200">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Répartition par type d&apos;infraction</h3>
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie data={typePie} dataKey="value" nameKey="name" outerRadius={88} label={(d) => d.name}>
                  {typePie.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* Top 10 rankings */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <RankingTable title="Top 10 véhicules verbalisés" rows={data.top_vehicles}
                      cols={["Plaque", "Nb", "Total"]} testId="fdb-top-vehicles" />
        <RankingTable title="Top 10 chauffeurs verbalisés" rows={data.top_drivers}
                      cols={["Chauffeur", "Nb", "Total"]} testId="fdb-top-drivers" />
        <RankingTable title="Top 10 montants" rows={data.top_amounts}
                      cols={["Dossier", "Montant", "Statut"]} testId="fdb-top-amounts" amountsTable />
      </div>
    </div>
  );
}

function Kpi({ label, value, tone = "neutral", testId, icon }) {
  const colorCls = {
    success: "text-emerald-600",
    warning: "text-amber-600",
    danger: "text-rose-600",
    neutral: "text-slate-900",
  }[tone];
  return (
    <Card className="p-3 bg-white border-slate-200" data-testid={testId}>
      <div className="flex items-center justify-between gap-1">
        <p className="text-[10px] uppercase tracking-[0.14em] text-slate-400 font-semibold">{label}</p>
        {icon && <span className="text-slate-300">{icon}</span>}
      </div>
      <p className={`mt-1 text-xl font-semibold ${colorCls}`}>{value ?? 0}</p>
    </Card>
  );
}

function RankingTable({ title, rows, cols, testId, amountsTable }) {
  return (
    <Card className="p-4 bg-white border-slate-200" data-testid={testId}>
      <h3 className="text-sm font-semibold text-slate-700 mb-3">{title}</h3>
      {(!rows || rows.length === 0) ? (
        <p className="text-xs text-slate-400 py-2">Aucune donnée</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-slate-400">
              {cols.map(c => <th key={c} className="text-left py-1 font-semibold">{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={(r.key || "") + i} className="border-t border-slate-100">
                {amountsTable ? (
                  <>
                    <td className="py-1.5 font-mono text-[11px]">{r.label}</td>
                    <td className="py-1.5 text-right font-mono">{fmtAmount(r.total)}</td>
                    <td className="py-1.5 text-slate-500">{FINE_STATUS_MAP[r.status]?.label || r.status}</td>
                  </>
                ) : (
                  <>
                    <td className="py-1.5 truncate max-w-[150px]">{r.label}</td>
                    <td className="py-1.5 text-right font-mono w-12">{r.count}</td>
                    <td className="py-1.5 text-right font-mono text-slate-600">{fmtAmount(r.total)}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
