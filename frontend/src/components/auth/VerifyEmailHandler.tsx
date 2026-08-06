import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { verifyEmail } from "../../api";
import { useI18n } from "../../i18n";

type Phase = "idle" | "working" | "done" | "failed";

/**
 * Consumes `?verify_token=…` from the confirmation email.
 *
 * Mounted at the APP ROOT (see App.tsx), deliberately not inside MainLayout:
 * that subtree is keyed by userId, so a login — or just the bootstrap /users
 * call resolving — remounts it. Since the effect strips the token from the URL
 * on its first run, a remount would find nothing and silently discard the
 * result of a redemption that already burned the single-use token.
 *
 * `position: fixed` for the same reason it lives at the root: it renders
 * outside the page container, and floating it keeps it out of document flow so
 * an async message can't shove the page down under the user's cursor (the CLS
 * rule in .claude/rules/frontend.md).
 *
 * Works logged-OUT as well as logged-in — the backend endpoint is
 * unauthenticated because these links are routinely opened in a different
 * browser (a phone mail client) from the one that registered.
 */
export function VerifyEmailHandler() {
  const { userId, emailVerified, refreshProfile } = useAuth();
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>("idle");
  const [dismissed, setDismissed] = useState(false);
  // Belt-and-braces against a double redeem of a single-use token under
  // StrictMode's dev double-invoke. Honest caveat: the primary guard is the
  // SYNCHRONOUS replaceState below, which removes the token before the second
  // invocation reads the URL — removing this latch does not reproduce a double
  // redeem in tests, even with replaceState stubbed out. Kept because it costs
  // nothing and the failure mode (reporting failure for a confirmation that
  // worked, on a token already burned) is user-visible and unrecoverable
  // without a resend. Deliberately uncovered; see the note in the test file.
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
        // Only meaningful when this browser holds the session; harmless
        // otherwise (refreshProfile swallows its own failures).
        if (userId) void refreshProfile();
      })
      .catch(() => setPhase("failed"));
    // Once on mount by design: the URL is read a single time and the token is
    // stripped immediately, so re-running on a userId change could only ever
    // find nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (phase === "idle" || phase === "working" || dismissed) return null;

  const ok = phase === "done";
  // A 400 for someone who is already verified means they clicked the same link
  // twice — reporting that as an error would be alarming and wrong.
  const alreadyDone = !ok && userId !== null && emailVerified;
  const success = ok || alreadyDone;

  return (
    <div
      // Failures are announced assertively: this is the only thing telling the
      // user their confirmation didn't work.
      role={success ? "status" : "alert"}
      style={{ ...toast, ...(success ? successSkin : errorSkin) }}
    >
      <span>
        {ok
          ? t("verifyToast.confirmed")
          : alreadyDone
            ? t("verifyToast.alreadyUsed")
            : userId
              ? t("verifyToast.invalid")
              : // Logged out, so EmailVerificationBanner (which owns the Resend
                // control) renders nothing — point at what IS on screen.
                t("verifyToast.invalidLoggedOut")}
      </span>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label={t("verifyToast.dismiss")}
        style={close}
      >
        &times;
      </button>
    </div>
  );
}

// Floated, so it can't shift the page; self-contained opaque surface with an
// explicit background AND colour, so it reads in both OS colour schemes.
const toast: CSSProperties = {
  position: "fixed",
  top: "1rem",
  left: "50%",
  transform: "translateX(-50%)",
  zIndex: 1400,
  maxWidth: "min(520px, calc(100vw - 2rem))",
  display: "flex",
  alignItems: "flex-start",
  gap: "0.75rem",
  borderRadius: 8,
  padding: "0.7rem 0.9rem",
  fontSize: "0.9rem",
  boxShadow: "0 2px 12px rgba(0, 0, 0, 0.25)",
};

const successSkin: CSSProperties = {
  backgroundColor: "#dcfce7",
  color: "#166534",
  border: "1px solid #86efac",
};

const errorSkin: CSSProperties = {
  backgroundColor: "#fee2e2",
  color: "#991b1b",
  border: "1px solid #fecaca",
};

const close: CSSProperties = {
  background: "none",
  border: "none",
  color: "inherit",
  fontSize: "1.2rem",
  lineHeight: 1,
  cursor: "pointer",
  padding: "0 0.2rem",
};
