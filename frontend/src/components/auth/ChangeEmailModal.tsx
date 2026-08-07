import { type CSSProperties, type FormEvent, useState } from "react";
import { ModalShell } from "../ModalShell";
import { useAuth } from "../../contexts/AuthContext";
import { changeEmail } from "../../api";
import { useI18n } from "../../i18n";
import { Trans } from "../../i18n/Trans";

/**
 * "Change your email address" modal.
 *
 * Exists because a typo at registration used to be unrecoverable: the
 * confirmation link goes to an address the user does not own, "resend" only
 * re-mails that same wrong address, and the server then 403s every feature
 * behind `require_verified_email`. Reached from the confirm-your-email banner
 * (the locked-out case) and from Settings (a verified user who lost access to
 * their inbox has the same problem and no banner to click).
 *
 * A MODAL rather than an inline expander on purpose: the banner sits above the
 * whole page, so expanding a form in flow would shove everything down under the
 * user's cursor — the CLS trap in .claude/rules/frontend.md. A fixed-position
 * overlay shifts nothing.
 *
 * Self-contained light surface with an explicit dark text colour, per the same
 * rules file — the app is dark-by-default via the stock Vite template, so a
 * white card that does not pin its own colour goes white-on-white.
 */
export function ChangeEmailModal({ onClose }: { onClose: () => void }) {
  const { email, refreshProfile } = useAuth();
  const [newEmail, setNewEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const { t } = useI18n();

  const unchanged = newEmail.trim().toLowerCase() === (email ?? "").trim().toLowerCase();
  const canSubmit = newEmail.trim().length > 0 && password.length > 0 && !unchanged;

  async function onSubmit(e: FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const target = newEmail.trim();
    try {
      await changeEmail(password, target);
      // The server rotated this device's cookies and cleared email_verified, so
      // the cached profile is now wrong in two ways. Refresh before showing the
      // confirmation, or the banner keeps naming the old address.
      await refreshProfile();
      setDone(target);
    } catch (err) {
      // Surfaced verbatim, and that stays correct now the UI is translated:
      // all three of these ("Current password is incorrect", "Email already
      // registered", "That is already the email address on your account")
      // are raised as LocalizedHTTPException, so the server already sends them
      // in the caller's language. Each needs a different response from the
      // user, so they must not be collapsed into one generic message. Only the
      // non-Error fallback is a client-side string.
      setError(err instanceof Error ? err.message : t("auth.changeEmail.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell onClose={onClose} ariaLabel={t("auth.changeEmail.title")} zIndex={1200}>
      <div style={card}>
        {done ? (
          <>
            <h3 style={heading}>{t("auth.changeEmail.doneTitle")}</h3>
            <p style={{ margin: "0 0 1.25rem", fontSize: 14, color: bodyColor }}>
              <Trans k="auth.changeEmail.doneBody" nodes={{ email: <strong>{done}</strong> }} />
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button type="button" onClick={onClose} style={primaryBtn}>
                {t("auth.changeEmail.done")}
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={(e) => void onSubmit(e)}>
            <h3 style={heading}>{t("auth.changeEmail.title")}</h3>
            <p style={{ margin: "0 0 1rem", fontSize: 13, color: mutedColor }}>
              {t("auth.changeEmail.body")}
            </p>

            <label style={labelStyle}>
              {t("auth.changeEmail.newEmail")}
              <input
                type="email"
                autoComplete="email"
                value={newEmail}
                onChange={(e) => {
                  setNewEmail(e.target.value);
                  setError(null);
                }}
                placeholder={t("auth.emailPlaceholder")}
                maxLength={128}
                required
                style={inputStyle}
              />
            </label>

            <label style={labelStyle}>
              {t("auth.changeEmail.currentPassword")}
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setError(null);
                }}
                required
                style={inputStyle}
              />
            </label>
            <p style={{ margin: "-0.25rem 0 0", fontSize: 12, color: mutedColor }}>
              {t("auth.changeEmail.why")}
            </p>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: "0.5rem",
                marginTop: "1.25rem",
              }}
            >
              <button type="button" onClick={onClose} style={secondaryBtn}>
                {t("auth.changeEmail.cancel")}
              </button>
              <button
                type="submit"
                disabled={busy || !canSubmit}
                title={unchanged && newEmail ? t("auth.changeEmail.unchanged") : undefined}
                style={{ ...primaryBtn, opacity: busy || !canSubmit ? 0.6 : 1 }}
              >
                {busy ? t("auth.changeEmail.changing") : t("auth.changeEmail.submit")}
              </button>
            </div>

            {/* The slot is ALWAYS in the layout; only its contents appear. Being
                below the buttons is not enough on its own here: ModalShell
                centres the card vertically, so growing it downward pushes the
                whole card UP by half the added height and the buttons move out
                from under the cursor anyway. Reserving the space is what
                actually holds them still (.claude/rules/frontend.md, CLS). */}
            <div style={errorSlot}>
              {error && (
                <div role="alert" style={bannerStyle}>
                  {error}
                </div>
              )}
            </div>
          </form>
        )}
      </div>
    </ModalShell>
  );
}

// --- Styles (explicit light surface + dark text; see the component docstring) ---

const surface = "#ffffff";
const textColor = "#111827";
const bodyColor = "#374151";
const mutedColor = "#6b7280";
const border = "#d1d5db";
const accent = "#4f46e5";
const danger = "#b91c1c";

const card: CSSProperties = {
  background: surface,
  color: textColor,
  borderRadius: 12,
  padding: "1.5rem",
  width: "min(92vw, 440px)",
  maxHeight: "90vh",
  overflowY: "auto",
  boxShadow: "0 4px 24px rgba(0,0,0,0.25)",
  border: `1px solid ${border}`,
  boxSizing: "border-box",
};

const heading: CSSProperties = { margin: "0 0 0.5rem", fontSize: "1.2rem", color: textColor };

const labelStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.3rem",
  fontSize: 13,
  color: bodyColor,
  marginBottom: "0.75rem",
};

const inputStyle: CSSProperties = {
  padding: "0.5rem 0.6rem",
  border: `1px solid ${border}`,
  borderRadius: 6,
  fontSize: 14,
  background: surface,
  color: textColor,
  width: "100%",
  boxSizing: "border-box",
  fontFamily: "inherit",
};

const primaryBtn: CSSProperties = {
  padding: "0.45rem 0.9rem",
  border: "none",
  borderRadius: 6,
  background: accent,
  color: "#ffffff",
  cursor: "pointer",
  fontSize: 14,
  fontWeight: 600,
};

const secondaryBtn: CSSProperties = {
  padding: "0.45rem 0.9rem",
  border: `1px solid ${border}`,
  borderRadius: 6,
  background: surface,
  color: bodyColor,
  cursor: "pointer",
  fontSize: 14,
};

// Height of one line of banner text plus its padding and margin. Two lines
// still nudge the card, but the common single-line errors ("Current password is
// incorrect", "Email already registered") cost zero movement.
const errorSlot: CSSProperties = { minHeight: 56 };

const bannerStyle: CSSProperties = {
  marginTop: "0.9rem",
  padding: "0.55rem 0.7rem",
  borderRadius: 6,
  background: "#fef2f2",
  color: danger,
  border: "1px solid #fecaca",
  fontSize: 13,
};
