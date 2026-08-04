import { describe, it, expect } from 'vitest';
import { contrastRatio, wcagAAFloor, checkText } from './contrast';
import {
  SURFACE,
  NOTICE_OK_COLOR,
  NOTICE_ERROR_COLOR,
  MUTED_COLOR,
} from '../components/PantryStaples';

describe('contrast maths', () => {
  it('agrees with the WCAG reference values', () => {
    // Pins the formula itself. Without these, a bug in `luminance` would make
    // every assertion below pass for the wrong reason.
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5);
    expect(contrastRatio('#ffffff', '#ffffff')).toBeCloseTo(1, 5);
    expect(contrastRatio('#767676', '#ffffff')).toBeCloseTo(4.54, 1);
  });

  it('is symmetric — foreground vs background role does not matter', () => {
    // The exact reasoning that made #16a34a a bug twice: it was fixed as a
    // background and left as a foreground, as if the ratio depended on which.
    expect(contrastRatio('#15803d', '#ffffff')).toBeCloseTo(
      contrastRatio('#ffffff', '#15803d'),
      10,
    );
  });

  it('only grants the 3:1 large-text floor to genuinely large text', () => {
    expect(wcagAAFloor(13.6)).toBe(4.5);
    expect(wcagAAFloor(16, 700)).toBe(4.5); // bold but under 18.66px
    expect(wcagAAFloor(18.66, 700)).toBe(3);
    expect(wcagAAFloor(24)).toBe(3);
  });
});

describe('pantry staples colours', () => {
  // These are checked as CONSTANTS rather than through the DOM on purpose. The
  // notice colours only render after a save or a failure, so a
  // getComputedStyle sweep of the open modal cannot see them — which is exactly
  // how #16a34a survived one, at 3.29:1, while the sweep reported "nothing
  // below AA".
  const cases: [string, string][] = [
    ['success notice', NOTICE_OK_COLOR],
    ['error notice', NOTICE_ERROR_COLOR],
    ['muted help text', MUTED_COLOR],
  ];

  for (const [name, color] of cases) {
    it(`${name} meets WCAG AA on the modal surface`, () => {
      const result = checkText(color, SURFACE, 13.6);
      expect(result).toMatchObject({ passes: true });
    });
  }

  it('the save button meets AA with the surface as its foreground', () => {
    // Inverted pair: white text on the green fill.
    expect(checkText(SURFACE, NOTICE_OK_COLOR, 14.4)).toMatchObject({ passes: true });
  });

  it('rejects the colour that shipped this bug', () => {
    // A negative control on the check itself. If this ever passes, the floor or
    // the maths has drifted and every assertion above is worthless.
    expect(checkText('#16a34a', SURFACE, 13.6).passes).toBe(false);
  });
});
