import { type CSSProperties, useRef, useState } from "react";
import { ModalShell } from "./ModalShell";
import { useSubmitFeedback } from "../hooks/useServerState";
import type { FeedbackKind, FeedbackScreenshotContentType } from "../types";
import { useI18n } from "../i18n";

// Mirror the backend bounds (core.feedback_gate): the client gates the MIN so the
// user isn't bounced by a server 422, and caps the textarea at the MAX.
const MESSAGE_MIN_LEN = 10;
const MESSAGE_MAX_LEN = 4000;

const KIND_OPTIONS: FeedbackKind[] = ["bug", "feature", "other"];

// Mirrors the backend bounds (feedback_schemas.MAX_SCREENSHOT_BYTES / the
// FeedbackScreenshotContentType literal) so a rejected file never leaves the
// client to bounce off a 422 — same reasoning as MESSAGE_MIN_LEN above.
const MAX_SCREENSHOT_BYTES = 3 * 1024 * 1024;
const ALLOWED_SCREENSHOT_TYPES = new Set<string>(["image/png", "image/jpeg"]);

interface Screenshot {
  base64: string;
  contentType: FeedbackScreenshotContentType;
  previewUrl: string;
}

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
  const [screenshot, setScreenshot] = useState<Screenshot | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const trimmedLen = message.trim().length;
  const tooShort = trimmedLen < MESSAGE_MIN_LEN;

  function attachFile(file: File): void {
    if (!ALLOWED_SCREENSHOT_TYPES.has(file.type)) {
      setError(t("feedback.screenshotUnsupportedType"));
      return;
    }
    if (file.size > MAX_SCREENSHOT_BYTES) {
      setError(t("feedback.screenshotTooLarge"));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      // readAsDataURL always yields "data:<type>;base64,<data>" for a Blob.
      const base64 = String(reader.result).split(",")[1] ?? "";
      setScreenshot({
        base64,
        contentType: file.type as FeedbackScreenshotContentType,
        previewUrl: String(reader.result),
      });
      setError(null);
    };
    reader.readAsDataURL(file);
  }

  function onPaste(e: React.ClipboardEvent): void {
    const item = Array.from(e.clipboardData.items).find((i) => i.type.startsWith("image/"));
    if (!item) return;
    const file = item.getAsFile();
    if (!file) return;
    // Otherwise the browser also inserts the image's filename as text.
    e.preventDefault();
    attachFile(file);
  }

  function removeScreenshot(): void {
    setScreenshot(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function onSubmit(e: React.FormEvent): void {
    e.preventDefault();
    setError(null);
    submit.mutate(
      {
        kind,
        message: message.trim(),
        page: page ?? null,
        screenshot_base64: screenshot?.base64 ?? null,
        screenshot_content_type: screenshot?.contentType ?? null,
      },
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
                onPaste={onPaste}
                placeholder={t("feedback.detailsPlaceholder")}
                rows={6}
                maxLength={MESSAGE_MAX_LEN}
                style={{ ...inputStyle, resize: "vertical", minHeight: 120 }}
              />
            </label>
            <div style={{ fontSize: 12, color: mutedColor, textAlign: "right", marginTop: -4 }}>
              {message.length}/{MESSAGE_MAX_LEN}
            </div>

            <div style={{ marginTop: "0.5rem" }}>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg"
                aria-label={t("feedback.attachScreenshot")}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) attachFile(file);
                }}
                style={{ display: "none" }}
              />
              {screenshot ? (
                <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                  <img
                    src={screenshot.previewUrl}
                    alt={t("feedback.screenshotAlt")}
                    style={{
                      height: 48,
                      width: 48,
                      objectFit: "cover",
                      borderRadius: 6,
                      border: `1px solid ${border}`,
                    }}
                  />
                  <button type="button" onClick={removeScreenshot} style={secondaryBtn}>
                    {t("feedback.removeScreenshot")}
                  </button>
                </div>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    style={secondaryBtn}
                  >
                    {t("feedback.attachScreenshot")}
                  </button>
                  <p style={{ margin: "0.4rem 0 0", fontSize: 12, color: mutedColor }}>
                    {t("feedback.pasteHint")}
                  </p>
                </>
              )}
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
