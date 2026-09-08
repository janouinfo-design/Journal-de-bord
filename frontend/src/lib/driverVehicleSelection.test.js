import { resolveVehicleSelection, storageKey, STORAGE_PREFIX } from "./driverVehicleSelection";

const V = (id) => ({ id, plate: `PL-${id}`, model: `M-${id}` });

describe("Console Chauffeur — résolution de sélection véhicule (T1–T10)", () => {
  test("T1 — liste vide : aucune sélection, aucun fallback", () => {
    const r = resolveVehicleSelection({ vehicles: [], defaultVehicleId: null, storedId: null, currentId: null });
    expect(r.selectedId).toBeNull();
    expect(r.revoked).toBe(false);
  });

  test("T2 — un seul véhicule : auto-sélection", () => {
    const r = resolveVehicleSelection({ vehicles: [V("a")], defaultVehicleId: null, storedId: null, currentId: null });
    expect(r.selectedId).toBe("a");
  });

  test("T3 — default backend présent : auto-sélection du default", () => {
    const r = resolveVehicleSelection({ vehicles: [V("a"), V("b")], defaultVehicleId: "b", storedId: null, currentId: null });
    expect(r.selectedId).toBe("b");
  });

  test("T4 — localStorage valide : réutilisé (priorité sur le default)", () => {
    const r = resolveVehicleSelection({ vehicles: [V("a"), V("b")], defaultVehicleId: "b", storedId: "a", currentId: null });
    expect(r.selectedId).toBe("a");
    expect(r.purgeStored).toBe(false);
  });

  test("T5 — localStorage invalide : purgé, jamais réutilisé", () => {
    const r = resolveVehicleSelection({ vehicles: [V("a"), V("b")], defaultVehicleId: null, storedId: "zz", currentId: null });
    expect(r.purgeStored).toBe(true);
    expect(r.selectedId).toBeNull();
  });

  test("T6 — sélection active toujours autorisée : conservée (priorité max)", () => {
    const r = resolveVehicleSelection({ vehicles: [V("a"), V("b")], defaultVehicleId: "b", storedId: "b", currentId: "a" });
    expect(r.selectedId).toBe("a");
    expect(r.revoked).toBe(false);
  });

  test("T7 — sélection active révoquée : désélection signalée (revoked)", () => {
    const r = resolveVehicleSelection({ vehicles: [V("b"), V("c")], defaultVehicleId: null, storedId: null, currentId: "a" });
    expect(r.revoked).toBe(true);
    expect(r.selectedId).toBeNull();
  });

  test("T8 — default hors liste (défense) : non sélectionné", () => {
    const r = resolveVehicleSelection({ vehicles: [V("a"), V("b")], defaultVehicleId: "zz", storedId: null, currentId: null });
    expect(r.selectedId).toBeNull();
  });

  test("T9 — plusieurs véhicules sans stored ni default : aucune sélection arbitraire", () => {
    const r = resolveVehicleSelection({ vehicles: [V("a"), V("b"), V("c")], defaultVehicleId: null, storedId: null, currentId: null });
    expect(r.selectedId).toBeNull();
  });

  test("T10 — stored invalide + default valide : purge puis default sélectionné", () => {
    const r = resolveVehicleSelection({ vehicles: [V("a"), V("b")], defaultVehicleId: "a", storedId: "zz", currentId: null });
    expect(r.purgeStored).toBe(true);
    expect(r.selectedId).toBe("a");
  });

  test("clé de stockage : scopée par utilisateur", () => {
    expect(storageKey("u1")).toBe(`${STORAGE_PREFIX}u1`);
    expect(storageKey(null)).toBe(`${STORAGE_PREFIX}anon`);
  });
});
