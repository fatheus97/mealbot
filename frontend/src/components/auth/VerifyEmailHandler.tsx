import { useEffect, useRef, useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { verifyEmail } from "../../api";

type Phase = "idle" | "working" | "done" | "failed";

/**
 * Consumes `?verify_token=…` from the confirmation email.
 *
 * Same shape as `ResetPasswordModal` / `BillingReturnHandler`: a global
 * param-handler mounted once at the app root, which strips the marker from the
 * URL so a reload can't replay it (and so the token doesn't linger in history
 * or get pasted into a bug report).
 *
 * Works logged-OUT as well as logged-in — the backend endpoint is
 * unauthenticated because these links are routinely opened in a different
 * browser (a phone mail client) from the one that registered. When the visitor
 * IS logged in we refresh the profile so the banner disappears immediately
 * rather than after the next reload.
 */
export function VerifyEmailHandler() {
  const { userId, refreshProfile } = useAuth();
  const [phase, setPhase] = useState<Phase>("idle");
  // StrictMode double-invokes effects in dev, and the token is single-use —
  // without this latch the second run redeems an already-used token and shows
  // a spurious failure on a confirmation that actually worked.
  const startedRef = useRef(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("verify_token");
    if (!token || startedRef.current) return;
    startedRef.current = true;

    params.delete("verify_token");
    const qs = params.toString();
    window.history.replaceState(
      null,
      "",
      window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash,
    );

    setPhase("working");
    verifyEmail(token)
      .then(() => {
        setPhase("done");
        // Only meaningful when this browser is the logged-in one; harmless
        // otherwise (refreshProfile swallows its own failures).
        if (userId) void refreshProfile();
      })
      .catch(() => setPhase("failed"));
    // Deliberately once-on-mount: the URL is read a single time, and re-running
    // on a userId change would re-redeem a token already stripped from the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (phase === "idle" || phase === "working") return null;

  const ok = phase === "done";
  return (
    <div
      role="status"
      style={{
        // Self-contained opaque surface with an explicit contrasting colour,
        // so it reads correctly in both OS colour schemes.
        backgroundColor: ok ? "#dcfce7" : "#fee2e2",
        color: ok ? "#166534" : "#991b1b",
        border: `1px solid ${ok ? "#86efac" : "#fecaca"}`,
        borderRadius: 8,
        padding: "0.7rem 0.9rem",
        marginBottom: "1rem",
        fontSize: "0.9rem",
      }}
    >
      {ok
        ? "✅ Email confirmed — you're all set."
        : "That confirmation link is invalid or has expired. Use “Resend link” below to get a new one."}
    </div>
  );
}
