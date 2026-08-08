import type { CSSProperties } from "react";
import { useI18n } from "../i18n";
import { legalHref } from "../i18n/localeFormat";

/**
 * Persistent legal footer for the SPA.
 *
 * The two documents were only reachable from the consent checkbox at
 * registration and from the paywall — i.e. only while signing up or paying. A
 * user who is already in the app had no route to the policy binding them, which
 * is both a GDPR/consumer-law expectation and simply how every site works.
 * The marketing landing already carries the same pair in its own footer.
 *
 * Hrefs are locale-derived (`legalHref`), not "/terms": the Czech editions are
 * equally authoritative, so a Czech UI must not send the reader to the English
 * one.
 *
 * Sets NO background, and inherits the adaptive default TEXT colour rather than
 * the default LINK colour — the app is dark-by-default via the stock Vite
 * template (see .claude/rules/frontend.md), and `index.css`'s `a { #646cff }`
 * measures **3.79:1** on that #242424 page, i.e. below AA for 13px text.
 * Measured in the browser, not assumed. `color: inherit` rides the scheme-aware
 * body colour instead (15.5:1 dark / 12.6:1 light) with no matchMedia hook, and
 * the underline carries the affordance the colour would have.
 */
export function AppFooter() {
  const { t, locale } = useI18n();
  return (
    <footer style={wrap}>
      <a
        href={legalHref(locale, "privacy")}
        target="_blank"
        rel="noopener noreferrer"
        style={link}
      >
        {t("footer.privacy")}
      </a>
      <span aria-hidden="true">·</span>
      <a
        href={legalHref(locale, "terms")}
        target="_blank"
        rel="noopener noreferrer"
        style={link}
      >
        {t("footer.terms")}
      </a>
    </footer>
  );
}

const link: CSSProperties = { color: "inherit", textDecoration: "underline" };

const wrap: CSSProperties = {
  marginTop: "2.5rem",
  paddingTop: "1rem",
  borderTop: "1px solid #9ca3af80",
  display: "flex",
  flexWrap: "wrap",
  gap: "0.5rem",
  justifyContent: "center",
  fontSize: 13,
};
