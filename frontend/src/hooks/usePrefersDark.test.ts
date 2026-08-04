import { renderHook, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { usePrefersDark } from "./usePrefersDark";

type Listener = () => void;

/** Install a controllable window.matchMedia mock; returns a setter that flips
 *  `matches` and notifies subscribers (simulating the user changing their OS
 *  theme while the tab is open). */
function installMatchMedia(initialMatches: boolean) {
  let matches = initialMatches;
  const listeners = new Set<Listener>();
  const mql = {
    get matches() {
      return matches;
    },
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: (_type: string, cb: Listener) => listeners.add(cb),
    removeEventListener: (_type: string, cb: Listener) => listeners.delete(cb),
    addListener: (cb: Listener) => listeners.add(cb),
    removeListener: (cb: Listener) => listeners.delete(cb),
    dispatchEvent: () => true,
  };
  window.matchMedia = vi.fn().mockReturnValue(mql) as unknown as typeof window.matchMedia;
  return {
    setMatches(v: boolean) {
      matches = v;
      listeners.forEach((cb) => cb());
    },
  };
}

afterEach(() => {
  Reflect.deleteProperty(window, "matchMedia");
});

describe("usePrefersDark", () => {
  it("returns false when the OS asks for light", () => {
    installMatchMedia(false);
    const { result } = renderHook(() => usePrefersDark());
    expect(result.current).toBe(false);
  });

  it("returns true when the OS asks for dark", () => {
    installMatchMedia(true);
    const { result } = renderHook(() => usePrefersDark());
    expect(result.current).toBe(true);
  });

  it("reacts to the user flipping their system theme mid-session", () => {
    const mm = installMatchMedia(false);
    const { result } = renderHook(() => usePrefersDark());
    expect(result.current).toBe(false);
    act(() => mm.setMatches(true));
    expect(result.current).toBe(true);
    act(() => mm.setMatches(false));
    expect(result.current).toBe(false);
  });

  it("falls back to light when matchMedia is unavailable (SSR / old jsdom)", () => {
    Reflect.deleteProperty(window, "matchMedia");
    const { result } = renderHook(() => usePrefersDark());
    expect(result.current).toBe(false);
  });
});
