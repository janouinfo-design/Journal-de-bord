import { useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Layers, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";

const TOKEN = new URLSearchParams(window.location.search).get("token");

export default function InvitationPage() {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [formError, setFormError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!TOKEN) {
      setError("Lien d'invitation invalide — paramètre manquant.");
      setLoading(false);
      return;
    }
    api.get(`/auth/invitation/${TOKEN}`)
      .then(({ data }) => setInfo(data))
      .catch((e) => setError(formatApiErrorDetail(e.response?.data?.detail)))
      .finally(() => setLoading(false));
  }, []);

  async function submit(e) {
    e.preventDefault();
    setFormError(null);
    if (pw.length < 8) return setFormError("Le mot de passe doit contenir au moins 8 caractères.");
    if (pw !== pw2) return setFormError("Les deux mots de passe ne correspondent pas.");
    setSaving(true);
    try {
      await api.post(`/auth/invitation/${TOKEN}/accept`, { password: pw });
      setDone(true);
      setTimeout(() => window.location.replace("/driver"), 1800);
    } catch (err) {
      setFormError(formatApiErrorDetail(err.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#F4F6F8] flex items-center justify-center p-6 font-[IBM_Plex_Sans,sans-serif]">
      <div data-testid="invitation-page" className="bg-white rounded-xl border border-slate-200 shadow-sm max-w-md w-full p-8 space-y-5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-slate-900 flex items-center justify-center text-white">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <div className="text-lg font-semibold tracking-tight text-slate-900 leading-tight">LogiTrak</div>
            <p className="text-[9px] uppercase tracking-[0.22em] text-slate-400 font-semibold">Journal de bord</p>
          </div>
        </div>

        {loading ? (
          <div className="py-10 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" /></div>
        ) : error ? (
          <div data-testid="invitation-error" className="py-6 text-center space-y-3">
            <AlertTriangle className="w-10 h-10 text-amber-500 mx-auto" />
            <p className="text-sm text-slate-700 font-medium">{error}</p>
            <p className="text-xs text-slate-500">Demandez à votre administrateur de vous renvoyer une invitation.</p>
          </div>
        ) : done ? (
          <div data-testid="invitation-success" className="py-6 text-center space-y-3">
            <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto" />
            <p className="text-sm text-slate-700 font-medium">Compte activé ! Connexion en cours…</p>
          </div>
        ) : (
          <>
            <div>
              <h1 className="text-xl font-semibold text-slate-900">Bienvenue {info?.driver_name}</h1>
              <p className="text-sm text-slate-500 mt-1">
                Vous êtes invité(e) à activer votre accès chauffeur pour <strong>{info?.company}</strong>.
                Choisissez un mot de passe pour le compte <strong>{info?.email}</strong>.
              </p>
            </div>
            <form onSubmit={submit} className="space-y-4">
              <div className="space-y-1.5">
                <Label>Mot de passe (min. 8 caractères)</Label>
                <Input data-testid="invitation-password" type="password" value={pw}
                       onChange={(e) => setPw(e.target.value)} autoFocus />
              </div>
              <div className="space-y-1.5">
                <Label>Confirmez le mot de passe</Label>
                <Input data-testid="invitation-password-confirm" type="password" value={pw2}
                       onChange={(e) => setPw2(e.target.value)} />
              </div>
              {formError && (
                <p data-testid="invitation-form-error" className="text-sm text-rose-600">{formError}</p>
              )}
              <Button data-testid="invitation-submit" type="submit" className="w-full"
                      disabled={saving || !pw || !pw2}>
                {saving ? "Activation…" : "Activer mon compte"}
              </Button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
