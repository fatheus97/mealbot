import { renderHook, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useIsMobile } from "./useIsMobile";

type Listener = () => void;

/** Install a controllable window.matchMedia mock; returns a setter that flips
 *  `matches` and notifies subscribers (simulating a viewport crossing). */
function installMatchMedia(initialMatches: boolean) {
  let matches = initialMatches;
  const listeners = new Set<Listener>();
  const mql = {
    get matches() {
      return matches;
    },
    media: "(max-width: 640px)",
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

describe("useIsMobile", () => {
  it("returns false on a wide viewport", () => {
    installMatchMedia(false);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });

  it("returns true on a phone-sized viewport", () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it("reacts to a viewport crossing (rotation / resize)", () => {
    const mm = installMatchMedia(false);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
    act(() => mm.setMatches(true));
    expect(result.current).toBe(true);
    act(() => mm.setMatches(false));
    expect(result.current).toBe(false);
  });

  it("falls back to false when matchMedia is unavailable (SSR / old jsdom)", () => {
    Reflect.deleteProperty(window, "matchMedia");
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });
});
