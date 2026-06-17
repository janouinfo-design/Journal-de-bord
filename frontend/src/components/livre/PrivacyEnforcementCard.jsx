import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import {
  AlertTriangle, Loader2, Power, ZapOff, RefreshCw, ShieldX,
  CheckCircle2, XCircle, FlaskConical, Radio,
} from "lucide-react";

const STATE_BADGE = {
  tracking: { color: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Tracking actif", icon: Radio },
  private:  { color: "bg-slate-100 text-slate-700 border-slate-300",      label: "Mode privé",     icon: ShieldX },
};

const RESULT_BADGE = {
  success:   { color: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "OK",        icon: CheckCircle2 },
  simulated: { color: "bg-amber-50 text-amber-700 border-amber-200",       label: "Simulé",    icon: FlaskConical },
  error:     { color: "bg-rose-50 text-rose-700 border-rose-200",          label: "Erreur",    icon: XCircle },
  pending:   { color: "bg-slate-100 text-slate-600 border-slate-200",      label: "En attente", icon: Loader2 },
};

function fmtAgo(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "il y a quelques secondes";
  if (diff < 3600) return `il y a ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `il y a ${Math.floor(diff / 3600)} h`;
  return d.toLocaleString("fr-CH");
}

export default function PrivacyEnforcementCard() {
  const [config, setConfig] = useState(null);
  const [states, setStates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [killing, setKilling] = useState(false);
  const [lastRun, setLastRun] = useState(null);

  async function loadAll() {
    setLoading(true);
    try {
      const [c, s] = await Promise.all([
        api.get("/livre/privacy/enforcement-config").then(r => r.data),
        api.get("/livre/privacy/state").then(r => r.data),
      ]);
      setConfig(c);
      setStates(s.rows || []);
    } catch (e) {
      toast.error("Impossible de charger la configuration");
    } finally { setLoading(false); }
  }

  useEffect(() => { loadAll(); /* eslint-disable-next-line */ }, []);

  async function updateConfig(patch) {
    try {
      const { data } = await api.put("/livre/privacy/enforcement-config", patch);
      setConfig(data);
      toast.success("Configuration enregistrée");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec de la mise à jour");
    }
  }

  async function enforceNow() {
    setRunning(true);
    try {
      const { data } = await api.post("/livre/privacy/enforce-now");
      setLastRun(data);
      await loadAll();
      const mode = data.simulation ? "simulés" : "envoyés";
      toast.success(`${data.executed} ordre(s) ${mode} · ${data.skipped} ignoré(s) · ${data.errors} erreur(s)`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec de l'enforcement");
    } finally { setRunning(false); }
  }

  async function killSwitch() {
    if (!window.confirm(
      "⚠️ KILL SWITCH\n\nCette action va envoyer immédiatement à TOUS les traceurs " +
      "actuellement en mode privé une commande pour réactiver le tracking GPS. " +
      "Elle bypasse la simulation et le toggle d'enforcement.\n\n" +
      "À utiliser uniquement en cas d'urgence (perte de visibilité non désirée).\n\n" +
      "Continuer ?"
    )) return;
    setKilling(true);
    try {
      const { data } = await api.post("/livre/privacy/kill-switch");
      await loadAll();
      toast.success(`Kill switch exécuté · ${data.sent} commande(s) envoyée(s) · ${data.errors} erreur(s)`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec du kill switch");
    } finally { setKilling(false); }
  }

  const enabled = !!config?.enabled;
  const simulation = !!config?.simulation;

  return (
    <Card
      data-testid="privacy-enforcement-card"
      className="bg-white border-slate-200 shadow-sm rounded-md p-6"
    >
      <div className="flex items-start justify-between gap-4 mb-1">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
            <Power className={`w-4 h-4 ${enabled ? "text-emerald-600" : "text-slate-400"}`} />
            Enforcement du mode privé (Phase 2)
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Envoie automatiquement les commandes <span className="font-mono">setparam 11000:0/4</span> aux
            traceurs Teltonika compatibles, toutes les 5 min, selon les plages horaires et le mode véhicule.
            En mode <strong>simulation</strong> les commandes sont uniquement loguées sans être transmises.
          </p>
        </div>
        <Button
          size="sm" variant="outline" onClick={loadAll} disabled={loading}
          data-testid="privacy-enforcement-refresh"
        >
          {loading ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1.5" />}
          Rafraîchir
        </Button>
      </div>

      {!simulation && enabled && (
        <div className="mt-3 mb-3 bg-rose-50 border border-rose-200 text-rose-800 rounded-md p-3 text-xs flex gap-2 items-start"
             data-testid="privacy-real-mode-warning">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span><strong>Mode réel actif.</strong> Les prochains envois iront jusqu&apos;aux traceurs.
            Vérifie les horaires et les modes véhicule avant de partir en weekend.</span>
        </div>
      )}

      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="border border-slate-200 rounded-md p-4 flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold text-slate-700">Activer l&apos;enforcement</p>
            <p className="text-[11px] text-slate-500 mt-1">
              Active le job APScheduler qui évalue les états attendus toutes les 5 min.
            </p>
          </div>
          <Switch
            checked={enabled}
            onCheckedChange={(v) => updateConfig({ enabled: v })}
            data-testid="privacy-toggle-enabled"
          />
        </div>
        <div className="border border-slate-200 rounded-md p-4 flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
              <FlaskConical className="w-3.5 h-3.5 text-amber-600" /> Mode simulation
            </p>
            <p className="text-[11px] text-slate-500 mt-1">
              Recommandé pour démarrer. Logue les commandes dans l&apos;audit sans les envoyer aux traceurs.
            </p>
          </div>
          <Switch
            checked={simulation}
            onCheckedChange={(v) => updateConfig({ simulation: v })}
            data-testid="privacy-toggle-simulation"
          />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          size="sm" onClick={enforceNow} disabled={running || !enabled}
          data-testid="privacy-enforce-now"
        >
          {running ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Power className="w-4 h-4 mr-1.5" />}
          Forcer maintenant
        </Button>
        <Button
          size="sm" variant="destructive" onClick={killSwitch} disabled={killing}
          data-testid="privacy-kill-switch"
        >
          {killing ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <ZapOff className="w-4 h-4 mr-1.5" />}
          Kill switch — réactiver tout
        </Button>
        {lastRun && (
          <span className="text-[11px] text-slate-500 self-center" data-testid="privacy-last-run">
            Dernier run : {lastRun.sent_real}r · {lastRun.simulated}s · {lastRun.skipped}⊘ · {lastRun.errors}✕
          </span>
        )}
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full text-sm" data-testid="privacy-state-table">
          <thead>
            <tr className="bg-slate-50 text-slate-500 text-xs font-medium uppercase tracking-wider">
              <th className="text-left py-3 px-4">Plaque</th>
              <th className="text-left py-3 px-4">État attendu</th>
              <th className="text-left py-3 px-4">Dernière commande</th>
              <th className="text-left py-3 px-4">Mode</th>
              <th className="text-left py-3 px-4">Résultat</th>
              <th className="text-left py-3 px-4">Quand</th>
            </tr>
          </thead>
          <tbody>
            {states.length === 0 ? (
              <tr><td colSpan={6} className="py-8 text-center text-slate-400">
                Aucun véhicule compatible n&apos;a encore d&apos;état. Clique sur « Forcer maintenant » pour initialiser.
              </td></tr>
            ) : states.map(r => {
              const sb = STATE_BADGE[r.expected_state] || { color: "bg-slate-100 text-slate-500 border-slate-200", label: "—", icon: Radio };
              const rb = RESULT_BADGE[r.last_command_result] || RESULT_BADGE.pending;
              const SIcon = sb.icon, RIcon = rb.icon;
              return (
                <tr key={r.vehicle_id}
                  className="border-t border-slate-100 hover:bg-slate-50/60"
                  data-testid={`privacy-state-row-${r.expected_state || "unknown"}`}
                >
                  <td className="py-3 px-4 font-mono text-xs">{r.plate}</td>
                  <td className="py-3 px-4">
                    <Badge variant="outline" className={`${sb.color} font-medium`}>
                      <SIcon className="w-3 h-3 mr-1.5" />{sb.label}
                    </Badge>
                  </td>
                  <td className="py-3 px-4 text-xs font-mono text-slate-600">{r.last_command || "—"}</td>
                  <td className="py-3 px-4 text-xs text-slate-500">
                    {r.last_command_mode === "simulation" ? "Simulation" : r.last_command_mode === "real" ? "Réel" : "—"}
                  </td>
                  <td className="py-3 px-4">
                    <Badge variant="outline" className={`${rb.color} font-medium`}>
                      <RIcon className="w-3 h-3 mr-1.5" />{rb.label}
                    </Badge>
                    {r.last_command_error && (
                      <div className="text-[10px] text-rose-600 mt-1 truncate max-w-xs" title={r.last_command_error}>
                        {r.last_command_error}
                      </div>
                    )}
                  </td>
                  <td className="py-3 px-4 text-xs text-slate-500">{fmtAgo(r.last_command_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-slate-400 mt-4 italic">
        Les véhicules incompatibles (smartphones, modèles inconnus) sont ignorés automatiquement.
        L&apos;état attendu est calculé à partir du mode véhicule (always_pro/always_perso/mixte) et de l&apos;horaire chauffeur.
      </p>
    </Card>
  );
}
