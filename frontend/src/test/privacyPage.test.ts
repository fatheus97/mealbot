import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

/**
 * Guards the privacy policy's load-bearing sentences.
 *
 * A privacy policy is the one page where a silent deletion is worse than a
 * broken layout: the disclosures below are the ones that would make the page
 * misleading if they went missing in an edit. This asserts the BUILT output, so
 * it also proves the page is actually part of the Vite multi-page build rather
 * than an orphaned file nobody ships.
 */

const DIST = resolve(import.meta.dirname, "../../dist/privacy.html");
const DIST_INDEX = resolve(import.meta.dirname, "../../dist/index.html");
const built = existsSync(DIST);

// Unconditional, so `describe.skipIf` below can never silently report zero
// tests when the build hasn't run — the failure mode that hid a real bug once.
it("dist/privacy.html exists (run `npm run build` first)", () => {
  expect(built).toBe(true);
});

describe.skipIf(!built)("privacy policy (built dist/privacy.html)", () => {
  const html = built ? readFileSync(DIST, "utf8") : "";

  describe("the disclosure that must never disappear", () => {
    it("says dietary data is sent to Google", () => {
      // The single most important fact on the page: allergens and diet types
      // leave our servers. Deleting this makes the policy actively misleading.
      expect(html).toMatch(/Gemini API/);
      expect(html).toMatch(/allergens/i);
      expect(html).toMatch(/Google/);
    });

    it("states that no account identifier goes with it", () => {
      // The mitigating half of the same fact — the content is pseudonymous at
      // the provider. Keeping one without the other misrepresents the risk.
      expect(html).toMatch(/do not send your email address/i);
    });

    it("names every third party that receives data", () => {
      for (const party of ["Google", "Stripe", "Resend", "GitHub", "Hetzner", "Cloudflare"]) {
        expect(html).toContain(party);
      }
    });
  });

  describe("promises the code can actually keep", () => {
    it("no longer claims the self-service buttons are missing", () => {
      // This assertion used to run the other way: the page said outright that
      // no delete button and no export existed. Both now do (GET
      // /api/users/export, POST /api/auth/delete-account), so the honest
      // disclosure became a false one. Kept as a regression guard because a
      // copy-paste from the old wording is exactly how it would come back.
      expect(html).not.toMatch(/no "delete my account" button/i);
      expect(html).not.toMatch(/no self-service data export/i);
    });

    it("points at Settings for the three self-service rights", () => {
      expect(html).toMatch(/in Settings/i);
      expect(html).toMatch(/download your data/i);
      expect(html).toMatch(/delete your account/i);
    });

    it("still admits deletion is not absolute", () => {
      // Invoices survive (tax law), Stripe's customer record and any filed bug
      // report are not removed automatically, and backups age out over 14 days.
      // Deleting the button-does-not-exist bullet must not quietly delete this.
      expect(html).toMatch(/not absolute/i);
      expect(html).toMatch(/14 days/i);
    });

    it("warns that deleting forfeits the rest of a paid period", () => {
      // The single most likely support complaint, and the one thing a user
      // cannot discover before it is irreversible.
      expect(html).toMatch(/not refunded/i);
    });
  });

  describe("cookie claims match the three cookies we actually set", () => {
    it("lists exactly the real cookie names", () => {
      for (const c of ["mealbot_at", "mealbot_rt", "mealbot_csrf"]) {
        expect(html).toContain(c);
      }
    });

    it("claims no analytics or tracking", () => {
      expect(html).toMatch(/no analytics/i);
    });

    it("does not promise a cookie banner it doesn't render", () => {
      // We removed the only non-essential storage (attribution) precisely so no
      // banner is needed. If someone reintroduces non-essential storage, this
      // sentence becomes false and should fail loudly then.
      expect(html).toMatch(/no consent banner/i);
    });
  });

  describe("theme safety", () => {
    it("defines a light-scheme override for every custom property", () => {
      // Same matched-pair rule as the landing page: a property set only in the
      // dark block would pair a hardcoded background with adaptive text.
      const dark = html.match(/:root\s*\{([^}]*)\}/)?.[1] ?? "";
      const light = html.match(/prefers-color-scheme:\s*light\s*\)\s*\{\s*:root\s*\{([^}]*)\}/)?.[1] ?? "";
      const names = (block: string) =>
        new Set([...block.matchAll(/(--[a-z-]+)\s*:/g)].map((m) => m[1]));
      const darkVars = names(dark);
      const lightVars = names(light);
      expect(darkVars.size).toBeGreaterThan(5);
      const missing = [...darkVars].filter((v) => !lightVars.has(v) && v !== "--color-scheme");
      expect(missing).toEqual([]);
    });

    it("keeps wide tables in their own scroll container", () => {
      // The page body must never scroll sideways on mobile.
      expect(html).toMatch(/\.table-scroll\s*\{[^}]*overflow-x:\s*auto/);
    });
  });

  describe("identifies the controller", () => {
    it("carries no unfilled placeholders", () => {
      // The page shipped with [OPERATOR — …] blanks only the operator could
      // fill. Publishing those to a live legal page would be worse than having
      // no policy, so this fails loudly if one is ever reintroduced.
      const placeholders = html.match(/\[OPERATOR[^\]]*\]/g);
      expect(placeholders).toBeNull();
    });

    it("names the controller, address and IČO", () => {
      // Identifying the controller is the one thing a privacy policy cannot
      // omit — without it the reader has nobody to address a request to.
      expect(html).toContain("František Bláha");
      expect(html).toMatch(/IČO\s*22059946/);
      expect(html).toMatch(/Hradec Králové/);
      expect(html).toMatch(/mailto:info@trymealbot\.com/);
    });

    it("states where the servers physically are", () => {
      expect(html).toMatch(/Nuremberg, Germany/);
    });
  });

  describe("server logs", () => {
    it("states that access logs rotate rather than growing forever", () => {
      // Before container log rotation existed there was no truthful retention
      // statement to make — "they grow until the disk fills" is not an answer.
      expect(html).toMatch(/capped in size and rotate automatically/i);
      expect(html).toMatch(/oldest entries are deleted/i);
    });

    it("does not invent a retention period it cannot honour", () => {
      // Rotation is by SIZE, not age, so any "N days" claim would be fiction.
      expect(html).toMatch(/cannot honestly quote a fixed number of days/i);
    });

    it("states that logs carry no reset or sign-in links", () => {
      // True only because nginx now logs $uri instead of $request — the fix
      // that stopped single-use secrets landing in the log next to the IP.
      expect(html).toMatch(/never contain sign-in links or password-reset links/i);
    });
  });

  describe("reachability", () => {
    it("is linked from the landing page footer", () => {
      // An unlinked policy is not a published policy.
      const index = readFileSync(DIST_INDEX, "utf8");
      expect(index).toMatch(/href="\/privacy"/);
    });
  });
});
