export const MATCH_STATUS = {
  auto_matched:   { label: "Rapproché auto",     cls: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  matched_review: { label: "Contrôle recommandé", cls: "bg-amber-100 text-amber-700 border-amber-200" },
  unmatched:      { label: "À vérifier",          cls: "bg-rose-100 text-rose-700 border-rose-200" },
  manual:         { label: "Attribué manuellement", cls: "bg-sky-100 text-sky-700 border-sky-200" },
};

export const CARD_STATUS = {
  active:    { label: "Active",    cls: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  suspended: { label: "Suspendue", cls: "bg-amber-100 text-amber-700 border-amber-200" },
  expired:   { label: "Expirée",   cls: "bg-slate-100 text-slate-500 border-slate-200" },
  blocked:   { label: "Bloquée",   cls: "bg-rose-100 text-rose-700 border-rose-200" },
  replaced:  { label: "Remplacée", cls: "bg-slate-100 text-slate-500 border-slate-200" },
};

export const PRODUCT_LABEL = {
  diesel: "Diesel", essence: "Essence", adblue: "AdBlue", electric: "Électrique / recharge", other: "Autre",
};

export const SOURCE_LABEL = { csv: "CSV", xlsx: "XLSX", manual: "Manuel", api: "API" };

export const CLASSIFICATION_LABEL = {
  professional: "Professionnel", personal: "Privé", mixed: "Mixte", unclassified: "Non classé",
};

export const ASSIGNMENT_TYPE_LABEL = {
  vehicle: "Véhicule", driver: "Chauffeur", pool: "Carte de pool", other: "Autre",
};

export const FX_STATUS = {
  pending:    { label: "Conversion en attente", cls: "bg-amber-100 text-amber-700 border-amber-200" },
  converted:  { label: "Converti (BCE)",        cls: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  not_needed: { label: "CHF",                   cls: "bg-slate-100 text-slate-500 border-slate-200" },
};

export const ROW_STATUS = {
  ok:              { label: "Valide",             cls: "bg-emerald-100 text-emerald-700" },
  duplicate:       { label: "Doublon probable",   cls: "bg-amber-100 text-amber-700" },
  unknown_card:    { label: "Carte inconnue",     cls: "bg-sky-100 text-sky-700" },
  invalid:         { label: "Invalide",           cls: "bg-rose-100 text-rose-700" },
  amount_mismatch: { label: "Montant incohérent", cls: "bg-orange-100 text-orange-700" },
  pending:         { label: "En attente",         cls: "bg-slate-100 text-slate-500" },
};

export function fmtAmount(v, currency = "CHF") {
  if (v == null) return "—";
  return `${Number(v).toFixed(2)} ${currency}`;
}

export function fmtQty(v, unit = "L") {
  if (v == null) return "—";
  return `${Number(v).toFixed(2)} ${unit}`;
}
