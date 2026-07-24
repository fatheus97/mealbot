import { type CSSProperties, useState } from "react";
import { ModalShell } from "./ModalShell";
import { useSubmitFeedback } from "../hooks/useServerState";
import type { FeedbackKind } from "../types";

// Mirror the backend bounds (core.feedback_gate): the client gates the MIN so the
// user isn't bounced by a server 422, and caps the textarea at the MAX.
const MESSAGE_MIN_LEN = 10;
const MESSAGE_MAX_LEN = 4000;

const KIND_OPTIONS: { value: FeedbackKind; label: string }[] = [
  { value: "bug", label: "🐞 Something's broken" },
  { value: "feature", label: "💡 Idea / feature request" },
  { value: "other", label: "💬 Something else" },
];

/**
 * "Send feedback" modal — a logged-in user reports a bug or requests a feature.
 *
 * Self-contained light surface with an explicit dark text colour (per
 * .claude/rules/frontend.md: the app is dark-by-default via the Vite template, so a
 * white card must pin its own text colour to stay legible in OS dark mode).
 */
export function FeedbackModal({
  onClose,
  page,
}: {
  onClose: () => void;
  /** Optional coarse context (e.g. "settings") stored with the report. */
  page?: string;
}) {
  const submit = useSubmitFeedback();
  const [kind, setKind] = useState<FeedbackKind>("bug");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const trimmedLen = message.trim().length;
  const tooShort = trimmedLen < MESSAGE_MIN_LEN;

  function onSubmit(e: React.FormEvent): void {
    e.preventDefault();
    setError(null);
    submit.mutate(
      { kind, message: message.trim(), page: page ?? null },
      {
        onSuccess: () => setDone(true),
        onError: (err) =>
          setError(err instanceof Error ? err.message : "Could not send your feedback."),
      },
    );
  }

  return (
    <ModalShell onClose={onClose} ariaLabel="Send feedback" zIndex={1200}>
      <div style={card}>
        {done ? (
          <>
            <h3 style={heading}>Thanks — we got it. 🙏</h3>
            <p style={{ margin: "0 0 1.25rem", fontSize: 14, color: bodyColor }}>
              Your report is on its way to the team. We read every one.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button type="button" onClick={onClose} style={primaryBtn}>
                Done
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={onSubmit}>
            <h3 style={heading}>Send feedback</h3>
            <p style={{ margin: "0 0 1rem", fontSize: 13, color: mutedColor }}>
              Found a bug or have an idea? Tell us — it genuinely helps shape Mealbot.
            </p>

            <label style={labelStyle}>
              Type
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as FeedbackKind)}
                style={inputStyle}
              >
                {KIND_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>

            <label style={labelStyle}>
              Details
              <textarea
                value={message}
                onChange={(e) => {
                  setMessage(e.target.value);
                  setError(null);
                }}
                placeholder="What happened, or what would you like to see? The more detail, the better."
                rows={6}
                maxLength={MESSAGE_MAX_LEN}
                style={{ ...inputStyle, resize: "vertical", minHeight: 120 }}
              />
            </label>
            <div style={{ fontSize: 12, color: mutedColor, textAlign: "right", marginTop: -4 }}>
              {message.length}/{MESSAGE_MAX_LEN}
            </div>

            {error && (
              <div role="alert" style={bannerStyle}>
                {error}
              </div>
            )}

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: "0.5rem",
                marginTop: "1.25rem",
              }}
            >
              <button type="button" onClick={onClose} style={secondaryBtn}>
                Cancel
              </button>
              <button
                type="submit"
                disabled={submit.isPending || tooShort}
                title={tooShort ? "Please add a bit more detail." : undefined}
                style={{ ...primaryBtn, opacity: submit.isPending || tooShort ? 0.6 : 1 }}
              >
                {submit.isPending ? "Sending…" : "Send"}
              </button>
            </div>
          </form>
        )}
      </div>
    </ModalShell>
  );
}

// --- Styles (explicit light surface + dark text; see the component docstring) ---

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
  width: "min(92vw, 460px)",
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
  padding: "0.4rem 0.85rem",
  border: `1px solid ${border}`,
  borderRadius: 6,
  background: surface,
  color: textColor,
  cursor: "pointer",
  fontSize: 14,
};

const bannerStyle: CSSProperties = {
  padding: "0.5rem 0.75rem",
  borderRadius: 8,
  background: "#fef2f2",
  color: danger,
  border: "1px solid #fecaca",
  fontSize: 13,
  marginTop: "0.75rem",
};
