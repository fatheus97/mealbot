import { describe, it, expect, beforeEach, vi } from "vitest";
import { captureAttribution, __resetAttributionForTests } from "../utils/attribution";
import {
  landingDemo,
  landingLogin,
  landingRegister,
  passwordComplaint,
  validationMessage,
  LandingAuthError,
} from "./authApi";

// NB: deliberately no `vi.unstubAllGlobals()` here. src/test/setup.ts installs
// the whole `localStorage` global with vi.stubGlobal (Node 26's jsdom leaves it
// unconfigured), so unstubbing everything would delete localStorage itself and
// every assertion below would fail on `undefined.clear()`. Re-stubbing fetch per
// test is enough — vitest isolates globals per test FILE, so it can't leak out.

const PROFILE = { id: 5, email: "u@example.com", is_demo: false, is_admin: false };

describe("passwordComplaint", () => {
  it("mirrors each backend rule (length, upper, lower, digit)", () => {
    expect(passwordComplaint("Short1")).toMatch(/at least 8/i);
    expect(passwordComplaint(`${"A1a".repeat(50)}`)).toMatch(/at most 128/i);
    expect(passwordComplaint("lowercase123")).toMatch(/uppercase/i);
    expect(passwordComplaint("UPPERCASE123")).toMatch(/lowercase/i);
    expect(passwordComplaint("NoDigitsHere")).toMatch(/digit/i);
  });

  it("accepts a password satisfying all of them", () => {
    expect(passwordComplaint("TestPassword123")).toBeNull();
  });
});

describe("validationMessage", () => {
  it("extracts and tidies a FastAPI 422 detail", () => {
    expect(
      validationMessage({
        detail: [
          { type: "value_error", loc: ["password"], msg: "Value error, Password must contain at least one uppercase letter" },
        ],
      }),
    ).toBe("Password must contain at least one uppercase letter.");
  });

  it("returns null for shapes it can't read, so the caller falls back to neutral copy", () => {
    expect(validationMessage(null)).toBeNull();
    expect(validationMessage({})).toBeNull();
    expect(validationMessage({ detail: [] })).toBeNull();
    expect(validationMessage({ detail: "a string" })).toBeNull();
    expect(validationMessage({ detail: [{ msg: 42 }] })).toBeNull();
  });
});

function jsonResponse(body: unknown, ok = true): Response {
  return { ok, json: () => Promise.resolve(body) } as unknown as Response;
}

describe("landing authApi", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });

  describe("landingLogin", () => {
    it("posts credentials and stores the session hints on success", async () => {
      vi.mocked(fetch).mockResolvedValue(jsonResponse(PROFILE));
      const profile = await landingLogin("u@example.com", "pw");

      expect(profile.id).toBe(5);
      expect(localStorage.getItem("mealbot_user_id")).toBe("5");
      const [url, init] = vi.mocked(fetch).mock.calls[0];
      expect(url).toBe("/api/auth/login");
      expect(init).toMatchObject({ method: "POST", credentials: "include" });
      expect(JSON.parse(init!.body as string)).toEqual({
        email: "u@example.com",
        password: "pw",
      });
    });

    it("throws a friendly error and stores nothing on bad credentials", async () => {
      vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: "nope" }, false));
      await expect(landingLogin("u@example.com", "wrong")).rejects.toBeInstanceOf(
        LandingAuthError,
      );
      expect(localStorage.getItem("mealbot_user_id")).toBeNull();
    });

    it("throws a friendly error when the network is down", async () => {
      vi.mocked(fetch).mockRejectedValue(new TypeError("offline"));
      await expect(landingLogin("u@example.com", "pw")).rejects.toThrow(
        /check your credentials/i,
      );
    });

    it("rejects a 200 whose body isn't a usable profile rather than storing junk", async () => {
      vi.mocked(fetch).mockResolvedValue(jsonResponse({ unexpected: true }));
      await expect(landingLogin("u@example.com", "pw")).rejects.toBeInstanceOf(
        LandingAuthError,
      );
      expect(localStorage.getItem("mealbot_user_id")).toBeNull();
    });
  });

  describe("landingRegister", () => {
    it("registers then logs in, replaying stored attribution", async () => {
      // In-memory capture (no device storage -> no consent banner needed).
      __resetAttributionForTests();
      window.history.replaceState(null, "", "/?utm_source=google&utm_medium=cpc");
      captureAttribution();
      vi.mocked(fetch)
        .mockResolvedValueOnce(jsonResponse({ message: "created" })) // register
        .mockResolvedValueOnce(jsonResponse(PROFILE)); // auto-login

      await landingRegister("u@example.com", "longenough", true);

      const registerBody = JSON.parse(
        vi.mocked(fetch).mock.calls[0][1]!.body as string,
      );
      expect(registerBody).toMatchObject({
        email: "u@example.com",
        password: "longenough",
        utm_source: "google",
        utm_medium: "cpc",
      });
      expect(vi.mocked(fetch).mock.calls[1][0]).toBe("/api/auth/login");
      expect(localStorage.getItem("mealbot_user_id")).toBe("5");
    });

    it("uses neutral copy on a 409 so it never discloses that an email is taken", async () => {
      const resp = { ok: false, status: 409, json: () => Promise.resolve({ detail: "exists" }) };
      vi.mocked(fetch).mockResolvedValue(resp as unknown as Response);
      await expect(landingRegister("taken@example.com", "Longenough1", true)).rejects.toThrow(
        /registration failed/i,
      );
    });

    it("echoes the specific reason on a 422 instead of the useless generic message", async () => {
      const resp = {
        ok: false,
        status: 422,
        json: () =>
          Promise.resolve({
            detail: [{ msg: "Value error, Password must contain at least one digit" }],
          }),
      };
      vi.mocked(fetch).mockResolvedValue(resp as unknown as Response);
      await expect(landingRegister("u@example.com", "NoDigitsHere", true)).rejects.toThrow(
        /must contain at least one digit/i,
      );
    });

    it("tells the user the account EXISTS when only the follow-up login fails", async () => {
      // Getting this wrong sends them back to re-register into a 409.
      vi.mocked(fetch)
        .mockResolvedValueOnce(jsonResponse({ message: "created" }))
        .mockResolvedValueOnce(jsonResponse({ detail: "nope" }, false));

      await expect(landingRegister("u@example.com", "longenough", true)).rejects.toThrow(
        /account created/i,
      );
    });
  });

  describe("landingDemo", () => {
    it("starts a demo session and marks the hint as a demo account", async () => {
      vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...PROFILE, is_demo: true }));
      await landingDemo();
      expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/auth/demo");
      expect(localStorage.getItem("mealbot_is_demo")).toBe("true");
    });

    it("throws a friendly error when demo mode is off (404)", async () => {
      vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: "disabled" }, false));
      await expect(landingDemo()).rejects.toThrow(/could not start the demo/i);
    });
  });
});
