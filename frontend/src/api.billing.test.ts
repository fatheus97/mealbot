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

describe("generateRecipe error surfacing", () => {
  it("surfaces the backend fail-closed allergen detail on 422 (not the raw body)", async () => {
    mockFetch({
      ok: false,
      status: 422,
      json: () => Promise.resolve({
        detail:
          "We couldn't generate a meal that avoids Milk (incl. lactose). Very " +
          "restrictive combinations can be hard to satisfy — try removing an " +
          "allergen or diet and generating again.",
      }),
    });
    await expect(generateRecipe(recipeReq)).rejects.toThrow(/try removing an allergen/i);
  });

  it("falls back to a friendly message for a Pydantic list detail", async () => {
    // A *validation* 422 carries a LIST detail, not a string — extractErrorDetail
    // must not dump it raw; it falls through to the generic message + status.
    mockFetch({
      ok: false,
      status: 422,
      json: () => Promise.resolve({ detail: [{ msg: "invalid" }] }),
    });
    await expect(generateRecipe(recipeReq)).rejects.toThrow(
      "Recipe generation failed. Please try again. (422)",
    );
  });
});

describe("structured error details (the usage-cap 429)", () => {
  const capDetail = {
    user_detail:
      "You have used your €2.00 of AI generation for this month. Your allowance " +
      "resets on 1 September 2026. New plans, recipes and receipt scanning are " +
      "paused until then; everything you have already saved is unaffected.",
    code: "usage_cap_reached",
    tier: "paid",
    cap_eur: 2.0,
    used_eur: 2.03,
    remaining_eur: 0.0,
    reset_at: "2026-09-01T00:00:00",
  };

  it("shows user_detail instead of 'Please try again'", async () => {
    // The bug: an OBJECT detail failed the `typeof === "string"` test and fell
    // through to the generic fallback, so the one error where retrying can
    // never work was the one that told the user to retry — for up to a month.
    mockFetch({ ok: false, status: 429, json: () => Promise.resolve({ detail: capDetail }) });
    await expect(generateRecipe(recipeReq)).rejects.toThrow(/allowance resets on 1 September 2026/);
  });

  it("never leaks the machine-readable siblings into the message", async () => {
    mockFetch({ ok: false, status: 429, json: () => Promise.resolve({ detail: capDetail }) });
    const err = await generateRecipe(recipeReq).then(() => null, (e: unknown) => e);
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).not.toMatch(/usage_cap_reached|cap_eur|reset_at|\{/);
  });

  it("falls back when an object detail carries no user_detail", async () => {
    // Any future structured detail that forgets the human string must degrade to
    // the generic message, never to "[object Object]".
    mockFetch({
      ok: false,
      status: 429,
      json: () => Promise.resolve({ detail: { code: "something_new" } }),
    });
    await expect(generateRecipe(recipeReq)).rejects.toThrow(
      "Recipe generation failed. Please try again. (429)",
    );
  });

  it("ignores a non-string user_detail", async () => {
    mockFetch({
      ok: false,
      status: 429,
      json: () => Promise.resolve({ detail: { user_detail: { nested: "no" } } }),
    });
    await expect(generateRecipe(recipeReq)).rejects.toThrow(
      "Recipe generation failed. Please try again. (429)",
    );
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
