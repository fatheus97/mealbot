import { describe, it, expect, vi } from "vitest";
import {
  createCheckoutSession,
  createPortalSession,
  generateRecipe,
  PaywallError,
} from "./api";
import type { SingleRecipeRequest } from "./types";

const recipeReq: SingleRecipeRequest = {
  meal_type: "main_course",
  diet_type: null,
  people_count: 2,
  taste_preferences: [],
  avoid_ingredients: [],
  ingredients_to_use: [],
  stock_only: false,
  note: null,
};

function mockFetch(resp: Partial<Response> & { json?: () => Promise<unknown> }) {
  // Global setup.ts installs localStorage via vi.stubGlobal + restoreAllMocks in
  // afterEach, so we re-stub fetch per test and don't unstub globals ourselves
  // (unstubAllGlobals would nuke that shared localStorage stub).
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resp as unknown as Response));
}

describe("402 paywall handling", () => {
  it("generateRecipe throws PaywallError and dispatches mealbot:paywall on 402", async () => {
    mockFetch({ ok: false, status: 402, text: () => Promise.resolve(""), json: () => Promise.resolve({}) });
    const onPaywall = vi.fn();
    window.addEventListener("mealbot:paywall", onPaywall);
    try {
      await expect(generateRecipe(recipeReq)).rejects.toBeInstanceOf(PaywallError);
      expect(onPaywall).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener("mealbot:paywall", onPaywall);
    }
  });
});

describe("createCheckoutSession", () => {
  it("returns the Stripe url on success", async () => {
    mockFetch({ ok: true, status: 200, json: () => Promise.resolve({ url: "https://checkout.stripe/x" }) });
    await expect(createCheckoutSession()).resolves.toBe("https://checkout.stripe/x");
  });

  it("surfaces the backend detail on 503", async () => {
    mockFetch({ ok: false, status: 503, json: () => Promise.resolve({ detail: "Billing is not available." }) });
    await expect(createCheckoutSession()).rejects.toThrow("Billing is not available.");
  });
});

describe("createPortalSession", () => {
  it("returns the portal url on success", async () => {
    mockFetch({ ok: true, status: 200, json: () => Promise.resolve({ url: "https://portal.stripe/y" }) });
    await expect(createPortalSession()).resolves.toBe("https://portal.stripe/y");
  });

  it("surfaces the backend detail on 400 (no customer yet)", async () => {
    mockFetch({ ok: false, status: 400, json: () => Promise.resolve({ detail: "No billing account yet — subscribe first." }) });
    await expect(createPortalSession()).rejects.toThrow(/No billing account yet/);
  });
});
