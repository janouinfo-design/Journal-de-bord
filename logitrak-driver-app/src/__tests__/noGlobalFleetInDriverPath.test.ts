/**
 * Garde statique : le parcours chauffeur n'utilise JAMAIS la flotte globale du tenant
 * (/api/livre/vehicles) ni l'ancien endpoint par affectations (/driver/my-vehicles).
 * La seule source autorisée est GET /api/livre/driver/vehicles.
 */
import * as fs from 'fs';
import * as path from 'path';

const SRC_DIR = path.join(__dirname, '..');

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(p));
    else out.push(p);
  }
  return out;
}

describe('périmètre véhicules — garde anti-régression', () => {
  const sources = walk(SRC_DIR).filter(
    (f) => /\.(ts|tsx)$/.test(f) && !f.includes('__tests__'),
  );

  it('aucun fichier source n’appelle la flotte globale /api/livre/vehicles', () => {
    const offenders = sources.filter((f) =>
      fs.readFileSync(f, 'utf8').includes("/api/livre/vehicles"),
    );
    expect(offenders).toEqual([]);
  });

  it('aucun fichier source n’appelle l’ancien endpoint /driver/my-vehicles', () => {
    const offenders = sources.filter((f) =>
      fs.readFileSync(f, 'utf8').includes('/driver/my-vehicles'),
    );
    expect(offenders).toEqual([]);
  });

  it('la source d’autorité /driver/vehicles est bien utilisée', () => {
    const users = sources.filter((f) =>
      fs.readFileSync(f, 'utf8').includes('/api/livre/driver/vehicles'),
    );
    expect(users.length).toBeGreaterThan(0);
  });
});
