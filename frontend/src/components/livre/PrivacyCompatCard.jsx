import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { ShieldCheck, ShieldAlert, ShieldOff, ShieldQuestion, RefreshCw, Loader2, List } from "lucide-react";

const STATUS_META = {
  full:    { label: "Compatible",    color: "bg-emerald-50 text-emerald-700 border-emerald-200", icon: ShieldCheck },
  partial: { label: "Partiel",       color: "bg-amber-50 text-amber-700 border-amber-200",       icon: ShieldAlert },
  none:    { label: "Non supporté",  color: "bg-rose-50 text-rose-700 border-rose-200",          icon: ShieldOff },
  unknown: { label: "À vérifier",    color: "bg-slate-100 text-slate-600 border-slate-200",      icon: ShieldQuestion },
};

const COUNTERS = [
  { key: "full",    label: "Compatibles",   icon: ShieldCheck,    color: "text-emerald-600" },
  { key: "partial", label: "Partiels",      icon: ShieldAlert,    color: "text-amber-600" },
  { key: "none",    label: "Non supportés", icon: ShieldOff,      color: "text-rose-600" },
  { key: "unknown", label: "À vérifier",    icon: ShieldQuestion, color: "text-slate-500" },
];

function Row({ r }) {
  const meta = STATUS_META[r.status] || STATUS_META.unknown;
  const Icon = meta.icon;
  return (
    <tr className="border-t border-slate-100 hover:bg-slate-50/60"
        data-testid={`privacy-compat-row-${r.status}`}>
      <td className="py-2.5 px-3 font-mono text-xs">{r.plate}</td>
      <td className="py-2.5 px-3 text-slate-700 text-xs">{r.model || "—"}</td>
      <td className="py-2.5 px-3 text-slate-600 text-xs">{r.family}</td>
      <td className="py-2.5 px-3">
        <Badge variant="outline" className={`${meta.color} font-medium`}>
          <Icon className="w-3 h-3 mr-1.5" />{meta.label}
        </Badge>
      </td>
      <td className="py-2.5 px-3 text-xs text-slate-500 font-mono">
        {r.recommended_command || <span className="text-slate-400 italic">—</span>}
      </td>
    </tr>
  );
}

export default function PrivacyCompatCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showAll, setShowAll] = useState(false);

  async function scan() {
    setLoading(true);
    try {
      const { data } = await api.get("/livre/privacy/tracker-compatibility");
      setData(data);
    } catch {
      toast.error("Échec du scan de compatibilité");
    } finally { setLoading(false); }
  }
  useEffect(() => { scan(); /* eslint-disable-next-line */ }, []);

  const rows = data?.rows || [];
  // Sort by status priority for the preview: compatibles first, then partial, unknown, none
  const ORDER = { full: 0, partial: 1, unknown: 2, none: 3 };
  const sortedRows = [...rows].sort((a, b) => (ORDER[a.status] ?? 99) - (ORDER[b.status] ?? 99));
  const preview = sortedRows.slice(0, 5);

  return (
    <div data-testid="privacy-compat-card">
      {/* Counters */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4" data-testid="privacy-compat-counters">
        {COUNTERS.map(c => {
          const Icon = c.icon;
          return (
            <div key={c.key}
              className="border border-slate-200 rounded-md p-3 flex items-center justify-between bg-white"
              data-testid={`privacy-compat-counter-${c.key}`}>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                  <Icon className={`w-3 h-3 ${c.color}`} /> {c.label}
                </p>
                <p className={`text-2xl font-semibold mt-0.5 ${c.color}`}>
                  {data ? data.counters[c.key] : "—"}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Compact table */}
      <div className="border border-slate-200 rounded-md overflow-hidden bg-white">
        <table className="w-full text-sm" data-testid="privacy-compat-table">
          <thead>
            <tr className="bg-slate-50 text-slate-500 text-[10px] font-semibold uppercase tracking-wider">
              <th className="text-left py-2.5 px-3">Plaque</th>
              <th className="text-left py-2.5 px-3">Modèle</th>
              <th className="text-left py-2.5 px-3">Famille</th>
              <th className="text-left py-2.5 px-3">Statut</th>
              <th className="text-left py-2.5 px-3">Commande prévue (Phase 2)</th>
            </tr>
          </thead>
          <tbody>
            {!data ? (
              <tr><td colSpan={5} className="py-8 text-center text-slate-400">
                <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> Scan en cours…
              </td></tr>
            ) : preview.length === 0 ? (
              <tr><td colSpan={5} className="py-6 text-center text-slate-400">Aucun véhicule.</td></tr>
            ) : preview.map(r => <Row key={r.vehicle_id} r={r} />)}
          </tbody>
        </table>
      </div>

      <div className="flex justify-between items-center mt-3">
        <p className="text-[11px] text-slate-400 italic">
          Phase 1 — scan en lecture seule. Aucune commande n&apos;est envoyée aux traceurs.
        </p>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={scan} disabled={loading}
            data-testid="privacy-compat-rescan">
            {loading ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5 mr-1.5" />}
            Re-scanner
          </Button>
          {rows.length > 5 && (
            <Button size="sm" variant="outline" onClick={() => setShowAll(true)}
              data-testid="privacy-compat-show-all">
              <List className="w-3.5 h-3.5 mr-1.5" />
              Voir tous les véhicules ({rows.length})
            </Button>
          )}
        </div>
      </div>

      {/* Modal — full list */}
      <Dialog open={showAll} onOpenChange={setShowAll}>
        <DialogContent className="max-w-5xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">
              Compatibilité Mode privé — tous les véhicules ({rows.length})
            </DialogTitle>
          </DialogHeader>
          <div className="border border-slate-200 rounded-md overflow-hidden">
            <table className="w-full text-sm" data-testid="privacy-compat-table-full">
              <thead className="sticky top-0">
                <tr className="bg-slate-50 text-slate-500 text-[10px] font-semibold uppercase tracking-wider">
                  <th className="text-left py-2.5 px-3">Plaque</th>
                  <th className="text-left py-2.5 px-3">Modèle</th>
                  <th className="text-left py-2.5 px-3">Famille</th>
                  <th className="text-left py-2.5 px-3">Statut</th>
                  <th className="text-left py-2.5 px-3">Commande prévue</th>
                </tr>
              </thead>
              <tbody>
                {sortedRows.map(r => <Row key={r.vehicle_id} r={r} />)}
              </tbody>
            </table>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
