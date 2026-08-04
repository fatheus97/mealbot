import { useState, type CSSProperties } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { ChangeEmailModal } from "./ChangeEmailModal";
import { useI18n } from "../../i18n";
import { Trans } from "../../i18n/Trans";

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
  const { userId, email, emailVerified, resendVerification } = useAuth();
  const { t } = useI18n();
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [changing, setChanging] = useState(false);

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
    // The modal is a SIBLING of the banner, not a child. role="status" is an
    // ARIA live region: anything mounted inside it gets announced as a status
    // update, so nesting a dialog there would make a screen reader read the
    // whole form out as if it were a notification, and fight the dialog's own
    // announcement.
    <>
    <div role="status" style={wrap}>
      <span style={{ flex: "1 1 260px" }}>
        {/* Naming the address is the whole point: a user who mistyped it at
            sign-up cannot otherwise tell why the link never arrived, and
            "check your inbox" reads as advice to wait longer.

            Both bold runs are holes in ONE sentence rather than separate keys:
            Czech continues "…adresu, abyste mohli…", so the clause after the
            first <strong> is not a standalone phrase. */}
        <Trans
          k="verify.body"
          nodes={{
            title: <strong>{t("verify.title")}</strong>,
            email: <strong>{email}</strong>,
          }}
        />
      </span>
      {state === "sent" ? (
        // Deliberately not a disabled button: once sent, the useful thing to
        // say is "we sent it", and the 60s server cooldown would silently
        // swallow an immediate second press anyway.
        <span style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{t("verify.sent")}</span>
      ) : (
        <button
          type="button"
          onClick={() => void resend()}
          disabled={state === "sending"}
          style={button}
        >
          {state === "sending" ? t("verify.sending") : t("verify.resend")}
        </button>
      )}
      {/* The escape hatch from the lockout: resending only ever re-mails the
          SAME address, so a user who mistyped it can press "Resend link" all
          day and never receive anything. */}
      <button type="button" onClick={() => setChanging(true)} style={linkButton}>
        {t("verify.wrongAddress")}
      </button>
      {state === "error" && (
        // role=alert: the surrounding region is a polite role=status, so a
        // failure announced inside it can be missed entirely.
        <span role="alert" style={{ flexBasis: "100%", fontSize: "0.85rem" }}>
          {t("verify.resendFailed")}
        </span>
      )}
    </div>
    {changing && <ChangeEmailModal onClose={() => setChanging(false)} />}
    </>
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

// Text-styled but a real <button>: it opens a dialog, not a navigation, and an
// <a href="#"> would announce as a link to a screen reader. Colour is pinned to
// the banner's own foreground, which is explicit, so it cannot go
// dark-on-dark — the surface it sits on sets both background and colour.
const linkButton: CSSProperties = {
  background: "none",
  border: "none",
  padding: 0,
  color: "#78350f",
  textDecoration: "underline",
  cursor: "pointer",
  fontSize: "0.85rem",
  fontFamily: "inherit",
  whiteSpace: "nowrap",
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
