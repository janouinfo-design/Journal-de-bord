import { createContext, useContext, useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";

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

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);     // user object | null
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // SSO Navixy : si l'iframe a été chargée avec ?session_key=..., connexion auto
      if (NAVIXY_SSO_KEY) {
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

  async function logout() {
    try {
      await api.post("/auth/logout");
    } catch (e) {
      console.debug("[AuthContext] logout request failed (will still clear local state):", e);
    }
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
