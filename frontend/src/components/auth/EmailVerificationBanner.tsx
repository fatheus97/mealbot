import { useState, type CSSProperties } from "react";
import { useAuth } from "../../contexts/AuthContext";

/**
 * "Confirm your email" prompt for an unverified account.
 *
 * The server gates generation and checkout with a 403 (see
 * `deps.require_verified_email`), but that's the backstop — this banner is
 * what the user actually reacts to, driven off `email_verified` on the
 * profile, exactly as `SubscriptionBanner` is driven off `is_subscribed`
 * rather than off the 402.
 *
 * Renders nothing for verified users, logged-out visitors, and demo sessions
 * (a demo address is server-generated with no inbox to confirm — the profile
 * already reports those as verified).
 *
 * Theme-safety (.claude/rules/frontend.md): a self-contained opaque surface
 * with an explicit background AND an explicit contrasting colour, so it can't
 * land dark-on-dark in OS dark mode.
 */
export function EmailVerificationBanner() {
  const { userId, emailVerified, resendVerification } = useAuth();
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");

  if (!userId || emailVerified) return null;

  async function resend(): Promise<void> {
    setState("sending");
    try {
      await resendVerification();
      setState("sent");
    } catch {
      setState("error");
    }
  }

  return (
    <div role="status" style={wrap}>
      <span style={{ flex: "1 1 260px" }}>
        <strong>Confirm your email address</strong> to start generating plans. We've
        sent you a link — check your inbox (and spam).
      </span>
      {state === "sent" ? (
        // Deliberately not a disabled button: once sent, the useful thing to
        // say is "we sent it", and the 60s server cooldown would silently
        // swallow an immediate second press anyway.
        <span style={{ fontWeight: 600, whiteSpace: "nowrap" }}>Sent ✓</span>
      ) : (
        <button
          type="button"
          onClick={() => void resend()}
          disabled={state === "sending"}
          style={button}
        >
          {state === "sending" ? "Sending…" : "Resend link"}
        </button>
      )}
      {state === "error" && (
        <span style={{ flexBasis: "100%", fontSize: "0.85rem" }}>
          Couldn't resend just now — please try again in a minute.
        </span>
      )}
    </div>
  );
}

// Explicit background + explicit colour, together (the white-on-white rule).
const wrap: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "0.75rem",
  flexWrap: "wrap",
  backgroundColor: "#fef3c7",
  color: "#78350f",
  border: "1px solid #fcd34d",
  borderRadius: 8,
  padding: "0.7rem 0.9rem",
  marginBottom: "1rem",
  fontSize: "0.9rem",
};

const button: CSSProperties = {
  padding: "0.4rem 0.85rem",
  borderRadius: 6,
  border: "1px solid #b45309",
  backgroundColor: "#b45309",
  color: "#ffffff",
  cursor: "pointer",
  fontSize: "0.85rem",
  fontWeight: 600,
  whiteSpace: "nowrap",
};
