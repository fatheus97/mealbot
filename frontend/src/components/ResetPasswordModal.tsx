import { useEffect, useId, useMemo, useState } from "react";
import { ModalShell } from "./ModalShell";
import { resetPassword } from "../api";
import { useI18n } from "../i18n";
import { passwordProblem } from "../utils/passwordRules";

/**
 * Reset-link landing. The emailed link is `/?reset_token=<token>` (a query
 * param, because the SPA is state-routed with no router — same shape as
 * `?billing=success`). This is mounted globally at the app root and renders
 * nothing unless that param is present.
 *
 * The token is read once on mount and **immediately stripped from the URL**
 * (like BillingReturnHandler) — it's a single-use credential, so it must not
 * linger in the address bar, browser history, or a copy-pasted link.
 *
 * On success it does NOT log the user in (mirroring the backend, which
 * deliberately doesn't mint a session on reset) and dispatches `mealbot:logout`
 * to drop any stale logged-in UI — the reset revoked every session server-side,
 * so this browser's cookie, if any, is already dead.
 *
 * Self-contained light surface (explicit background + dark text) so it reads in
 * both OS colour schemes (.claude/rules/frontend.md).
 */
export function ResetPasswordModal() {
  // Read + strip the token exactly once, on first render.
  const [token, setToken] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("reset_token");
  });

  useEffect(() => {
    if (token === null) return;
    const params = new URLSearchParams(window.location.search);
    if (!params.has("reset_token")) return;
    params.delete("reset_token");
    const qs = params.toString();
    window.history.replaceState(
      null,
      "",
      window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash,
    );
    // token stays in component state; only the URL is scrubbed.
  }, [token]);

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();
  const { t } = useI18n();

  const problem = useMemo(() => passwordProblem(password), [password]);
  const mismatch = confirm.length > 0 && confirm !== password;

  if (token === null) return null;

  const close = () => setToken(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (problem || mismatch) return;
    setPending(true);
    setError(null);
    try {
      await resetPassword(token, password);
      setDone(true);
      // Every session was just revoked server-side; clear any stale UI state.
      window.dispatchEvent(new Event("mealbot:logout"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("auth.genericError"));
    } finally {
      setPending(false);
    }
  };

  return (
    <ModalShell onClose={close} ariaLabel={t("auth.reset.title")} zIndex={1300}>
      <div
        style={{
          backgroundColor: "#fff",
          color: "#1f2937",
          borderRadius: 12,
          padding: "1.5rem",
          width: "min(92vw, 420px)",
          boxShadow: "0 4px 24px rgba(0,0,0,0.25)",
          border: "1px solid #e5e7eb",
        }}
      >
        <h3 id={titleId} style={{ margin: "0 0 0.75rem 0", fontSize: "1.15rem" }}>
          {t("auth.reset.title")}
        </h3>

        {done ? (
          <>
            <p style={{ margin: "0 0 1.25rem 0", color: "#374151", fontSize: "0.95rem", lineHeight: 1.5 }}>
              {t("auth.reset.done")}
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button type="button" onClick={close} style={primaryBtn}>
                {t("auth.reset.signIn")}
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <input
              type="password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setError(null); }}
              placeholder={t("auth.reset.newPassword")}
              autoFocus
              autoComplete="new-password"
              style={inputStyle}
            />
            <input
              type="password"
              value={confirm}
              onChange={(e) => { setConfirm(e.target.value); setError(null); }}
              placeholder={t("auth.reset.confirmPassword")}
              autoComplete="new-password"
              style={inputStyle}
            />
            {/* Inline guidance: show the first unmet rule, or the mismatch.
                Each rule is a complete sentence of its own — see
                utils/passwordRules for why it cannot be a fragment. */}
            {password.length > 0 && problem && <p style={hintStyle}>{t(problem)}</p>}
            {mismatch && <p style={hintStyle}>{t("auth.password.mismatch")}</p>}
            {error && (
              <div role="alert" style={{ color: "#b91c1c", fontSize: "0.85rem", margin: "0 0 0.75rem 0" }}>
                {error}
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.25rem" }}>
              <button type="button" onClick={close} disabled={pending} style={secondaryBtn(pending)}>
                {t("auth.reset.cancel")}
              </button>
              <button
                type="submit"
                disabled={pending || password.length === 0 || problem !== null || mismatch}
                style={{ ...primaryBtn, opacity: pending ? 0.7 : 1 }}
              >
                {pending ? t("auth.reset.saving") : t("auth.reset.submit")}
              </button>
            </div>
          </form>
        )}
      </div>
    </ModalShell>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  padding: "0.5rem",
  marginBottom: "0.6rem",
  borderRadius: 6,
  border: "1px solid #d1d5db",
  fontSize: "0.95rem",
  backgroundColor: "#fff",
  color: "#111",
};

const hintStyle: React.CSSProperties = {
  margin: "0 0 0.6rem 0",
  color: "#6b7280",
  fontSize: "0.82rem",
};

const primaryBtn: React.CSSProperties = {
  padding: "0.45rem 1rem",
  fontSize: "0.9rem",
  backgroundColor: "#2563eb",
  color: "#fff",
  border: "none",
  borderRadius: 6,
  cursor: "pointer",
};

const secondaryBtn = (disabled: boolean): React.CSSProperties => ({
  padding: "0.45rem 1rem",
  fontSize: "0.9rem",
  backgroundColor: "#e5e7eb",
  color: "#333",
  border: "none",
  borderRadius: 6,
  cursor: disabled ? "default" : "pointer",
  opacity: disabled ? 0.6 : 1,
});
