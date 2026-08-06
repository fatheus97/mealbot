import { type CSSProperties, useState } from "react";
import { ModalShell } from "./ModalShell";
import { useSubmitFeedback } from "../hooks/useServerState";
import type { FeedbackKind } from "../types";
import { useI18n } from "../i18n";

// Mirror the backend bounds (core.feedback_gate): the client gates the MIN so the
// user isn't bounced by a server 422, and caps the textarea at the MAX.
const MESSAGE_MIN_LEN = 10;
const MESSAGE_MAX_LEN = 4000;

const KIND_OPTIONS: FeedbackKind[] = ["bug", "feature", "other"];

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
  const { t } = useI18n();
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
          setError(err instanceof Error ? err.message : t("feedback.failed")),
      },
    );
  }

  return (
    <ModalShell onClose={onClose} ariaLabel={t("feedback.title")} zIndex={1200}>
      <div style={card}>
        {done ? (
          <>
            <h3 style={heading}>{t("feedback.thanksTitle")}</h3>
            <p style={{ margin: "0 0 1.25rem", fontSize: 14, color: bodyColor }}>
              {t("feedback.thanksBody")}
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button type="button" onClick={onClose} style={primaryBtn}>
                {t("feedback.done")}
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={onSubmit}>
            <h3 style={heading}>{t("feedback.title")}</h3>
            <p style={{ margin: "0 0 1rem", fontSize: 13, color: mutedColor }}>
              {t("feedback.intro")}
            </p>

            <label style={labelStyle}>
              {t("feedback.type")}
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as FeedbackKind)}
                style={inputStyle}
              >
                {KIND_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {t(`feedbackKind.${value}` as const)}
                  </option>
                ))}
              </select>
            </label>

            <label style={labelStyle}>
              {t("feedback.details")}
              <textarea
                value={message}
                onChange={(e) => {
                  setMessage(e.target.value);
                  setError(null);
                }}
                placeholder={t("feedback.detailsPlaceholder")}
                rows={6}
                maxLength={MESSAGE_MAX_LEN}
                style={{ ...inputStyle, resize: "vertical", minHeight: 120 }}
              />
            </label>
            <div style={{ fontSize: 12, color: mutedColor, textAlign: "right", marginTop: -4 }}>
              {message.length}/{MESSAGE_MAX_LEN}
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: "0.5rem",
                marginTop: "1.25rem",
              }}
            >
              <button type="button" onClick={onClose} style={secondaryBtn}>
                {t("feedback.cancel")}
              </button>
              <button
                type="submit"
                disabled={submit.isPending || tooShort}
                title={tooShort ? t("feedback.tooShort") : undefined}
                style={{ ...primaryBtn, opacity: submit.isPending || tooShort ? 0.6 : 1 }}
              >
                {submit.isPending ? t("feedback.sending") : t("feedback.send")}
              </button>
            </div>

            {/* Below the buttons so a failed submit grows the modal downward instead
                of shifting Send/Cancel under the cursor (CLS — see frontend.md). */}
            {error && (
              <div role="alert" style={bannerStyle}>
                {error}
              </div>
            )}
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
