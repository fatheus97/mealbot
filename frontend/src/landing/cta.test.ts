import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  applyConfig,
  applyRegistrationCopy,
  createDemoHandler,
  forwardSearchOnAppLinks,
  loggedInRedirectTarget,
  paramForwardTarget,
  type PublicConfig,
  type RegistrationCopyElements,
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

describe("createDemoHandler", () => {
  function setup(startDemo: () => Promise<unknown>) {
    const button = document.createElement("a");
    button.textContent = "Try the demo";
    const navigate = vi.fn<(url: string) => void>();
    const handler = createDemoHandler(button, {
      startDemo,
      navigate,
      search: "?utm_source=x",
    });
    return { button, navigate, handler };
  }

  function click(handler: (e: Event) => void) {
    const event = new MouseEvent("click", { cancelable: true });
    handler(event);
    return event;
  }

  it("starts a demo and navigates to /app, preserving the query string", async () => {
    const startDemo = vi.fn().mockResolvedValue({ id: 1 });
    const { navigate, handler } = setup(startDemo);

    const event = click(handler);
    expect(event.defaultPrevented).toBe(true);
    await vi.waitFor(() => expect(navigate).toHaveBeenCalledWith("/app?utm_source=x"));
    expect(startDemo).toHaveBeenCalledTimes(1);
  });

  it("IGNORES a second click while the first is in flight", async () => {
    // /auth/demo has no idempotency — every call mints a new ephemeral
    // account, so an unguarded double-click creates two accounts racing to
    // own one cookie.
    let resolve!: (v: unknown) => void;
    const startDemo = vi.fn().mockReturnValue(new Promise((r) => (resolve = r)));
    const { handler, navigate } = setup(startDemo);

    click(handler);
    click(handler);
    click(handler);
    expect(startDemo).toHaveBeenCalledTimes(1);

    resolve({ id: 1 });
    await vi.waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
  });

  it("shows a pending label while the request is in flight", () => {
    const { button, handler } = setup(() => new Promise(() => {}));
    click(handler);
    expect(button.textContent).toBe("Starting…");
  });

  it("still hands off to /app when the demo call fails, restoring the label", async () => {
    const { button, navigate, handler } = setup(() => Promise.reject(new Error("nope")));
    click(handler);
    await vi.waitFor(() => expect(navigate).toHaveBeenCalledWith("/app?utm_source=x"));
    expect(button.textContent).toBe("Try the demo");
  });
});

