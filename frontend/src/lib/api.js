import axios from "axios";

const BASE = process.env.REACT_APP_BACKEND_URL;
export const API_URL = `${BASE}/api`;

export const api = axios.create({
  baseURL: API_URL,
  withCredentials: true,
});

// Global 401 handler — fires the redirect once, lets callers handle their own errors.
let _redirecting = false;
api.interceptors.response.use(
  (resp) => resp,
  (err) => {
    const status = err?.response?.status;
    const url = err?.config?.url || "";
    // /auth/me 401 is expected (= not logged in); don't redirect from it
    if (status === 401 && !url.includes("/auth/me") && !url.includes("/auth/login")) {
      if (!_redirecting && typeof window !== "undefined") {
        _redirecting = true;
        if (window.location.pathname !== "/login") {
          window.location.replace("/login");
        }
      }
    }
    return Promise.reject(err);
  },
);

export function formatApiErrorDetail(detail) {
  if (detail == null) return "Une erreur est survenue. Veuillez réessayer.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function fmtKm(v) {
  if (v == null) return "—";
  return v.toLocaleString("fr-CH", { maximumFractionDigits: 1 }).replace(/,/g, "'") + " km";
}

export function fmtPct(v) {
  if (v == null) return "—";
  return `${v.toFixed(1)} %`;
}

export function fmtDateTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-CH", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch (e) {
    return iso;
  }
}

export function fmtDuration(min) {
  if (min == null) return "—";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h > 0 ? `${h}h ${m}min` : `${m} min`;
}

export function fmtAmount(v, currency = "CHF") {
  if (v == null || isNaN(v)) return "—";
  const n = Number(v).toLocaleString("fr-CH", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).replace(/,/g, "'");
  return `${n} ${currency}`;
}

export function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("fr-CH", {
      day: "2-digit", month: "2-digit", year: "numeric",
    });
  } catch (e) { return iso; }
}
