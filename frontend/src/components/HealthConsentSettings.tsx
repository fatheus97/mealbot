import { useState, type CSSProperties } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useI18n } from "../i18n";
import { formatDate } from "../i18n/localeFormat";
import { HealthConsentCheckbox } from "./HealthConsentCheckbox";

/**
 * The Settings row for the diet/allergy consent: when it was given, and a
 * one-step-plus-confirm way to withdraw it, as easy as giving it (GDPR
 * Art. 7(3)). Withdrawal is offered for ANY consent on record, including one
 * to an older consent text the server no longer counts as current. Without a
 * consent it offers the same checkbox as the forms, so consenting never
 * depends on what the planner form happens to hold. Shown to demo sessions
 * too, unlike export/delete: a demo user can consent, so they must be able to
 * withdraw.
 *
 * The confirm REPLACES the button in place instead of opening below it, so
 * nothing the user might click moves (CLS, .claude/rules/frontend.md).
 *
 * THEME: lives inside SettingsPopup's explicit light surface, so it pins its
 * own colours like the rows around it.
 */
export function HealthConsentSettings() {
  const { t, locale } = useI18n();
  const { healthConsent, healthConsentAt, withdrawHealthConsent } = useAuth();
  const onRecord = healthConsent || healthConsentAt !== null;
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleWithdraw = async () => {
    setBusy(true);
    setError(null);
    try {
      await withdrawHealthConsent();
      setConfirming(false);
    } catch {
      setError(t("settings.healthConsent.failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: "1.25rem", borderTop: "1px solid #e5e7eb", paddingTop: "1rem" }}>
      <div style={{ fontSize: 13, color: "#6b7280", marginBottom: "0.5rem" }}>
        {t("settings.healthConsent.title")}
      </div>
      <p style={{ fontSize: 13, color: "#111827", margin: "0 0 0.5rem" }}>
        {onRecord
          ? healthConsentAt
            ? t("settings.healthConsent.givenOn", { date: formatDate(healthConsentAt, locale) })
            : t("settings.healthConsent.given")
          : t("settings.healthConsent.none")}
      </p>
      {!healthConsent && <HealthConsentCheckbox active id="health-consent-settings" lightSurface />}
      {onRecord && !confirming && (
        <button type="button" onClick={() => setConfirming(true)} style={secondary}>
          {t("settings.healthConsent.withdraw")}
        </button>
      )}
      {onRecord && confirming && (
        <div>
          <p style={{ fontSize: 13, color: "#111827", margin: "0 0 0.5rem" }}>
            {t("settings.healthConsent.confirm")}
          </p>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => void handleWithdraw()}
              disabled={busy}
              style={{ ...danger, opacity: busy ? 0.6 : 1, cursor: busy ? "default" : "pointer" }}
            >
              {busy ? t("settings.healthConsent.withdrawing") : t("settings.healthConsent.confirmButton")}
            </button>
            <button type="button" onClick={() => setConfirming(false)} disabled={busy} style={secondary}>
              {t("settings.healthConsent.cancel")}
            </button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" style={{ margin: "0.4rem 0 0", color: "#b91c1c", fontSize: 12 }}>
          {error}
        </p>
      )}
    </div>
  );
}

const secondary: CSSProperties = {
  padding: "0.5rem 0.75rem",
  border: "1px solid #d1d5db",
  borderRadius: 6,
  background: "#f9fafb",
  color: "#111827",
  cursor: "pointer",
  fontSize: 13,
};

const danger: CSSProperties = {
  padding: "0.5rem 0.75rem",
  border: "1px solid #fecaca",
  borderRadius: 6,
  background: "#fef2f2",
  color: "#b91c1c",
  fontSize: 13,
};
