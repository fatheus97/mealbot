import { useEffect, useId, useMemo, useState } from "react";
import { ModalShell } from "./ModalShell";
import { useAuth } from "../contexts/AuthContext";
import { AutoLoginAfterRegisterError } from "../contexts/authErrors";
import { TermsConsent } from "./auth/TermsConsent";

/** Mirrors the backend rules (validate_password_complexity + the 8..128 length
 *  bounds) as an inline hint only; the server is the real gate. */
function passwordProblem(pw: string): string | null {
  if (pw.length < 8) return "at least 8 characters";
  if (pw.length > 128) return "to be 128 characters or fewer";
  if (!/[A-Z]/.test(pw)) return "an upper-case letter";
  if (!/[a-z]/.test(pw)) return "a lower-case letter";
  if (!/\d/.test(pw)) return "a digit";
  return null;
}

/**
 * Invite-link landing. An admin-generated link is `/?invite=<token>` (a query
 * param, because the SPA is state-routed with no router — same shape as
 * `?reset_token=`). Mounted globally at the app root; renders nothing unless the
 * param is present, so it works logged-in or out and is independent of AuthBar
 * and the `registrationEnabled` flag (the whole point — self-register while
 * public registration is closed).
 *
 * The token is read once on mount and **immediately stripped from the URL** (like
 * ResetPasswordModal) — it's a single-use credential, so it must not linger in
 * the address bar, browser history, or a copy-pasted link. On success the invitee
 * is auto-logged-in, so the modal just closes and the app renders the
 * authenticated UI.
 *
 * Self-contained light surface (explicit background + dark text) so it reads in
 * both OS colour schemes (.claude/rules/frontend.md).
 */
export function InviteRegisterModal() {
  const { registerViaInvite } = useAuth();

  // Read + strip the token exactly once, on first render.
  const [token, setToken] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get("invite"),
  );

  useEffect(() => {
    if (token === null) return;
    const params = new URLSearchParams(window.location.search);
    if (!params.has("invite")) return;
    params.delete("invite");
    const qs = params.toString();
    window.history.replaceState(
      null,
      "",
      window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash,
    );
    // token stays in component state; only the URL is scrubbed.
  }, [token]);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [acceptTerms, setAcceptTerms] = useState(false);
  const titleId = useId();

  const problem = useMemo(() => passwordProblem(password), [password]);
  const mismatch = confirm.length > 0 && confirm !== password;
  const emailOk = /.+@.+\..+/.test(email);

  if (token === null) return null;

  const close = () => setToken(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (problem || mismatch || !emailOk || !acceptTerms) return;
    setPending(true);
    setError(null);
    try {
      await registerViaInvite(token, email.trim(), password, acceptTerms);
      // Auto-logged-in — close; the app now renders the authenticated UI.
      setToken(null);
    } catch (err) {
      if (err instanceof AutoLoginAfterRegisterError) {
        // Account created but the auto-login leg failed — send them to sign in
        // rather than letting them retry and hit a 409 on a taken email.
        setNeedsSignIn(true);
      } else {
        setError(err instanceof Error ? err.message : "Something went wrong.");
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <ModalShell onClose={close} ariaLabel="Create your account" zIndex={1300}>
      <div style={cardStyle}>
        <h3 id={titleId} style={{ margin: "0 0 0.75rem 0", fontSize: "1.15rem" }}>
          Create your account
        </h3>

        {needsSignIn ? (
          <>
            <p style={bodyText}>
              Your account was created, but we couldn't sign you in automatically.
              Please sign in with the email and password you just chose.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button type="button" onClick={close} style={primaryBtn}>
                Sign in
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <p style={{ ...bodyText, marginBottom: "0.75rem" }}>
              You've been invited to Mealbot. Choose your login details below.
            </p>
            <input
              type="email"
              value={email}
              onChange={(e) => { setEmail(e.target.value); setError(null); }}
              placeholder="Email"
              autoFocus
              autoComplete="email"
              style={inputStyle}
            />
            <input
              type="password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setError(null); }}
              placeholder="Password"
              autoComplete="new-password"
              style={inputStyle}
            />
            <input
              type="password"
              value={confirm}
              onChange={(e) => { setConfirm(e.target.value); setError(null); }}
              placeholder="Confirm password"
              autoComplete="new-password"
              style={inputStyle}
            />
            <div style={{ margin: "0 0 0.75rem 0" }}>
              <TermsConsent
                id="invite-accept-terms"
                checked={acceptTerms}
                onChange={(next) => { setAcceptTerms(next); setError(null); }}
                disabled={pending}
              />
            </div>
            {password.length > 0 && problem && <p style={hintStyle}>Password needs {problem}.</p>}
            {mismatch && <p style={hintStyle}>Passwords don't match.</p>}
            {error && (
              <div role="alert" style={{ color: "#b91c1c", fontSize: "0.85rem", margin: "0 0 0.75rem 0" }}>
                {error}
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.25rem" }}>
              <button type="button" onClick={close} disabled={pending} style={secondaryBtn(pending)}>
                Cancel
              </button>
              <button
                type="submit"
                disabled={pending || !emailOk || password.length === 0 || problem !== null || mismatch || !acceptTerms}
                style={{ ...primaryBtn, opacity: pending ? 0.7 : 1 }}
              >
                {pending ? "Creating…" : "Create account"}
              </button>
            </div>
          </form>
        )}
      </div>
    </ModalShell>
  );
}

const cardStyle: React.CSSProperties = {
  backgroundColor: "#fff",
  color: "#1f2937",
  borderRadius: 12,
  padding: "1.5rem",
  width: "min(92vw, 420px)",
  boxShadow: "0 4px 24px rgba(0,0,0,0.25)",
  border: "1px solid #e5e7eb",
};

const bodyText: React.CSSProperties = {
  margin: "0 0 1rem 0",
  color: "#374151",
  fontSize: "0.95rem",
  lineHeight: 1.5,
};

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
