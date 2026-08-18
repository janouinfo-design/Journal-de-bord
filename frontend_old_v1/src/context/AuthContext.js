import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { login as apiLogin, decodeJwt } from '../services/api';
import { saveToken, getToken, clearAuth, saveUser, getUser } from '../services/storage';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(null);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const t = await getToken();
      const u = await getUser();
      if (t) {
        setToken(t);
        setUser(u || decodeJwt(t));
      }
      setLoading(false);
    })();
  }, []);

  const signIn = useCallback(async (email, password) => {
    const { token: jwt, raw } = await apiLogin(email, password);
    const decoded = decodeJwt(jwt) || {};
    const u = {
      email: raw?.user?.email || raw?.email || decoded?.email || email,
      name: raw?.user?.name || raw?.name || decoded?.name || decoded?.sub || null,
      company: raw?.user?.company || raw?.company || decoded?.company || decoded?.tenant || null,
      role: raw?.user?.role || decoded?.role || null,
    };
    await saveToken(jwt);
    await saveUser(u);
    setToken(jwt);
    setUser(u);
    return u;
  }, []);

  const signOut = useCallback(async () => {
    await clearAuth();
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ token, user, loading, signIn, signOut, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth doit être utilisé dans AuthProvider');
  return ctx;
}
