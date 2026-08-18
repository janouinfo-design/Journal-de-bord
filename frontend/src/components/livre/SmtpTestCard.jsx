import { useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Send, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";

export default function SmtpTestCard() {
  const { user } = useAuth();
  const [status, setStatus] = useState(null);
  const [to, setTo] = useState(user?.email || "");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    api.get("/livre/settings/smtp-status").then(({ data }) => setStatus(data)).catch(() => {});
  }, []);

  async function test() {
    setSending(true);
    setResult(null);
    try {
      const { data } = await api.post("/livre/settings/smtp-test", { to });
      setResult({ ok: true, msg: `Email de test envoyé à ${data.to} — vérifiez la boîte de réception (et les spams).` });
      toast.success(`Email de test envoyé à ${data.to}`);
    } catch (e) {
      const msg = formatApiErrorDetail(e.response?.data?.detail) || "Échec de l'envoi";
      setResult({ ok: false, msg });
      toast.error(msg);
    } finally {
      setSending(false);
    }
  }

  if (!status) return <p className="text-xs text-slate-400">Chargement de la configuration…</p>;

  return (
    <div data-testid="smtp-test-card" className="space-y-3">
      {status.configured ? (
        <div className="flex items-center gap-2 text-xs">
          <span data-testid="smtp-status-badge"
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200 font-medium">
            <CheckCircle2 className="w-3 h-3" /> Configuré
          </span>
          <span className="text-slate-500">
            Serveur <span className="font-mono text-slate-700">{status.host}:{status.port}</span> ·
            expéditeur <span className="font-mono text-slate-700">{status.from_addr}</span>
            {!status.user_set && " · sans authentification"}
          </span>
        </div>
      ) : (
        <div data-testid="smtp-not-configured"
             className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 space-y-1">
          <p className="font-semibold flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5" /> SMTP non configuré — les emails (invitations chauffeur) ne partent pas.
          </p>
          <p>
            Sur votre serveur, renseignez dans le fichier <span className="font-mono">.env</span> :{" "}
            <span className="font-mono">SMTP_HOST</span>, <span className="font-mono">SMTP_PORT</span> (587 ou 465),{" "}
            <span className="font-mono">SMTP_USER</span>, <span className="font-mono">SMTP_PASSWORD</span>,{" "}
            <span className="font-mono">SMTP_FROM</span> — puis{" "}
            <span className="font-mono">docker compose up -d backend</span>.
          </p>
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <Input data-testid="smtp-test-to" type="email" value={to} onChange={(e) => setTo(e.target.value)}
               placeholder="destinataire@exemple.ch" className="h-9 w-[260px]" disabled={!status.configured} />
        <Button data-testid="smtp-test-send" onClick={test} disabled={!status.configured || sending || !to}
                className="h-9 bg-[#2196F3] hover:bg-[#1976D2] text-white">
          {sending ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Send className="w-4 h-4 mr-1.5" />}
          {sending ? "Envoi…" : "Tester l'envoi"}
        </Button>
      </div>

      {result && (
        <p data-testid="smtp-test-result"
           className={`text-xs flex items-start gap-1.5 ${result.ok ? "text-emerald-700" : "text-rose-600"}`}>
          {result.ok ? <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                     : <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />}
          {result.msg}
        </p>
      )}
    </div>
  );
}
