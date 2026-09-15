import { canCalibrate, syncDisabled, canAttemptCalibration } from "../vehicleOdometerLogic";

// UI FAIL-CLOSED : bouton actif ⇔ can_calibrate === true. Aucun fallback.
describe("vehicleOdometer fail-closed logic", () => {
  test("can_calibrate === true => autorisé", () => {
    expect(canCalibrate({ can_calibrate: true })).toBe(true);
    expect(canAttemptCalibration({ can_calibrate: true })).toBe(true);
  });

  test("can_calibrate === false => refusé", () => {
    expect(canCalibrate({ can_calibrate: false })).toBe(false);
  });

  test("can_calibrate null / undefined / absent => refusé", () => {
    expect(canCalibrate({ can_calibrate: null })).toBe(false);
    expect(canCalibrate({ can_calibrate: undefined })).toBe(false);
    expect(canCalibrate({})).toBe(false);            // propriété absente
    expect(canCalibrate(null)).toBe(false);          // état null (erreur GET)
    expect(canCalibrate(undefined)).toBe(false);
  });

  test("device_write_enabled seul NE suffit PAS (pas de fallback)", () => {
    expect(canCalibrate({ device_write_enabled: true })).toBe(false);
    expect(canCalibrate({ device_write_enabled: true, can_calibrate: false })).toBe(false);
    expect(canCalibrate({ device_write_enabled: true, can_calibrate: null })).toBe(false);
  });

  test("valeur non booléenne 'true' (string) => refusé (strict ===)", () => {
    expect(canCalibrate({ can_calibrate: "true" })).toBe(false);
    expect(canCalibrate({ can_calibrate: 1 })).toBe(false);
  });

  describe("syncDisabled", () => {
    const okState = { can_calibrate: true };
    test("désactivé si gate refuse (même avec valeur saisie)", () => {
      expect(syncDisabled({ state: { can_calibrate: false }, submitting: false, dashKm: "139620" })).toBe(true);
      expect(syncDisabled({ state: {}, submitting: false, dashKm: "139620" })).toBe(true);
      expect(syncDisabled({ state: null, submitting: false, dashKm: "139620" })).toBe(true);
    });
    test("désactivé si soumission en cours", () => {
      expect(syncDisabled({ state: okState, submitting: true, dashKm: "139620" })).toBe(true);
    });
    test("désactivé si aucune valeur saisie", () => {
      expect(syncDisabled({ state: okState, submitting: false, dashKm: "" })).toBe(true);
    });
    test("actif uniquement si gate OK + valeur + pas de soumission", () => {
      expect(syncDisabled({ state: okState, submitting: false, dashKm: "139620" })).toBe(false);
    });
    test("appel sans arguments => désactivé (défense)", () => {
      expect(syncDisabled()).toBe(true);
    });
  });
});
