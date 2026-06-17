import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { ShieldCheck, ShieldAlert, ShieldOff, ShieldQuestion, RefreshCw, Loader2, Info } from "lucide-react";

const STATUS_META = {
  full: {
    label: "Compatible",
    color: "bg-emerald-50 text-emerald-700 border-emerald-200",
    icon: ShieldCheck,
    description: "Le tracker accepte une commande native qui coupe l'émission GPS.",
  },
  partial: {
    label: "Partiellement compatible",
    color: "bg-amber-50 text-amber-700 border-amber-200",
    icon: ShieldAlert,
    description: "Confidentialité possible mais via SMS uniquement (pas d'IP).",
  },
  none: {
    label: "Non supporté",
    color: "bg-rose-50 text-rose-700 border-rose-200",
    icon: ShieldOff,
    description: "Le mode privé doit être activé manuellement (ex. app smartphone).",
  },
  unknown: {
    label: "À vérifier",
    color: "bg-slate-100 text-slate-600 border-slate-200",
    icon: ShieldQuestion,
    description: "Modèle non répertorié — vérification manuelle requise.",
  },
};

const COUNTER_META = [
  { key: "full",    label: "Compatibles",   icon: ShieldCheck,    cls: "text-emerald-600" },
  { key: "partial", label: "Partiels",      icon: ShieldAlert,    cls: "text-amber-600" },
  { key: "none",    label: "Non supportés", icon: ShieldOff,      cls: "text-rose-600" },
  { key: "unknown", label: "À vérifier",    icon: ShieldQuestion, cls: "text-slate-500" },
];

export default function PrivacyCompatCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  async function scan() {
    setLoading(true);
    try {
      const { data } = await api.get("/livre/privacy/tracker-compatibility");
      setData(data);
    } catch (e) {
      toast.error("Échec du scan de compatibilité");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { scan(); /* eslint-disable-next-line */ }, []);

  return (
    <Card
      data-testid="privacy-compat-card"
      className="bg-white border-slate-200 shadow-sm rounded-md p-6"
    >
      <div className="flex items-start justify-between gap-4 mb-1">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-slate-500" />
            Compatibilité « Mode privé » par véhicule
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Phase 1 — Scan en lecture seule. Aucune commande n&apos;est envoyée aux traceurs.
            Cet écran identifie, à partir du modèle synchronisé via Navixy, quels véhicules
            pourront recevoir un ordre d&apos;arrêt d&apos;émission GPS en Phase 2.
          </p>
        </div>
        <Button
          size="sm" variant="outline" onClick={scan} disabled={loading}
          data-testid="privacy-compat-rescan"
        >
          {loading ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1.5" />}
          Re-scanner
        </Button>
      </div>

      <div className="mt-4 mb-5 grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="privacy-compat-counters">
        {COUNTER_META.map(c => {
          const Icon = c.icon;
          return (
            <div key={c.key}
              className="border border-slate-200 rounded-md p-3 flex items-center justify-between"
              data-testid={`privacy-compat-counter-${c.key}`}
            >
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-400">{c.label}</p>
                <p className={`text-2xl font-semibold mt-0.5 ${c.cls}`}>
                  {data ? data.counters[c.key] : "—"}
                </p>
              </div>
              <Icon className={`w-6 h-6 ${c.cls} opacity-70`} />
            </div>
          );
        })}
      </div>

      <div className="bg-slate-50 border border-slate-200 rounded-md p-3 mb-4 flex gap-2 text-xs text-slate-600">
        <Info className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
        <span>
          La détection se fait par <strong>modèle de traceur</strong> (Teltonika FMC130 / FMC230 / FMC003 = compatibles,
          smartphones Navixy = non supportés, modèles inconnus = à vérifier manuellement).
          Aucun appel sortant vers les traceurs n&apos;est effectué tant que la Phase 2 n&apos;est pas activée.
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="privacy-compat-table">
          <thead>
            <tr className="bg-slate-50 text-slate-500 text-xs font-medium uppercase tracking-wider">
              <th className="text-left py-3 px-4">Plaque</th>
              <th className="text-left py-3 px-4">Modèle</th>
              <th className="text-left py-3 px-4">Famille détectée</th>
              <th className="text-left py-3 px-4">Statut</th>
              <th className="text-left py-3 px-4">Commande prévue (Phase 2)</th>
            </tr>
          </thead>
          <tbody>
            {!data ? (
              <tr><td colSpan={5} className="py-10 text-center text-slate-400">
                <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> Scan en cours…
              </td></tr>
            ) : data.rows.length === 0 ? (
              <tr><td colSpan={5} className="py-8 text-center text-slate-400">Aucun véhicule.</td></tr>
            ) : (
              data.rows.map(r => {
                const meta = STATUS_META[r.status] || STATUS_META.unknown;
                const Icon = meta.icon;
                return (
                  <tr key={r.vehicle_id}
                    className="border-t border-slate-100 hover:bg-slate-50/60"
                    data-testid={`privacy-compat-row-${r.status}`}
                  >
                    <td className="py-3 px-4 font-mono text-xs">{r.plate}</td>
                    <td className="py-3 px-4 text-slate-700 text-xs">{r.model || "—"}</td>
                    <td className="py-3 px-4 text-slate-600 text-xs">{r.family}</td>
                    <td className="py-3 px-4">
                      <Badge variant="outline" className={`${meta.color} font-medium`}>
                        <Icon className="w-3 h-3 mr-1.5" /> {meta.label}
                      </Badge>
                    </td>
                    <td className="py-3 px-4 text-xs text-slate-500 font-mono">
                      {r.recommended_command || <span className="text-slate-400 italic">—</span>}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-slate-400 mt-4 italic">
        Phase 2 (à activer ultérieurement) : envoi automatique des commandes de mise en mode privé
        selon les plages horaires personnelles et le mode véhicule, avec garde-fou timeout 24h.
      </p>
    </Card>
  );
}
