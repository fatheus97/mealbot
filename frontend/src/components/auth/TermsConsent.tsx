import type { CSSProperties } from "react";
import { useI18n } from "../../i18n";
import { Trans } from "../../i18n/Trans";

/**
 * The "I accept the Terms and Privacy Policy" checkbox shown at account creation.
 *
 * The published Terms are browsewrap — "these are the terms you agree to by
 * using Mealbot" — which is the weakest form of assent, on a paid service. This
 * is the affirmative act the server records (`terms_accepted_at` /
 * `terms_version`), so it has to be a real, unticked-by-default checkbox: a
 * pre-ticked box is not consent, and the server rejects a signup without it
 * (422) rather than defaulting the field.
 *
 * Both documents open in a NEW TAB. Navigating away from a half-filled signup
 * form to read the terms — and losing the form — is the reason nobody reads
 * them.
 *
 * THEME: intended for an explicit LIGHT surface (the auth panel, the invite
 * modal), both of which set their own background AND colour. The link colour is
 * pinned for contrast against that surface; the label text deliberately
 * inherits, so it follows whatever the parent pinned. Do not drop this onto the
 * adaptive page background — see .claude/rules/frontend.md.
 */
export function TermsConsent({
  checked,
  onChange,
  disabled,
  id = "accept-terms",
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  /** Distinct id when more than one instance can be mounted at once. */
  id?: string;
}) {
  const { t } = useI18n();

  return (
    <label htmlFor={id} style={wrap}>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
        style={{ marginTop: 2, flexShrink: 0 }}
      />
      {/* One sentence, two link-shaped holes — NOT "I accept the" + link + "and"
          + link. Fragments would pin English word order, and the Czech labels
          are inflected to follow "Souhlasím s", so neither link text has a
          correct translation on its own. See i18n/Trans.tsx. */}
      <span>
        <Trans
          k="auth.acceptTerms"
          nodes={{
            terms: (
              <a href="/terms" target="_blank" rel="noopener noreferrer" style={link}>
                {t("auth.acceptTerms.termsLink")}
              </a>
            ),
            privacy: (
              <a href="/privacy" target="_blank" rel="noopener noreferrer" style={link}>
                {t("auth.acceptTerms.privacyLink")}
              </a>
            ),
          }}
        />
      </span>
    </label>
  );
}

const wrap: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  gap: "0.5rem",
  fontSize: 13,
  lineHeight: 1.4,
  cursor: "pointer",
};

const link: CSSProperties = { color: "#1d4ed8", textDecoration: "underline" };
