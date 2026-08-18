import { createContext, useContext, useEffect, useState } from "react";
import { api, formatApiErrorDetail, IMP_TOKEN_KEY } from "@/lib/api";

const AuthContext = createContext(null);

// Capturé au chargement du module (avant React/StrictMode) : clé SSO Navixy
const NAVIXY_SSO_KEY = (() => {
  const params = new URLSearchParams(window.location.search);
  const key = params.get("session_key");
  if (key) {
    params.delete("session_key");
    const qs = params.toString();
    window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
  }
  return key;
})();

// Token d'aperçu « Se connecter comme… » (usage unique, 60 s) transmis via l'URL
const IMPERSONATION_TOKEN = (() => {
  const params = new URLSearchParams(window.location.search);
  const t = params.get("imp_token");
  if (t) {
    params.delete("imp_token");
    const qs = params.toString();
    window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
  }
  return t;
})();

// Échange mémoïsé au niveau module : le token est à usage unique, StrictMode
// (double mount) ne doit déclencher qu'UNE seule requête d'échange.
let _impExchangePromise = null;
function exchangeImpersonationToken() {
  if (!_impExchangePromise) {
    _impExchangePromise = api.post("/auth/impersonate", { token: IMPERSONATION_TOKEN })
      .then(({ data }) => {
        sessionStorage.setItem(IMP_TOKEN_KEY, data.access_token);
        return null;
      })
      .catch((e) => {
        sessionStorage.removeItem(IMP_TOKEN_KEY);
        return formatApiErrorDetail(e.response?.data?.detail) || "Lien d'aperçu invalide ou expiré";
      });
  }
  return _impExchangePromise;
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);     // user object | null
  const [loading, setLoading] = useState(true);
  const [impersonationEnded, setImpersonationEnded] = useState(false);
  const [impersonationError, setImpersonationError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Aperçu utilisateur : échange du token contre une session Bearer (isolée à cet onglet)
      if (IMPERSONATION_TOKEN) {
        const err = await exchangeImpersonationToken();
        if (err && !cancelled) setImpersonationError(err);
      } else if (NAVIXY_SSO_KEY) {
        // SSO Navixy : si l'iframe a été chargée avec ?session_key=..., connexion auto
        try {
          const { data } = await api.post("/auth/navixy-sso", { session_key: NAVIXY_SSO_KEY });
          if (!cancelled) {
            setUser(data.user);
            setLoading(false);
          }
          return;
        } catch (e) {
          console.debug("[AuthContext] SSO Navixy échoué, fallback login classique:", e);
        }
      }
      try {
        const { data } = await api.get("/auth/me");
        if (!cancelled) setUser(data.user);
      } catch (e) {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  async function login(email, password) {
    try {
      const { data } = await api.post("/auth/login", { email, password });
      setUser(data.user);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: formatApiErrorDetail(e.response?.data?.detail) || e.message };
    }
  }

  async function endImpersonation() {
    try {
      await api.post("/auth/impersonate/end");
    } catch (e) {
      console.debug("[AuthContext] impersonate/end failed (session cleared anyway):", e);
    }
    sessionStorage.removeItem(IMP_TOKEN_KEY);
    setImpersonationEnded(true);
    window.close();
  }

  async function logout() {
    // En mode aperçu : ne JAMAIS détruire la session admin (les cookies sont partagés entre onglets)
    if (sessionStorage.getItem(IMP_TOKEN_KEY)) {
      return endImpersonation();
    }
    try {
      await api.post("/auth/logout");
    } catch (e) {
      console.debug("[AuthContext] logout request failed (will still clear local state):", e);
    }
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{
      user, loading, login, logout,
      endImpersonation, impersonationEnded, impersonationError,
      clearImpersonationError: () => setImpersonationError(null),
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
