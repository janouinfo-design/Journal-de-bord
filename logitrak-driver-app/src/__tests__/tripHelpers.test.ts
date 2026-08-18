/**
 * Tests des helpers de trajet : données incomplètes -> N/A, badges PRO/PRIVÉ/À classer.
 */
import {
  formatDate,
  formatTime,
  formatDuration,
  formatDistance,
  classificationBadge,
  tripRouteLabel,
} from '@/utils/trip';

describe('trip helpers', () => {
  it('formatDistance : N/A si absent, sinon km', () => {
    expect(formatDistance(null)).toBe('N/A');
    expect(formatDistance(undefined)).toBe('N/A');
    expect(formatDistance(7.8)).toBe('7.8 km');
  });

  it('formatDuration : N/A si absent, minutes ou heures', () => {
    expect(formatDuration(null)).toBe('N/A');
    expect(formatDuration(8)).toBe('8 min');
    expect(formatDuration(75)).toBe('1 h 15');
  });

  it('formatDate / formatTime : N/A si absent', () => {
    expect(formatDate(null)).toBe('N/A');
    expect(formatTime(undefined)).toBe('N/A');
  });

  it('classificationBadge : PRO / PRIVÉ / À classer', () => {
    expect(classificationBadge('professional').label).toBe('PRO');
    expect(classificationBadge('personal').label).toBe('PRIVÉ');
    expect(classificationBadge(null).label).toBe('À classer');
  });

  it('tripRouteLabel : libellés de repli si adresses absentes', () => {
    const r = tripRouteLabel({ id: 'x' } as any);
    expect(r.from).toMatch(/inconnue/i);
    expect(r.to).toMatch(/inconnue/i);
  });
});
