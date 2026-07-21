import { useId, useState } from "react";
import { ModalShell } from "./ModalShell";
import { requestPasswordReset } from "../api";

/**
 * "Forgot your password?" flow. Enter an email → POST /auth/forgot-password.
 *
 * **Non-enumeration is a UI requirement, not just a backend one.** The endpoint
 * returns 204 for unknown and demo addresses exactly as it does for real ones,
 * and this component mirrors that: on success it shows a neutral "if an account
 * exists, we've sent a link" message that reveals nothing about whether the
 * address is registered. It must NOT be changed to say "sent!" vs "no such
 * user" — that would hand back the oracle the backend closes.
 *
 * The card is a self-contained light surface (explicit background + dark text)
 * so it reads correctly in both OS colour schemes (.claude/rules/frontend.md).
 */
export function ForgotPasswordModal({
  onClose,
  initialEmail = "",
}: {
  onClose: () => void;
  initialEmail?: string;
}) {
  const [email, setEmail] = useState(initialEmail);
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      await requestPasswordReset(email);
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setPending(false);
    }
  };

  return (
    <ModalShell onClose={onClose} ariaLabel="Reset your password" zIndex={1200}>
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
          Reset your password
        </h3>

        {sent ? (
          <>
            <p style={{ margin: "0 0 1.25rem 0", color: "#374151", fontSize: "0.95rem", lineHeight: 1.5 }}>
              If an account exists for <strong>{email}</strong>, we've sent it a
              link to reset the password. Check your inbox — and your spam
              folder, just in case. The link expires in 30 minutes.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button type="button" onClick={onClose} style={primaryBtn}>
                Done
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <p style={{ margin: "0 0 1rem 0", color: "#374151", fontSize: "0.95rem", lineHeight: 1.5 }}>
              Enter your email and we'll send you a link to set a new password.
            </p>
            <input
              type="email"
              value={email}
              onChange={(e) => { setEmail(e.target.value); setError(null); }}
              placeholder="you@example.com"
              autoFocus
              required
              autoComplete="email"
              style={{
                width: "100%",
                boxSizing: "border-box",
                padding: "0.5rem",
                marginBottom: "0.75rem",
                borderRadius: 6,
                border: "1px solid #d1d5db",
                fontSize: "0.95rem",
                backgroundColor: "#fff",
                color: "#111",
              }}
            />
            {error && (
              <div role="alert" style={{ color: "#b91c1c", fontSize: "0.85rem", marginBottom: "0.75rem" }}>
                {error}
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
              <button type="button" onClick={onClose} disabled={pending} style={secondaryBtn(pending)}>
                Cancel
              </button>
              <button type="submit" disabled={pending || email.length === 0} style={primaryBtn}>
                {pending ? "Sending…" : "Send reset link"}
              </button>
            </div>
          </form>
        )}
      </div>
    </ModalShell>
  );
}

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
