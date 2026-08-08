import { type CSSProperties, type FormEvent, useState } from "react";
import { ModalShell } from "../ModalShell";
import { useAuth } from "../../contexts/AuthContext";
import { deleteAccount } from "../../api";
import { useI18n } from "../../i18n";

/**
 * "Delete my account" modal.
 *
 * The privacy policy used to say there was no such button and to email us —
 * i.e. every erasure request was a manual job. This is that button.
 *
 * Password-gated, like ChangeEmailModal and for the same reason: a valid access
 * token must not be enough to destroy an account. No second "type DELETE to
 * confirm" field — the admin bulk path has one because it acts on OTHER
 * people's accounts and has no password to ask for; here the password IS the
 * deliberate step, and stacking two only teaches people to click through both.
 *
 * What the copy must not do is soften it. The list is deliberately specific
 * about the two things people are surprised by afterwards: the subscription
 * ends immediately with no refund for the rest of the period, and the invoice
 * records survive because tax law says so.
 *
 * Self-contained light surface with explicit dark text, per
 * .claude/rules/frontend.md — the app is dark-by-default via the stock Vite
 * template, so a white card that sets no colour goes white-on-white.
 */
export function DeleteAccountModal({ onClose }: { onClose: () => void }) {
  const { isSubscribed } = useAuth();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { t } = useI18n();

  async function onSubmit(e: FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await deleteAccount(password, {
        rateLimited: t("auth.deleteAccount.rateLimited"),
        fallback: t("auth.deleteAccount.failed"),
      });
      // The SAME signal authFetch raises when a refresh dies: clear local UI
      // state ONLY. Calling logout() would POST /auth/logout for a session the
      // server just destroyed — a guaranteed 401 and a console warning, for a
      // revocation that has already happened. AuthProvider's listener unmounts
      // this tree, so there is nothing to close afterwards.
      window.dispatchEvent(new Event("mealbot:logout"));
    } catch (err) {
      // Verbatim: the three server answers need three different responses from
      // the user. 401 is a typo in the password, 403 says this account type
      // cannot self-delete, and 503 means the subscription could not be
      // cancelled so NOTHING was deleted and retrying is the right move.
      setError(err instanceof Error ? err.message : t("auth.deleteAccount.failed"));
      setBusy(false);
    }
  }

  return (
    <ModalShell onClose={onClose} ariaLabel={t("auth.deleteAccount.title")} zIndex={1200}>
      <div style={card}>
        <form onSubmit={(e) => void onSubmit(e)}>
          <h3 style={heading}>{t("auth.deleteAccount.title")}</h3>
          <p style={{ margin: "0 0 0.75rem", fontSize: 13, color: bodyColor }}>
            {t("auth.deleteAccount.body")}
          </p>
          <ul style={list}>
            <li>{t("auth.deleteAccount.pointData")}</li>
            {isSubscribed && <li>{t("auth.deleteAccount.pointSubscription")}</li>}
            <li>{t("auth.deleteAccount.pointInvoices")}</li>
            <li>{t("auth.deleteAccount.pointBackups")}</li>
          </ul>
          <p style={{ margin: "0 0 1rem", fontSize: 13, color: bodyColor }}>
            {t("auth.deleteAccount.exportFirst")}
          </p>

          <label style={labelStyle}>
            {t("auth.deleteAccount.currentPassword")}
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

          <div style={actions}>
            <button type="button" onClick={onClose} style={secondaryBtn} disabled={busy}>
              {t("auth.deleteAccount.cancel")}
            </button>
            <button
              type="submit"
              disabled={busy || password.length === 0}
              style={{ ...dangerBtn, opacity: busy || !password ? 0.6 : 1 }}
            >
              {busy ? t("auth.deleteAccount.deleting") : t("auth.deleteAccount.submit")}
            </button>
          </div>

          {/* Always in the layout, contents swap. ModalShell centres the card,
              so growing it downward moves the buttons out from under the
              cursor — reserving the space is what holds them still (CLS,
              .claude/rules/frontend.md). Two lines' worth, because the 503
              billing message is long by necessity. */}
          <div style={errorSlot}>
            {error && (
              <div role="alert" style={bannerStyle}>
                {error}
              </div>
            )}
          </div>
        </form>
      </div>
    </ModalShell>
  );
}

// --- Styles (explicit light surface + dark text; see the component docstring) ---

const surface = "#ffffff";
const textColor = "#111827";
const bodyColor = "#374151";
const border = "#d1d5db";
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

const list: CSSProperties = {
  margin: "0 0 0.75rem",
  paddingLeft: "1.1rem",
  fontSize: 13,
  color: bodyColor,
  display: "flex",
  flexDirection: "column",
  gap: "0.3rem",
};

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

const actions: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: "0.5rem",
  marginTop: "1.25rem",
};

const dangerBtn: CSSProperties = {
  padding: "0.45rem 0.9rem",
  border: "none",
  borderRadius: 6,
  background: "#dc2626",
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

const errorSlot: CSSProperties = { minHeight: 76 };

const bannerStyle: CSSProperties = {
  marginTop: "0.9rem",
  padding: "0.55rem 0.7rem",
  borderRadius: 6,
  background: "#fef2f2",
  color: danger,
  border: "1px solid #fecaca",
  fontSize: 13,
};
