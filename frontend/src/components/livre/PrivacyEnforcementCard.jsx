import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import {
  AlertTriangle, Loader2, Power, ZapOff, FlaskConical,
  Lock,
} from "lucide-react";

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
  const [lastRun, setLastRun] = useState(null);
  const [states, setStates] = useState([]);
  const [running, setRunning] = useState(false);
  const [killing, setKilling] = useState(false);

  async function loadAll() {
    try {
      const [c, s] = await Promise.all([
        api.get("/livre/privacy/enforcement-config").then(r => r.data),
        api.get("/livre/privacy/state").then(r => r.data),
      ]);
      setConfig(c);
      setStates(s.rows || []);
    } catch {
      toast.error("Impossible de charger la configuration enforcement");
    }
  }

  useEffect(() => { loadAll(); /* eslint-disable-next-line */ }, []);

  async function updateConfig(patch) {
    try {
      const { data } = await api.put("/livre/privacy/enforcement-config", patch);
      setConfig(data);
      toast.success("Configuration enregistrée");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    }
  }

  async function enforceNow() {
    setRunning(true);
    try {
      const { data } = await api.post("/livre/privacy/enforce-now");
      setLastRun(data);
      await loadAll();
      const mode = data.simulation ? "simulés" : "envoyés";
      toast.success(`${data.executed} ordre(s) ${mode}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    } finally { setRunning(false); }
  }

  async function killSwitch() {
    if (!window.confirm(
      "⚠️ KILL SWITCH\n\nRéactive immédiatement le tracking GPS sur tous les traceurs en mode privé.\n\nContinuer ?"
    )) return;
    setKilling(true);
    try {
      const { data } = await api.post("/livre/privacy/kill-switch");
      await loadAll();
      toast.success(`Kill switch · ${data.sent} cmd · ${data.errors} err`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    } finally { setKilling(false); }
  }

  const enabled = !!config?.enabled;
  const simulation = !!config?.simulation;

  // last run summary string
  const summary = lastRun
    ? `${lastRun.sent_real}r · ${lastRun.simulated}s · ${lastRun.skipped}⊘ · ${lastRun.errors}✕`
    : `${states.filter(s => s.last_command_result === "success").length}r · ${states.filter(s => s.last_command_result === "simulated").length}s · 0⊘ · ${states.filter(s => s.last_command_result === "error").length}✕`;

  return (
    <div data-testid="privacy-enforcement-card" className="h-full flex flex-col">
      {!simulation && enabled && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 rounded-md p-2.5 text-[11px] flex gap-1.5 items-start mb-3"
             data-testid="privacy-real-mode-warning">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span><strong>Mode réel actif.</strong> Les commandes vont jusqu&apos;aux traceurs.</span>
        </div>
      )}

      <div className="space-y-3 flex-1">
        <div className="border border-slate-200 rounded-md p-3 flex items-start justify-between gap-2 bg-white">
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
              <Lock className="w-3.5 h-3.5 text-slate-500" />
              Activer l&apos;enforcement
            </p>
            <p className="text-[10px] text-slate-500 mt-1 leading-snug">
              Active le job APScheduler qui évalue les états toutes les 5 min.
            </p>
          </div>
          <Switch
            checked={enabled}
            onCheckedChange={(v) => updateConfig({ enabled: v })}
            data-testid="privacy-toggle-enabled"
          />
        </div>

        <div className="border border-slate-200 rounded-md p-3 flex items-start justify-between gap-2 bg-white">
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
              <FlaskConical className="w-3.5 h-3.5 text-amber-600" />
              Mode simulation
            </p>
            <p className="text-[10px] text-slate-500 mt-1 leading-snug">
              Recommandé pour démarrer. Logue les commandes dans l&apos;audit sans les envoyer aux traceurs.
            </p>
          </div>
          <Switch
            checked={simulation}
            onCheckedChange={(v) => updateConfig({ simulation: v })}
            data-testid="privacy-toggle-simulation"
          />
        </div>

        <div className="flex gap-2">
          <Button size="sm" onClick={enforceNow} disabled={running || !enabled}
            data-testid="privacy-enforce-now"
            className="flex-1 bg-[#2196F3] hover:bg-[#1E88E5] text-white">
            {running ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Power className="w-3.5 h-3.5 mr-1.5" />}
            Forcer maintenant
          </Button>
          <Button size="sm" variant="destructive" onClick={killSwitch} disabled={killing}
            data-testid="privacy-kill-switch" className="flex-1">
            {killing ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <ZapOff className="w-3.5 h-3.5 mr-1.5" />}
            Kill switch
          </Button>
        </div>

        <div className="border border-slate-200 rounded-md p-3 bg-slate-50 text-xs space-y-1.5" data-testid="privacy-last-run">
          <div className="flex justify-between text-slate-600">
            <span className="font-medium">Dernier run :</span>
            <span className="font-mono">{summary}</span>
          </div>
          <div className="flex justify-between text-slate-600">
            <span className="font-medium">Mode :</span>
            <span className={`font-semibold ${simulation ? "text-amber-600" : "text-rose-600"}`}>
              {simulation ? "Simulation" : "Réel"}
            </span>
          </div>
          <div className="flex justify-between text-slate-500 text-[11px]">
            <span>Statut :</span>
            <span>{enabled ? "Actif" : "Désactivé"}</span>
          </div>
          {states.length > 0 && states[0].last_command_at && (
            <div className="flex justify-between text-slate-500 text-[11px] pt-1 border-t border-slate-200">
              <span>Dernière commande :</span>
              <span>{fmtAgo(states[0].last_command_at)}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
