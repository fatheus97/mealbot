import { describe, it, expect, beforeEach } from "vitest";
import { clearSessionHints, storeSessionHints, SESSION_HINT_KEYS } from "./sessionHints";

const FULL = {
  id: 7,
  email: "a@b.com",
  onboarding_completed: true,
  is_demo: false,
  is_admin: true,
  subscription_status: "active",
  current_period_end: "2026-09-01T00:00:00Z",
  cancel_at_period_end: true,
  is_subscribed: true,
  is_comped: true,
};

describe("sessionHints", () => {
  beforeEach(() => window.localStorage.clear());

  it("writes the identity + billing hints for a full profile", () => {
    storeSessionHints(FULL, false);
    expect(localStorage.getItem("mealbot_user_id")).toBe("7");
    expect(localStorage.getItem("mealbot_user_email")).toBe("a@b.com");
    expect(localStorage.getItem("mealbot_subscription_status")).toBe("active");
    expect(localStorage.getItem("mealbot_current_period_end")).toBe("2026-09-01T00:00:00Z");
    expect(localStorage.getItem("mealbot_cancel_at_period_end")).toBe("true");
    expect(localStorage.getItem("mealbot_is_subscribed")).toBe("true");
    expect(localStorage.getItem("mealbot_is_comped")).toBe("true");
    expect(localStorage.getItem("mealbot_is_admin")).toBe("true");
    expect(localStorage.getItem("mealbot_onboarding")).toBe("true");
  });

  it("uses the explicit demoFlag, not the profile's is_demo", () => {
    // The server's value is resolved by the caller; passing it separately is
    // what lets bootstrap/login/demo agree on one source of truth.
    storeSessionHints({ ...FULL, is_demo: false }, true);
    expect(localStorage.getItem("mealbot_is_demo")).toBe("true");
  });

  it("defaults a missing subscription_status to 'none' rather than writing undefined", () => {
    storeSessionHints({ id: 1, email: "x@y.com" }, false);
    expect(localStorage.getItem("mealbot_subscription_status")).toBe("none");
  });

  it("REMOVES falsy flags instead of leaving a stale hint from a previous session", () => {
    // The trap this guards: log in as an admin, log in as a non-admin, and the
    // stale "true" would make the SPA paint an admin UI it shouldn't.
    storeSessionHints(FULL, true);
    storeSessionHints(
      { id: 2, email: "plain@user.com", is_admin: false, is_subscribed: false },
      false,
    );
    expect(localStorage.getItem("mealbot_is_admin")).toBeNull();
    expect(localStorage.getItem("mealbot_is_demo")).toBeNull();
    expect(localStorage.getItem("mealbot_is_subscribed")).toBeNull();
    expect(localStorage.getItem("mealbot_is_comped")).toBeNull();
    expect(localStorage.getItem("mealbot_current_period_end")).toBeNull();
    expect(localStorage.getItem("mealbot_cancel_at_period_end")).toBeNull();
    expect(localStorage.getItem("mealbot_onboarding")).toBeNull();
    // …but identity is overwritten, not dropped.
    expect(localStorage.getItem("mealbot_user_id")).toBe("2");
  });

  it("clearSessionHints removes every key the writer can set", () => {
    storeSessionHints(FULL, true);
    clearSessionHints();
    for (const key of SESSION_HINT_KEYS) {
      expect(localStorage.getItem(key)).toBeNull();
    }
  });
});
