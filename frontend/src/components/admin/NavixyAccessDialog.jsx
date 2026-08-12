import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Copy, PlugZap } from "lucide-react";

const ACCESS_BADGE = {
  configured: { label: "Configuré", cls: "bg-emerald-100 text-emerald-700" },
  untested: { label: "À tester", cls: "bg-slate-100 text-slate-600" },
  incomplete: { label: "Incomplet", cls: "bg-amber-100 text-amber-700" },
  error: { label: "Erreur", cls: "bg-red-100 text-red-700" },
};
const SYNC_BADGE = {
  never: { label: "Jamais exécutée", cls: "bg-slate-100 text-slate-500" },
  ok: { label: "Réussie", cls: "bg-emerald-100 text-emerald-700" },
  error: { label: "En erreur", cls: "bg-red-100 text-red-700" },
};
const FAIL_LABEL = {
  invalid_format: "Format de clé invalide",
  navixy_rejected: "Session refusée par Navixy",
  navixy_timeout: "Navixy injoignable (délai dépassé)",
  tenant_unmapped: "Entreprise non rattachée",
  tenant_suspended: "Entreprise suspendue",
  internal_error: "Erreur interne",
};
const TEST_ERROR_LABEL = {
  no_key: "Clé API non configurée",
  invalid_key_or_unreachable: "Clé invalide ou API Navixy injoignable",
  master_mismatch: "La clé appartient à un autre compte maître Navixy",
};

function Row({ label, children }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <span className="text-xs text-slate-400 uppercase tracking-wider shrink-0">{label}</span>
      <span className="text-sm text-slate-800 text-right min-w-0 break-words">{children}</span>
    </div>
  );
}

export default function NavixyAccessDialog({ tenant, onClose }) {
  const [data, setData] = useState(null);
  const [testing, setTesting] = useState(false);
  const url = window.location.origin;

  const load = useCallback(() => {
    api.get(`/admin/tenants/${tenant.id}/navixy-access`)
      .then(({ data }) => setData(data))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
  }, [tenant.id]);
  useEffect(() => { load(); }, [load]);

  function copyUrl() {
    navigator.clipboard.writeText(url)
      .then(() => toast.success("URL copiée"))
      .catch(() => toast.error("Copie impossible — copiez manuellement"));
  }

  async function runTest() {
    setTesting(true);
    try {
      const { data: r } = await api.post(`/admin/tenants/${tenant.id}/test-navixy`);
      if (r.ok) toast.success("Connexion Navixy vérifiée");
      else toast.error(TEST_ERROR_LABEL[r.error] || "Test en échec");
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setTesting(false); }
  }

  const access = ACCESS_BADGE[data?.access_status] || ACCESS_BADGE.untested;
  const sync = SYNC_BADGE[data?.sync?.status] || SYNC_BADGE.never;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="navixy-access-dialog"
                     className="w-[95vw] sm:max-w-xl max-h-[85vh] overflow-y-auto overflow-x-hidden">
        <DialogHeader>
          <DialogTitle>Accès Navixy — {tenant.name}</DialogTitle>
        </DialogHeader>
        {!data ? <p className="text-sm text-slate-400 py-4">Chargement…</p> : (
          <div className="space-y-4">
            <div className="rounded-lg border border-slate-200 p-3 space-y-2">
              <p className="text-xs text-slate-400 uppercase tracking-wider">URL officielle à configurer dans Navixy</p>
              <div className="flex items-center gap-2 min-w-0">
                <code data-testid="navixy-access-url" className="flex-1 min-w-0 text-sm bg-slate-50 rounded px-2 py-1.5 truncate">{url}</code>
                <Button data-testid="navixy-access-copy" variant="outline" size="sm" onClick={copyUrl}>
                  <Copy className="w-3.5 h-3.5 mr-1" /> Copier
                </Button>
              </div>
              <ol className="text-xs text-slate-500 list-decimal ml-4 space-y-0.5">
                <li>Panneau Navixy du client → <strong>Applications utilisateur</strong></li>
                <li>Créer/modifier l'application « Journal de bord »</li>
                <li>Méthode d'authentification : <strong>Session key</strong></li>
                <li>Coller l'URL ci-dessus, enregistrer</li>
                <li>L'application apparaît dans le menu Navixy — la reconnaissance du client est automatique</li>
              </ol>
            </div>

            <div className="rounded-lg border border-slate-200 p-3">
              <Row label="Tenant lié">{data.tenant.name} <span className="text-slate-400 text-xs">({data.tenant.id})</span></Row>
              <Row label="Compte maître">
                {data.master.login || "—"}
                {data.master.id ? <span className="text-slate-400 text-xs"> · #{data.master.id}</span> : null}
              </Row>
              <Row label="Accès Navixy">
                <span data-testid="navixy-access-status"
                      className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${access.cls}`}>{access.label}</span>
                {data.last_test?.at && (
                  <span className="block text-[11px] text-slate-400">
                    testé le {fmtDateTime(data.last_test.at)}
                    {data.last_test.error ? ` — ${TEST_ERROR_LABEL[data.last_test.error] || data.last_test.error}` : ""}
                  </span>
                )}
              </Row>
              <Row label="Synchronisation">
                <span data-testid="navixy-sync-status"
                      className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${sync.cls}`}>{sync.label}</span>
                {data.sync.last_sync_at && (
                  <span className="block text-[11px] text-slate-400">le {fmtDateTime(data.sync.last_sync_at)}</span>
                )}
                {data.sync.error && <span className="block text-[11px] text-red-600">{data.sync.error}</span>}
              </Row>
              <Row label="Dernier accès SSO">
                <span data-testid="navixy-last-sso">{data.last_sso_at ? fmtDateTime(data.last_sso_at) : "Jamais"}</span>
              </Row>
            </div>

            <div className="flex items-center justify-between gap-3">
              <Button data-testid="navixy-test-btn" onClick={runTest} disabled={testing}
                      className="bg-slate-900 hover:bg-slate-800 text-white">
                <PlugZap className="w-4 h-4 mr-1.5" /> {testing ? "Test en cours…" : "Tester la connexion"}
              </Button>
              <p className="flex-1 min-w-0 text-[10px] text-slate-400 text-right break-words">
                Le test valide la clé API permanente — il ne crée ni session ni utilisateur.
              </p>
            </div>

            <div className="rounded-lg border border-slate-200 p-3">
              <p className="text-xs text-slate-400 uppercase tracking-wider mb-1.5">Erreurs de connexion récentes</p>
              {data.recent_errors.length === 0 ? (
                <p data-testid="navixy-errors-empty" className="text-xs text-slate-400">Aucune erreur récente</p>
              ) : data.recent_errors.map((e, i) => (
                <p key={i} className="text-xs text-slate-600">
                  {fmtDateTime(e.at)} — {FAIL_LABEL[e.category] || e.category}
                </p>
              ))}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
