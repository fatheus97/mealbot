import { describe, it, expect, beforeEach, afterEach } from "vitest";
import {
  captureAttribution,
  getStoredAttribution,
  __resetAttributionForTests,
} from "./attribution";

function setUrl(search: string) {
  window.history.replaceState(null, "", `/${search}`);
}

function setReferrer(value: string) {
  Object.defineProperty(document, "referrer", { value, configurable: true });
}

beforeEach(() => {
  __resetAttributionForTests();
  localStorage.clear();
  setUrl("");
  setReferrer("");
});

afterEach(() => {
  __resetAttributionForTests();
  setUrl("");
  setReferrer("");
});

describe("captureAttribution", () => {
  it("captures utm params from the landing URL", () => {
    setUrl("?utm_source=google&utm_medium=cpc&utm_campaign=launch");
    captureAttribution();
    expect(getStoredAttribution()).toEqual({
      utm_source: "google",
      utm_medium: "cpc",
      utm_campaign: "launch",
    });
  });

  it("captures the referrer even with no utm params", () => {
    setReferrer("https://news.example.com/post");
    captureAttribution();
    expect(getStoredAttribution()).toEqual({ referrer: "https://news.example.com/post" });
  });

  it("is first-touch: a second visit does not overwrite the first", () => {
    setUrl("?utm_source=google");
    captureAttribution();
    setUrl("?utm_source=facebook"); // later visit, different campaign
    captureAttribution();
    expect(getStoredAttribution().utm_source).toBe("google");
  });

  it("captures nothing on a direct visit (no utm, no referrer)", () => {
    captureAttribution();
    expect(getStoredAttribution()).toEqual({});
    // ...so a *later* utm'd visit on the same page can still be first-touch.
    setUrl("?utm_source=twitter");
    captureAttribution();
    expect(getStoredAttribution().utm_source).toBe("twitter");
  });

  it("truncates over-long values to their caps", () => {
    setUrl(`?utm_source=${"s".repeat(400)}`);
    setReferrer(`https://x.com/${"r".repeat(900)}`);
    captureAttribution();
    const stored = getStoredAttribution();
    expect(stored.utm_source).toHaveLength(200);
    expect(stored.referrer).toHaveLength(500);
  });

  it("ignores blank/whitespace param values", () => {
    setUrl("?utm_source=%20%20&utm_medium=cpc");
    captureAttribution();
    expect(getStoredAttribution()).toEqual({ utm_medium: "cpc" });
  });
});

describe("no storage on the visitor's device", () => {
  // The whole point of the in-memory rewrite: marketing attribution is not
  // strictly necessary, and ePrivacy treats localStorage exactly like a cookie,
  // so persisting this was the single thing on the site that would have needed
  // a consent banner. If someone reintroduces the write, this fails.
  it("writes nothing to localStorage", () => {
    setUrl("?utm_source=google&utm_medium=cpc&utm_campaign=launch");
    setReferrer("https://news.example.com/post");
    captureAttribution();

    expect(getStoredAttribution().utm_source).toBe("google"); // it did capture
    expect(localStorage.length).toBe(0); // ...and stored nothing on the device
  });

  it("writes nothing to sessionStorage either", () => {
    // sessionStorage is still storage on terminal equipment — same rule, so
    // "just use sessionStorage" is not a workaround for the consent question.
    setUrl("?utm_source=google");
    captureAttribution();
    expect(sessionStorage.length).toBe(0);
  });

  it("does not survive a fresh page (no cross-session first-touch)", () => {
    setUrl("?utm_source=google");
    captureAttribution();
    expect(getStoredAttribution().utm_source).toBe("google");

    // A new document starts from nothing — this is the deliberate cost of
    // dropping persistence, not a bug. Cross-session recognition is exactly
    // the part that would require consent.
    __resetAttributionForTests();
    setUrl("");
    expect(getStoredAttribution()).toEqual({});
  });
});

describe("getStoredAttribution", () => {
  it("returns an empty object when nothing is captured", () => {
    expect(getStoredAttribution()).toEqual({});
  });

  it("returns a copy, so a caller cannot mutate the stored capture", () => {
    setUrl("?utm_source=google");
    captureAttribution();
    const first = getStoredAttribution();
    first.utm_source = "tampered";
    expect(getStoredAttribution().utm_source).toBe("google");
  });

  it("removes a stale localStorage blob left by the old persisted version", () => {
    // Browsers of existing visitors still hold `mealbot_attribution` from
    // before this change. It must be inert AND actively cleared — continuing to
    // hold unnecessary data on someone's device is the thing this change exists
    // to stop. Asserting only that it isn't READ would pass even if the
    // removeItem were deleted.
    localStorage.setItem(
      "mealbot_attribution",
      JSON.stringify({ utm_source: "old-persisted-value" }),
    );
    captureAttribution();
    expect(getStoredAttribution()).toEqual({});
    expect(localStorage.getItem("mealbot_attribution")).toBeNull();
  });
});
