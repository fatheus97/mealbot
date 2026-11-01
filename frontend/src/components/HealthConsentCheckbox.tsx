import { useState, type CSSProperties } from "react";
import { useAuth } from "../contexts/AuthContext";
import { HealthConsentStaleError } from "../api";
import { useI18n } from "../i18n";
import { Trans } from "../i18n/Trans";
import { legalHref } from "../i18n/localeFormat";
import { usePrefersDark } from "../hooks/usePrefersDark";
import { MUTED_PAGE_TEXT, PAGE_TEXT } from "../constants/theme";

/**
 * Explicit consent (GDPR Art. 9(2)(a)) to process the diets, allergens and
 * ingredients to avoid the user just entered, shown above Generate only while
 * the form carries any of them and the user has not consented yet.
 *
 * Ticking it IS the consent: it records it on the server right away
 * (POST /users/health-consent), unticked by default, never bundled with the
 * Terms checkbox. The parent keeps Generate disabled until `healthConsent`
 * turns true; the server refuses such a request anyway (403), so this is the
 * proactive surface and the 403 the backstop. Withdrawing lives in Settings.
 *
 * THEME: sits on the adaptive page background (the planner and Cook Now
 * forms), so the text inherits the adaptive colour and the link only adds an
 * underline; the one coloured line, the error, picks its colour per scheme.
 */
export function HealthConsentCheckbox({ active, id = "health-consent", lightSurface = false }: {
  /** Whether the form currently carries diets, allergens or ingredients to avoid. */
  active: boolean;
  /** Distinct id when two forms can be mounted at once. */
  id?: string;
  /** Rendered on an explicit light surface (Settings) rather than the adaptive
   *  page: the error then keeps its light-theme colour in dark mode too. */
  lightSurface?: boolean;
}) {
  const { t, locale } = useI18n();
  const { healthConsent, grantHealthConsent } = useAuth();
  const scheme = usePrefersDark() ? "dark" : "light";
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!active || healthConsent) return null;

  const handleChange = async (checked: boolean) => {
    if (!checked || saving) return;
    setSaving(true);
    setError(null);
    try {
      await grantHealthConsent();
    } catch (err) {
      setError(t(err instanceof HealthConsentStaleError ? "healthConsent.stale" : "healthConsent.failed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={wrap}>
      <label htmlFor={id} style={row}>
        <input
          id={id}
          type="checkbox"
          // Shows the tick while the grant is in flight; on success the whole
          // control unmounts, on failure it unticks with the error below.
          checked={saving}
          disabled={saving}
          onChange={(e) => void handleChange(e.target.checked)}
          style={{ marginTop: 3, flexShrink: 0 }}
        />
        <span>
          <Trans
            k="healthConsent.label"
            nodes={{
              privacy: (
                <a href={legalHref(locale, "privacy")} target="_blank" rel="noopener noreferrer" style={link}>
                  {t("healthConsent.privacyLink")}
                </a>
              ),
            }}
          />
        </span>
      </label>
      <p style={{ ...MUTED_PAGE_TEXT, fontSize: 12, margin: "0.35rem 0 0 1.6rem" }}>
        {t("healthConsent.note")}
      </p>
      {error && (
        <p
          role="alert"
          style={{ color: PAGE_TEXT.error[lightSurface ? "light" : scheme], fontSize: 13, margin: "0.35rem 0 0 1.6rem" }}
        >
          {error}
        </p>
      )}
    </div>
  );
}

const wrap: CSSProperties = { margin: "0 0 0.75rem", maxWidth: 640 };

const row: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  gap: "0.5rem",
  fontSize: 14,
  lineHeight: 1.45,
  cursor: "pointer",
};

const link: CSSProperties = { color: "inherit", textDecoration: "underline" };
