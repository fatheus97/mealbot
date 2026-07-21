import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { captureAttribution, getStoredAttribution } from "./attribution";

const KEY = "mealbot_attribution";

function setUrl(search: string) {
  window.history.replaceState(null, "", `/${search}`);
}

function setReferrer(value: string) {
  Object.defineProperty(document, "referrer", { value, configurable: true });
}

beforeEach(() => {
  localStorage.clear();
  setUrl("");
  setReferrer("");
});

afterEach(() => {
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

  it("stores nothing on a direct visit (no utm, no referrer)", () => {
    captureAttribution();
    expect(localStorage.getItem(KEY)).toBeNull();
    // ...so a *later* utm'd visit in the same browser can still be first-touch.
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

describe("getStoredAttribution", () => {
  it("returns an empty object when nothing is stored", () => {
    expect(getStoredAttribution()).toEqual({});
  });

  it("returns an empty object for a corrupt blob", () => {
    localStorage.setItem(KEY, "not json{");
    expect(getStoredAttribution()).toEqual({});
  });

  it("drops unknown / non-string keys from a tampered blob", () => {
    localStorage.setItem(
      KEY,
      JSON.stringify({ utm_source: "google", evil: "x", utm_medium: 42 }),
    );
    expect(getStoredAttribution()).toEqual({ utm_source: "google" });
  });
});
