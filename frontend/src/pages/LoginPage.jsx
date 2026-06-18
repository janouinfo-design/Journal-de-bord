import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { Navigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TEST_IDS } from "@/constants/testIds";
import { Truck, MapPin, FileText, Loader2 } from "lucide-react";

// Demo / mock seed accounts shown intentionally on the login screen so testers
// can sign in without provisioning real users. These credentials are public
// (also seeded by the backend) and DO NOT grant access to any production data.
// They live in env vars too: ADMIN_EMAIL/PASSWORD, MANAGER_EMAIL/PASSWORD,
// DRIVER_EMAIL/PASSWORD in backend/.env.
const DEMO = [
  { id: TEST_IDS.auth.demoAdmin, label: "Admin", email: "admin@logitrak.ch", password: "admin123", desc: "Accès complet" },
  { id: TEST_IDS.auth.demoManager, label: "Gestionnaire", email: "manager@logitrak.ch", password: "manager123", desc: "Selon politique" },
  { id: TEST_IDS.auth.demoDriver, label: "Chauffeur", email: "chauffeur@logitrak.ch", password: "chauffeur123", desc: "Ses trajets" },
];

export default function LoginPage() {
  const { user, login, loading } = useAuth();
  const [email, setEmail] = useState("");
  const [pwd, setPwd] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState("");

  if (loading) return null;
  if (user) return <Navigate to="/livre/dashboard" replace />;

  async function onSubmit(e) {
    e.preventDefault();
    setErr("");
    setSubmitting(true);
    const r = await login(email, pwd);
    setSubmitting(false);
    if (!r.ok) setErr(r.error);
  }

  function pickDemo(d) {
    setEmail(d.email);
    setPwd(d.password);
  }

  return (
    <div data-testid={TEST_IDS.auth.page} className="min-h-screen flex bg-slate-50">
      {/* Left visual panel */}
      <div className="hidden lg:flex lg:w-1/2 bg-slate-900 text-white p-12 flex-col justify-between relative overflow-hidden">
        <div className="absolute inset-0 opacity-30" style={{
          backgroundImage: "radial-gradient(circle at 30% 20%, #2196F3 0, transparent 40%), radial-gradient(circle at 80% 70%, #1976D2 0, transparent 40%)"
        }} />
        <div className="relative">
          <div className="flex items-center gap-3 text-2xl font-semibold tracking-tight">
            <span className="text-white">Logi<span className="text-[#E53935]">t</span>rak</span>
          </div>
          <p className="text-slate-400 mt-2 text-xs uppercase tracking-[0.2em]">Géolocalisation et logistique</p>
        </div>
        <div className="relative space-y-6">
          <h1 className="text-4xl xl:text-5xl font-semibold leading-tight tracking-tight">
            Livre de Bord<br/>
            <span className="text-[#2196F3]">Pro / Personnel</span>
          </h1>
          <p className="text-slate-300 text-base max-w-md leading-relaxed">
            Séparez automatiquement vos kilomètres professionnels et personnels grâce aux données GPS LOGITRAK.
            Confidentialité configurable, rapports fiscaux suisses.
          </p>
          <div className="grid grid-cols-3 gap-3 max-w-md pt-4">
            {[
              { icon: MapPin, label: "GPS LOGITRAK" },
              { icon: Truck, label: "Multi-véhicules" },
              { icon: FileText, label: "Fiscal CH" },
            ].map((f) => (
              <div key={f.label} className="bg-white/5 border border-white/10 rounded-md p-3 backdrop-blur-sm">
                <f.icon className="w-5 h-5 text-[#2196F3]" />
                <p className="text-xs mt-2 text-slate-200">{f.label}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="relative text-xs text-slate-500">© Logitrak SA — Genève</div>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center p-6 lg:p-12">
        <div className="w-full max-w-md">
          <div className="lg:hidden text-2xl font-semibold mb-8">
            Logi<span className="text-[#E53935]">t</span>rak
          </div>
          <h2 className="text-3xl font-semibold tracking-tight text-slate-900">Connexion</h2>
          <p className="text-sm text-slate-500 mt-2">Accédez au module Livre de Bord</p>

          <form onSubmit={onSubmit} className="mt-8 space-y-5">
            <div>
              <Label htmlFor="email" className="text-xs font-semibold tracking-wide uppercase text-slate-500">Email</Label>
              <Input
                id="email" type="email" required
                data-testid={TEST_IDS.auth.emailInput}
                value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@logitrak.ch"
                className="mt-1.5 h-11"
              />
            </div>
            <div>
              <Label htmlFor="pwd" className="text-xs font-semibold tracking-wide uppercase text-slate-500">Mot de passe</Label>
              <Input
                id="pwd" type="password" required
                data-testid={TEST_IDS.auth.passwordInput}
                value={pwd} onChange={(e) => setPwd(e.target.value)}
                placeholder="••••••••"
                className="mt-1.5 h-11"
              />
            </div>
            {err && (
              <p data-testid={TEST_IDS.auth.error} className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                {err}
              </p>
            )}
            <Button
              type="submit" disabled={submitting}
              data-testid={TEST_IDS.auth.submit}
              className="w-full h-11 bg-[#2196F3] hover:bg-[#1E88E5] text-white font-medium"
            >
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : "Se connecter"}
            </Button>
          </form>

          <div className="mt-8">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400 mb-3">Comptes de démo</p>
            <div className="space-y-2">
              {DEMO.map((d) => (
                <button
                  key={d.email}
                  type="button"
                  data-testid={d.id}
                  onClick={() => pickDemo(d)}
                  className="w-full text-left bg-white border border-slate-200 hover:border-[#2196F3] hover:bg-blue-50/40 rounded-md px-4 py-3 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-slate-800">{d.label}</p>
                      <p className="text-xs text-slate-500 mt-0.5">{d.email}</p>
                    </div>
                    <span className="text-[10px] uppercase tracking-wider text-slate-400">{d.desc}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
