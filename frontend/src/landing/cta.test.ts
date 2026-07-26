import { describe, it, expect, beforeEach } from "vitest";
import {
  applyConfig,
  forwardSearchOnAppLinks,
  loggedInRedirectTarget,
  paramForwardTarget,
  type PublicConfig,
} from "./cta";

function link(): HTMLAnchorElement {
  return document.createElement("a");
}

describe("paramForwardTarget", () => {
  it("forwards a reset_token param to /app", () => {
    expect(paramForwardTarget("?reset_token=abc")).toBe("/app?reset_token=abc");
  });

  it("forwards an invite param to /app", () => {
    expect(paramForwardTarget("?invite=xyz")).toBe("/app?invite=xyz");
  });

  it("forwards a billing param to /app", () => {
    expect(paramForwardTarget("?billing=success")).toBe("/app?billing=success");
  });

  it("does not forward a plain visit with no query string", () => {
    expect(paramForwardTarget("")).toBeNull();
  });

  it("does not forward a visit carrying only utm params", () => {
    expect(paramForwardTarget("?utm_source=google&utm_medium=cpc")).toBeNull();
  });

  it("preserves the full query string (including any utm params alongside the forwarded one)", () => {
    expect(paramForwardTarget("?invite=xyz&utm_source=newsletter")).toBe(
      "/app?invite=xyz&utm_source=newsletter",
    );
  });
});

describe("loggedInRedirectTarget", () => {
  it("returns null when there is no logged-in hint", () => {
    expect(loggedInRedirectTarget(false, "")).toBeNull();
  });

  it("redirects to /app, preserving the query string, when the hint is present", () => {
    expect(loggedInRedirectTarget(true, "?utm_source=google")).toBe("/app?utm_source=google");
  });
});

describe("forwardSearchOnAppLinks", () => {
  it("threads the current query string onto both the login and demo links", () => {
    const login = link();
    const demo = link();
    forwardSearchOnAppLinks({ login, demo }, "?utm_source=google");
    expect(login.getAttribute("href")).toBe("/app?utm_source=google");
    expect(demo.getAttribute("href")).toBe("/app?utm_source=google");
  });

  it("tolerates a missing element (defensive — getElementById can return null)", () => {
    expect(() => forwardSearchOnAppLinks({ login: null, demo: null }, "")).not.toThrow();
  });

  it("still sets /app (no query string) for a plain visit", () => {
    const login = link();
    forwardSearchOnAppLinks({ login, demo: null }, "");
    expect(login.getAttribute("href")).toBe("/app");
  });
});

describe("applyConfig", () => {
  const CLOSED: PublicConfig = {
    registration_enabled: false,
    demo_mode: false,
    annual_billing_available: true,
  };
  const OPEN: PublicConfig = {
    registration_enabled: true,
    demo_mode: false,
    annual_billing_available: true,
  };
  const DEMO_ON: PublicConfig = {
    registration_enabled: false,
    demo_mode: true,
    annual_billing_available: true,
  };

  let primary: HTMLAnchorElement;
  let demo: HTMLAnchorElement;

  beforeEach(() => {
    primary = link();
    primary.textContent = "Request access";
    primary.href = "mailto:info@trymealbot.com";
    demo = link();
    demo.classList.add("cta-reserved");
  });

  it("config null (pending or failed fetch) leaves the baseline untouched — no flash", () => {
    applyConfig(null, { primary, demo }, "");
    expect(primary.textContent).toBe("Request access");
    expect(primary.getAttribute("href")).toBe("mailto:info@trymealbot.com");
    expect(demo.classList.contains("cta-reserved")).toBe(true);
  });

  it("registration_enabled === false leaves the mailto baseline as-is", () => {
    applyConfig(CLOSED, { primary, demo }, "");
    expect(primary.textContent).toBe("Request access");
    expect(primary.getAttribute("href")).toBe("mailto:info@trymealbot.com");
  });

  it("registration_enabled === true swaps the primary CTA to Get started -> /app", () => {
    applyConfig(OPEN, { primary, demo }, "?utm_source=google");
    expect(primary.textContent).toBe("Get started");
    expect(primary.getAttribute("href")).toBe("/app?utm_source=google");
  });

  it("demo_mode === true reveals the Try the demo button (drops the reserved class, never removed from the flow)", () => {
    applyConfig(DEMO_ON, { primary, demo }, "");
    expect(demo.classList.contains("cta-reserved")).toBe(false);
  });

  it("demo_mode === false keeps the Try the demo button reserved (present, invisible)", () => {
    applyConfig(CLOSED, { primary, demo }, "");
    expect(demo.classList.contains("cta-reserved")).toBe(true);
  });

  it("tolerates missing elements (defensive)", () => {
    expect(() => applyConfig(OPEN, { primary: null, demo: null }, "")).not.toThrow();
  });
});
