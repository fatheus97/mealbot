import { type CSSProperties, type FormEvent, useState } from "react";
import { ModalShell } from "../ModalShell";
import { changePassword } from "../../api";
import { useAuth } from "../../contexts/AuthContext";
import { useI18n } from "../../i18n";
import { passwordProblem } from "../../utils/passwordRules";

/**
 * "Change password" modal, for POST /auth/password.
 *
 * Same shape as ChangeEmailModal (opened from Settings, reserved error slot,
 * explicit light surface). What the copy has to get right is the session
 * outcome: the server revokes every session and mints a fresh one for THIS
 * device, so the user stays signed in here while every other device is signed
 * out. Nothing needs refreshing afterwards; the profile has not changed.
 *
 * The new password is checked against the same rules as the server
 * (`passwordProblem`) and against the confirmation before the request is
 * allowed, so the only server errors left to show are the ones that need the
 * server: a wrong current password (401) and "same as the current one" (400).
 */
export function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const { t } = useI18n();
  const { email } = useAuth();
  // The request cannot be called back once sent, and a 204 means every other
  // device is already signed out. Closing the modal mid-request would hide
  // that, so Cancel, Escape and a backdrop click all wait for the answer.
  const close = () => {
    if (!busy) onClose();
  };

  const problem = passwordProblem(next);
  const mismatch = confirm.length > 0 && confirm !== next;
  const hint = next.length > 0 && problem ? problem : mismatch ? "auth.password.mismatch" : null;
  const canSubmit = current.length > 0 && problem === null && confirm === next;

  function edit(set: (v: string) => void) {
    return (e: { target: { value: string } }) => {
      set(e.target.value);
      setError(null);
    };
  }

  async function onSubmit(e: FormEvent): Promise<void> {
    e.preventDefault();
    if (!canSubmit || busy) return;
    setError(null);
    setBusy(true);
    try {
      await changePassword(current, next, {
        rateLimited: t("auth.changePassword.rateLimited"),
        fallback: t("auth.changePassword.failed"),
      });
      setDone(true);
    } catch (err) {
      // Verbatim: the server's 401 and 400 details are already localized and
      // each asks for a different fix (retype the current one, pick another).
      setError(err instanceof Error ? err.message : t("auth.changePassword.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell onClose={close} ariaLabel={t("auth.changePassword.title")} zIndex={1200}>
      <div style={card}>
        {done ? (
          <>
            <h3 style={heading}>{t("auth.changePassword.doneTitle")}</h3>
            <p style={{ margin: "0 0 1.25rem", fontSize: 14, color: bodyColor }}>
              {t("auth.changePassword.doneBody")}
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button type="button" onClick={onClose} style={primaryBtn}>
                {t("auth.changePassword.done")}
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={(e) => void onSubmit(e)}>
            <h3 style={heading}>{t("auth.changePassword.title")}</h3>
            <p style={{ margin: "0 0 1rem", fontSize: 13, color: mutedColor }}>
              {t("auth.changePassword.body")}
            </p>

            {/* Not shown: password managers read it to file the new password
                under the right saved login (Chromium's change-password form
                guidance). Without it they guess, or save a login with no
                username. */}
            <input
              type="text"
              autoComplete="username"
              value={email}
              readOnly
              hidden
            />

            <label style={labelStyle}>
              {t("auth.changePassword.currentPassword")}
              <input
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={edit(setCurrent)}
                required
                style={inputStyle}
              />
            </label>
            <label style={labelStyle}>
              {t("auth.changePassword.newPassword")}
              <input
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={edit(setNext)}
                required
                style={inputStyle}
              />
            </label>
            <label style={labelStyle}>
              {t("auth.changePassword.confirmPassword")}
              <input
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={edit(setConfirm)}
                required
                style={inputStyle}
              />
            </label>

            {/* Reserved, like the error slot below: a rule hint that appears as
                the user types must not push the buttons down (CLS,
                .claude/rules/frontend.md). */}
            <p aria-live="polite" style={hintStyle}>
              {hint ? t(hint) : null}
            </p>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
              <button type="button" onClick={close} style={secondaryBtn} disabled={busy}>
                {t("auth.changePassword.cancel")}
              </button>
              <button
                type="submit"
                disabled={busy || !canSubmit}
                style={{ ...primaryBtn, opacity: busy || !canSubmit ? 0.6 : 1 }}
              >
                {busy ? t("auth.changePassword.changing") : t("auth.changePassword.submit")}
              </button>
            </div>

            {/* Always in the layout, contents swap: ModalShell centres the
                card, so growing it would move the buttons (see ChangeEmailModal). */}
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

// --- Styles (explicit light surface + dark text, as ChangeEmailModal) ---

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

const hintStyle: CSSProperties = {
  margin: "-0.25rem 0 0.75rem",
  minHeight: 18,
  fontSize: 12,
  color: mutedColor,
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
