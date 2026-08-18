/* Domain enums for the Fines module — mirror of /backend/app/routes/fines.py */

export const FINE_STATUSES = [
  { value: "received",            label: "Reçue",                 tone: "neutral" },
  { value: "to_analyze",          label: "À analyser",            tone: "warning" },
  { value: "driver_to_identify",  label: "Conducteur à identifier", tone: "warning" },
  { value: "awaiting_driver",     label: "En attente chauffeur",  tone: "warning" },
  { value: "disputed",            label: "Contestée",             tone: "warning" },
  { value: "to_pay",              label: "À payer",               tone: "danger"  },
  { value: "paid",                label: "Payée",                 tone: "success" },
  { value: "recharged",           label: "Refacturée",            tone: "success" },
  { value: "closed",              label: "Clôturée",              tone: "success" },
  { value: "cancelled",           label: "Annulée",               tone: "muted"   },
];

export const FINE_STATUS_MAP = Object.fromEntries(FINE_STATUSES.map(s => [s.value, s]));

export const STATUS_TONE_CLASS = {
  // Red — to_pay, en retard
  danger:  "bg-rose-50 text-rose-700 border-rose-200",
  // Orange — to_analyze, disputed, awaiting…
  warning: "bg-amber-50 text-amber-700 border-amber-200",
  // Green — paid, closed, recharged
  success: "bg-emerald-50 text-emerald-700 border-emerald-200",
  // Gray — cancelled
  muted:   "bg-slate-100 text-slate-600 border-slate-200",
  // Default — received
  neutral: "bg-slate-50 text-slate-700 border-slate-200",
};

export const INFRACTION_TYPES = [
  { value: "speeding",       label: "Excès de vitesse" },
  { value: "parking",        label: "Stationnement" },
  { value: "red_light",      label: "Feu rouge" },
  { value: "toll",           label: "Péage" },
  { value: "forbidden_zone", label: "Zone interdite" },
  { value: "phone",          label: "Téléphone" },
  { value: "seatbelt",       label: "Ceinture" },
  { value: "other",          label: "Autre" },
];

export const INFRACTION_LABEL = Object.fromEntries(INFRACTION_TYPES.map(t => [t.value, t.label]));

export const PRIORITIES = [
  { value: "low",     label: "Basse" },
  { value: "normal",  label: "Normale" },
  { value: "high",    label: "Haute" },
  { value: "urgent",  label: "Urgente" },
];

export const PRIORITY_LABEL = Object.fromEntries(PRIORITIES.map(p => [p.value, p.label]));

/** Determine if the fine is in arrears (due_date passed and not paid/cancelled). */
export function isOverdue(fine, now = new Date()) {
  if (!fine?.due_date) return false;
  if (["paid", "recharged", "closed", "cancelled"].includes(fine.status)) return false;
  try {
    return new Date(fine.due_date) < now;
  } catch { return false; }
}
