import { type CSSProperties, useState } from "react";
import { ConfirmDialog } from "../ConfirmDialog";
import { usePolicyNotice, useSendPolicyNotice } from "../../hooks/useServerState";
import type { PolicyNoticePreview } from "../../types";
import { cardStyle, colors, radius } from "./theme";

const COUNT_LABELS: { key: keyof PolicyNoticePreview["counts"]; label: string; note: string }[] = [
  { key: "eligible", label: "Will get it", note: "on the next send" },
  { key: "sent", label: "Sent", note: "Resend accepted it" },
  { key: "accepted_in_app", label: "Agreed in app", note: "already informed, not emailed" },
  { key: "unconfirmed", label: "Unconfirmed", note: "a send died mid-way; never retried" },
  { key: "excluded", label: "Excluded", note: "deactivated or unconfirmed address" },
];

/**
 * The Notices admin tab: the email the Privacy Policy and Terms §12 promise on a
 * material change (backend services/policy_notice; the CLI
 * `app.scripts.send_policy_notice` runs the same rules).
 *
 * The preview IS the dry run: counts, quota, and the email exactly as each
 * locale's recipients get it, rendered in a sandboxed iframe (no scripts, no
 * same-origin) because it is a whole HTML document. Sending sends the shown
 * eligible count as the confirmation; if the audience changed meanwhile the
 * server refuses and says so, and the admin reviews again.
 */
export function NoticePanel() {
  const query = usePolicyNotice(true);
  const sendMut = useSendPolicyNotice();
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  if (query.isLoading) {
    return <div style={{ color: colors.textMuted, fontSize: 13 }}>Loading…</div>;
  }
  if (query.error || !query.data) {
    return (
      <div role="alert" style={{ color: colors.danger, fontSize: 13 }}>
        Failed to load the notice preview.{" "}
        {query.error instanceof Error ? query.error.message : ""}
      </div>
    );
  }

  const data = query.data;
  const eligible = data.counts.eligible;
  const remaining = Math.max(0, data.daily_limit - data.sent_last_24h);
  const willQueue = Math.min(eligible, remaining);
  const blocker = !data.email_configured
    ? "RESEND_API_KEY is not set on the server, so nothing can be sent."
    : eligible === 0
      ? "Nobody is waiting for this notice."
      : remaining === 0
        ? "Today's quota is used up. Try again within 24 hours."
        : null;

  function doSend(): void {
    setMessage(null);
    sendMut.mutate(eligible, {
      onSuccess: (res) => {
        setConfirming(false);
        setMessage({
          kind: "ok",
          text: `Queued ${res.queued}. They go out one per second; refresh to follow them.`,
        });
      },
      onError: (e) => {
        setConfirming(false);
        setMessage({ kind: "error", text: e instanceof Error ? e.message : "Could not send." });
      },
    });
  }

  return (
    <div>
      <p style={{ margin: "0 0 1rem", color: colors.textMuted, fontSize: 13, maxWidth: 640 }}>
        The email the Privacy Policy and Terms promise when a change is material. Campaign{" "}
        <code>{data.campaign}</code>. Each account gets it at most once, and users who already
        clicked "I agree" on the in-app banner are skipped.
      </p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: "0.75rem",
          marginBottom: "1rem",
        }}
      >
        {COUNT_LABELS.map(({ key, label, note }) => (
          <div key={key} style={cardStyle}>
            <div style={{ fontSize: 12, color: colors.textMuted }}>{label}</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: colors.text }}>
              {data.counts[key]}
            </div>
            <div style={{ fontSize: 12, color: colors.textMuted }}>{note}</div>
          </div>
        ))}
      </div>

      <p style={{ margin: "0 0 1rem", fontSize: 13, color: colors.textBody }}>
        Quota: {data.sent_last_24h} of {data.daily_limit} used in the last 24 hours (shared
        Resend key with password-reset mail).
      </p>

      {message && (
        <div role={message.kind === "error" ? "alert" : "status"} style={messageStyle[message.kind]}>
          {message.text}
        </div>
      )}

      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={() => setConfirming(true)}
          disabled={blocker !== null || sendMut.isPending}
          // Visibly inert when blocked: the reason sits right beside it, and a
          // full-strength accent button reads as clickable.
          style={blocker ? { ...primaryBtn, opacity: 0.5, cursor: "not-allowed" } : primaryBtn}
        >
          Send to {willQueue} {willQueue === 1 ? "user" : "users"}
        </button>
        <button type="button" onClick={() => void query.refetch()} style={secondaryBtn}>
          Refresh
        </button>
        {blocker && <span style={{ fontSize: 13, color: colors.textMuted }}>{blocker}</span>}
      </div>

      <h3 style={{ margin: "1.75rem 0 0.75rem", fontSize: "1rem", color: colors.text }}>
        What they will receive
      </h3>
      {data.previews.map((p) => (
        <div key={p.locale} style={{ ...cardStyle, marginBottom: "1rem" }}>
          <div style={{ fontSize: 13, color: colors.textBody, marginBottom: "0.5rem" }}>
            <strong>{p.locale}</strong> · Subject: {p.subject}
          </div>
          <iframe
            title={`Notice email preview (${p.locale})`}
            sandbox=""
            srcDoc={p.html}
            style={{
              width: "100%",
              height: 360,
              border: `1px solid ${colors.border}`,
              borderRadius: radius,
              background: "#ffffff",
              colorScheme: "light",
            }}
          />
        </div>
      ))}

      {confirming && (
        <ConfirmDialog
          title={`Email ${willQueue} ${willQueue === 1 ? "user" : "users"}?`}
          message={
            `Sends the notice above to ${willQueue} of ${eligible} eligible accounts` +
            (willQueue < eligible ? " (the rest once the daily quota allows)" : "") +
            ". This cannot be recalled."
          }
          confirmLabel="Send"
          // Admin stays English; pin the shared dialog's translated labels.
          cancelLabel="Cancel"
          loadingLabel="Sending…"
          onConfirm={doSend}
          onCancel={() => setConfirming(false)}
          loading={sendMut.isPending}
          destructive={false}
        />
      )}
    </div>
  );
}

const primaryBtn: CSSProperties = {
  padding: "0.45rem 0.9rem",
  border: "none",
  borderRadius: 6,
  background: colors.accent,
  color: "#ffffff",
  cursor: "pointer",
  fontSize: 14,
  fontWeight: 600,
};

const secondaryBtn: CSSProperties = {
  padding: "0.4rem 0.85rem",
  border: `1px solid ${colors.borderStrong}`,
  borderRadius: 6,
  background: colors.card,
  color: colors.text,
  cursor: "pointer",
  fontSize: 14,
};

const messageStyle: Record<"ok" | "error", CSSProperties> = {
  ok: {
    padding: "0.5rem 0.75rem",
    borderRadius: radius,
    background: "#ecfdf5",
    color: "#065f46",
    border: "1px solid #a7f3d0",
    fontSize: 13,
    marginBottom: "0.75rem",
  },
  error: {
    padding: "0.5rem 0.75rem",
    borderRadius: radius,
    background: "#fef2f2",
    color: colors.danger,
    border: "1px solid #fecaca",
    fontSize: 13,
    marginBottom: "0.75rem",
  },
};
