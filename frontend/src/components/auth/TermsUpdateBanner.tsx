import { useId, useState, type CSSProperties } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { TermsVersionStaleError } from "../../api";
import { useI18n } from "../../i18n";
import { Trans } from "../../i18n/Trans";
import { legalHref } from "../../i18n/localeFormat";

/**
 * "We've changed our Privacy Policy and Terms" for a user who has not accepted
 * the latest MATERIAL change (`terms_update` on the profile, server-computed).
 *
 * Non-dismissable on purpose: no close button, it stays until "I agree", and the
 * server records that click (its clock, its version). But it is a BANNER, not a
 * blocking modal. The remedy the Terms offer for disagreeing is to cancel or
 * delete the account, and both live behind UI a modal would cover. Making
 * someone agree before they can reach the exit is the dark pattern this avoids.
 *
 * The summary is server text (app.core.legal.CHANGE_SUMMARY, shared with the
 * notice email), shown in the UI locale with English as the fallback.
 *
 * Theme-safety (.claude/rules/frontend.md): one explicit light surface with an
 * explicit dark colour; the links inherit that colour.
 */
export function TermsUpdateBanner() {
  const { userId, termsUpdate, acceptTerms } = useAuth();
  const { t, locale } = useI18n();
  const titleId = useId();
  const [state, setState] = useState<"idle" | "saving" | "failed" | "stale">("idle");

  if (!userId || !termsUpdate) return null;
  const summary = termsUpdate.summary[locale] ?? termsUpdate.summary.en;

  async function agree(version: string): Promise<void> {
    setState("saving");
    try {
      // On success the profile comes back with terms_update null and this
      // component unmounts, so there is no "done" state to set.
      await acceptTerms(version);
    } catch (err) {
      setState(err instanceof TermsVersionStaleError ? "stale" : "failed");
    }
  }

  return (
    <section aria-labelledby={titleId} style={wrap}>
      <strong id={titleId} style={{ display: "block", marginBottom: "0.35rem" }}>
        {t("termsUpdate.title")}
      </strong>
      {summary && <p style={para}>{summary}</p>}
      <p style={para}>
        <Trans
          k="termsUpdate.readFull"
          nodes={{
            privacy: (
              <a href={legalHref(locale, "privacy")} target="_blank" rel="noopener noreferrer" style={link}>
                {t("termsUpdate.readFull.privacy")}
              </a>
            ),
            terms: (
              <a href={legalHref(locale, "terms")} target="_blank" rel="noopener noreferrer" style={link}>
                {t("termsUpdate.readFull.terms")}
              </a>
            ),
          }}
        />
      </p>
      <p style={para}>
        {t("termsUpdate.continuing")} {t("termsUpdate.disagree")}
      </p>
      <button
        type="button"
        onClick={() => void agree(termsUpdate.version)}
        disabled={state === "saving"}
        style={button}
      >
        {state === "saving" ? t("termsUpdate.saving") : t("termsUpdate.agree")}
      </button>
      {(state === "failed" || state === "stale") && (
        <span role="alert" style={{ display: "block", marginTop: "0.5rem", fontSize: "0.85rem" }}>
          {state === "stale" ? t("termsUpdate.stale") : t("termsUpdate.failed")}
        </span>
      )}
    </section>
  );
}

// Explicit background + explicit colour, together (the white-on-white rule).
const wrap: CSSProperties = {
  backgroundColor: "#eff6ff",
  color: "#1e3a8a",
  border: "1px solid #93c5fd",
  borderRadius: 8,
  padding: "0.8rem 0.9rem",
  marginBottom: "1rem",
  fontSize: "0.9rem",
  lineHeight: 1.45,
};

const para: CSSProperties = { margin: "0 0 0.5rem" };

const link: CSSProperties = { color: "inherit", textDecoration: "underline" };

const button: CSSProperties = {
  padding: "0.4rem 0.9rem",
  border: "1px solid #1d4ed8",
  borderRadius: 6,
  backgroundColor: "#1d4ed8",
  color: "#ffffff",
  cursor: "pointer",
  fontWeight: 600,
};
