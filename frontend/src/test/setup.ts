import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { __resetAttributionForTests } from '../utils/attribution';
import { __resetMediaForTests } from './media';

// Node 22+ ships native Web Storage globals (`localStorage`/`sessionStorage`) that
// vitest's jsdom environment leaves unconfigured, so the bare globals resolve to
// `undefined` under Node 26 (they were provided implicitly under Node 24). Install an
// in-memory Storage so the test setup and zustand's persist middleware behave
// consistently regardless of the Node version running the suite.
function createMemoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, String(value));
    },
  } as Storage;
}

vi.stubGlobal('localStorage', createMemoryStorage());
vi.stubGlobal('sessionStorage', createMemoryStorage());

// jsdom does no layout, so it does not implement scrollIntoView, and a component
// that calls it on mount throws. Without this, such a test only passed when an
// earlier test in the file had stubbed the prototype and never put it back.
// A test that asserts on the call should `vi.spyOn(Element.prototype,
// 'scrollIntoView')`; the restoreAllMocks below hands this no-op back.
Element.prototype.scrollIntoView = () => {};

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  // Attribution is held in a MODULE-level variable now (not localStorage), so
  // `localStorage.clear()` no longer resets it and a capture in one test would
  // otherwise leak into the next test's register payload within the same file.
  __resetAttributionForTests();
  // Reset any matchMedia mock (see test-utils setMobileViewport /
  // setColorScheme) so a mobile or dark-mode test can't leak into the next
  // test's defaults (desktop, light). The mock answers from module state, so
  // dropping the global alone would leave that state dirty for the next install.
  __resetMediaForTests();
  Reflect.deleteProperty(window, 'matchMedia');
});
