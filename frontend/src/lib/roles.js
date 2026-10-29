export const ROLE_LABEL = {
  admin: "Admin",
  manager: "Gestionnaire",
  office: "Office (administratif)",
  driver: "Chauffeur",
  lecture_seule: "Lecture seule",
  superadmin: "Super Admin",
};

// Rôles attribuables à un utilisateur d'entreprise (ordre d'affichage des sélecteurs).
export const TENANT_ROLE_OPTIONS = [
  { value: "admin", label: "Admin" },
  { value: "manager", label: "Gestionnaire" },
  { value: "office", label: "Office (administratif)" },
  { value: "driver", label: "Chauffeur" },
  { value: "lecture_seule", label: "Lecture seule" },
];

export const ROLE_HINT = {
  admin: "Accès complet à l'entreprise, gestion des utilisateurs et des permissions.",
  manager: "Pilotage de la flotte : journal, classification, conducteurs, rapprochements.",
  office: "Administratif / comptabilité : carburant, cartes, amendes, décomptes — sans positions GPS.",
  driver: "Ses propres trajets, transactions et amendes ; console chauffeur.",
  lecture_seule: "Consultation uniquement, aucune écriture.",
};