describe("applyRegistrationCopy", () => {
  const CLOSED_ANSWER =
    "Mealbot is currently a private alpha. Request access below, or log in if you already have an account.";

  interface Fixture {
    note: HTMLElement;
    faqAnswer: HTMLElement;
    accessHeading: HTMLElement;
    accessIntro: HTMLElement;
    faqSchema: HTMLScriptElement;
    els: RegistrationCopyElements;
  }

  function fixture(answerInMarkup = CLOSED_ANSWER): Fixture {
    const note = document.createElement("p");
    note.textContent = "Private alpha — see Access below.";

    const faqAnswer = document.createElement("div");
    // Wrapped across lines exactly as the markup wraps it, so the test also
    // covers the whitespace normalization the JSON-LD match depends on.
    faqAnswer.textContent = `\n            ${answerInMarkup.replace(
      "or log in",
      "or log in\n            ",
    )}\n          `;

    const accessHeading = document.createElement("h2");
    accessHeading.textContent = "Private alpha";

    const accessIntro = document.createElement("p");
    accessIntro.textContent = "Mealbot isn't open to public sign-ups yet.";

    const faqSchema = document.createElement("script");
    faqSchema.type = "application/ld+json";
    faqSchema.textContent = JSON.stringify({
      "@context": "https://schema.org",
      "@graph": [
        { "@type": "Organization", name: "Mealbot" },
        {
          "@type": "FAQPage",
          mainEntity: [
            {
              "@type": "Question",
              name: "How much does it cost?",
              acceptedAnswer: { "@type": "Answer", text: "€4.99 per month." },
            },
            {
              "@type": "Question",
              name: "Is it available now?",
              acceptedAnswer: { "@type": "Answer", text: CLOSED_ANSWER },
            },
          ],
        },
      ],
    });

    return {
      note,
      faqAnswer,
      accessHeading,
      accessIntro,
      faqSchema,
      els: { note, faqAnswer, accessHeading, accessIntro, faqSchema },
    };
  }

  function schemaAnswers(script: HTMLScriptElement): string[] {
    const parsed = JSON.parse(script.textContent ?? "") as {
      "@graph": Array<{ mainEntity?: Array<{ acceptedAnswer: { text: string } }> }>;
    };
    const faq = parsed["@graph"].find((node) => node.mainEntity !== undefined);
    return (faq?.mainEntity ?? []).map((q) => q.acceptedAnswer.text);
  }

  beforeEach(() => {
    document.documentElement.setAttribute("lang", "en");
  });

  it("rewrites all four access-model claims once registration is open", () => {
    const f = fixture();
    applyRegistrationCopy({ registration_enabled: true }, f.els);

    expect(f.note.textContent).toBe("10-day free trial. Cancel any time.");
    expect(f.faqAnswer.textContent).toContain("Sign up above");
    expect(f.accessHeading.textContent).toBe("Questions before you start?");
    expect(f.accessIntro.textContent).toContain("Sign-ups are open");

    for (const el of [f.note, f.faqAnswer, f.accessHeading, f.accessIntro]) {
      expect(el.textContent).not.toMatch(/private alpha/i);
    }
  });

  it("rewrites the matching FAQPage answer and leaves the others alone", () => {
    const f = fixture();
    applyRegistrationCopy({ registration_enabled: true }, f.els);

    const answers = schemaAnswers(f.faqSchema);
    expect(answers[0]).toBe("€4.99 per month.");
    expect(answers[1]).not.toMatch(/private alpha/i);
    expect(answers[1]).toBe(f.faqAnswer.textContent);
  });

  it("leaves everything alone while registration is closed", () => {
    const f = fixture();
    applyRegistrationCopy({ registration_enabled: false }, f.els);

    expect(f.note.textContent).toContain("Private alpha");
    expect(f.accessHeading.textContent).toBe("Private alpha");
    expect(schemaAnswers(f.faqSchema)[1]).toBe(CLOSED_ANSWER);
  });

  it("leaves everything alone when the config never resolved", () => {
    // Same fail-safe as applyConfig: an unreachable /api/config must not be
    // read as "registration is open" and invite people to sign up into a 403.
    const f = fixture();
    applyRegistrationCopy(null, f.els);
    expect(f.accessHeading.textContent).toBe("Private alpha");
    expect(schemaAnswers(f.faqSchema)[1]).toBe(CLOSED_ANSWER);
  });

  it("uses the Czech table on the Czech page", () => {
    document.documentElement.setAttribute("lang", "cs");
    const f = fixture();
    applyRegistrationCopy({ registration_enabled: true }, f.els);

    expect(f.accessHeading.textContent).toBe("Máte otázku, než začnete?");
    expect(f.note.textContent).toContain("zkušební verze zdarma");
  });

  it("leaves the JSON-LD untouched when it has drifted from the visible answer", () => {
    // The block is matched on the visible answer's text. If the two copies
    // have diverged, replacing the wrong entry is worse than replacing none —
    // so a miss is a no-op, and landingCs.test.ts fails the build if they ever
    // do diverge in the shipped HTML.
    const f = fixture("Mealbot is currently invite-only. Ask below.");
    applyRegistrationCopy({ registration_enabled: true }, f.els);

    expect(schemaAnswers(f.faqSchema)[1]).toBe(CLOSED_ANSWER);
    expect(f.faqAnswer.textContent).toContain("Sign up above");
  });

  it("survives a page that is missing every element", () => {
    expect(() =>
      applyRegistrationCopy(
        { registration_enabled: true },
        { note: null, faqAnswer: null, accessHeading: null, accessIntro: null, faqSchema: null },
      ),
    ).not.toThrow();
  });

  it("survives a JSON-LD block that is not valid JSON", () => {
    const f = fixture();
    f.faqSchema.textContent = "{ not json";
    expect(() => applyRegistrationCopy({ registration_enabled: true }, f.els)).not.toThrow();
    expect(f.faqSchema.textContent).toBe("{ not json");
  });
});
