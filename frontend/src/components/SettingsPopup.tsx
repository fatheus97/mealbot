import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useUserProfile, useUpdateUserProfile } from "../hooks/useServerState";
import { PreferencesForm } from "./PreferencesForm";
import type { PreferencesFormValues } from "./PreferencesForm";
import { PantryStaples } from "./PantryStaples";
import { FeedbackModal } from "./FeedbackModal";
import { ChangeEmailModal } from "./auth/ChangeEmailModal";
import { InfoHint } from "./InfoHint";
import { useI18n, type TranslationKey } from "../i18n";

interface SettingsPopupProps {
  onClose: () => void;
}

export function SettingsPopup({ onClose }: SettingsPopupProps) {
  const { userId, email, isDemo } = useAuth();
  const { t } = useI18n();
  const { data: profile, isLoading } = useUserProfile(userId);
  const mutation = useUpdateUserProfile();
  // The KEY, not the sentence: an error already translated cannot follow a
  // later language switch. See AuthBar for the same shape.
  const [saveError, setSaveError] = useState<TranslationKey | null>(null);
  const [staplesDirty, setStaplesDirty] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [showFeedback, setShowFeedback] = useState(false);
  const [showChangeEmail, setShowChangeEmail] = useState(false);

  // Guard every close path (✕, backdrop, and a successful preferences save)
  // against silently dropping unsaved pantry-staple edits — staples have their
  // own separate save, so a plain close would lose them without warning.
  const requestClose = () => {
    if (staplesDirty) setConfirmDiscard(true);
    else onClose();
  };

  const handleSubmit = async (values: PreferencesFormValues) => {
    setSaveError(null);
    try {
      await mutation.mutateAsync({
        country: values.country || null,
        language: values.language,
        variability: values.variability,
        measurement_system: values.measurement_system,
        include_spices: values.include_spices,
        show_pieces: values.show_pieces,
        track_snacks: values.track_snacks,
        // Send the raw array (possibly []). The backend treats [] as "clear"
        // and a populated list as the new stored layout.
        default_day_layout: values.default_day_layout,
      });
      requestClose();
    } catch {
      setSaveError("settings.saveFailed");
    }
  };

  return (
    <>
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.3)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) requestClose();
      }}
    >
    <div
      style={{
        backgroundColor: "white",
        color: "#111",
        borderRadius: "10px",
        padding: "1.5rem",
        width: "360px",
        maxHeight: "90vh",
        overflowY: "auto",
        boxShadow: "0 4px 24px rgba(0,0,0,0.15)",
        border: "1px solid #e0e0e0",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h3 style={{ margin: 0 }}>{t("settings.title")}</h3>
        <button
          onClick={requestClose}
          style={{
            background: "none",
            border: "none",
            fontSize: "1.25rem",
            cursor: "pointer",
            color: "#666",
            padding: "0.25rem",
          }}
          aria-label={t("settings.close")}
        >
          ✕
        </button>
      </div>

      {confirmDiscard && (
        <div
          role="alertdialog"
          aria-label={t("settings.discardTitle")}
          style={{
            border: "1px solid #f59e0b",
            background: "#fffbeb",
            color: "#111",
            borderRadius: 8,
            padding: "0.6rem 0.75rem",
            marginBottom: "1rem",
            fontSize: "0.9rem",
          }}
        >
          <p style={{ margin: "0 0 0.5rem" }}>
            {t("settings.discardBody")}
          </p>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button
              type="button"
              onClick={() => {
                setConfirmDiscard(false);
                onClose();
              }}
              style={{ padding: "0.35rem 0.75rem", border: "none", borderRadius: 6, background: "#dc2626", color: "#fff", cursor: "pointer", fontSize: "0.85rem" }}
            >
              {t("settings.discardConfirm")}
            </button>
            <button
              type="button"
              onClick={() => setConfirmDiscard(false)}
              style={{ padding: "0.35rem 0.75rem", border: "1px solid #94a3b8", borderRadius: 6, background: "#fff", color: "#111", cursor: "pointer", fontSize: "0.85rem" }}
            >
              {t("settings.discardCancel")}
            </button>
          </div>
        </div>
      )}

      {isLoading && <p>{t("settings.loading")}</p>}

      {profile && (
        <PreferencesForm
          initialValues={{
            country: profile.country ?? "",
            language: profile.language,
            variability: profile.variability,
            measurement_system: profile.measurement_system ?? "metric",
            include_spices: profile.include_spices,
            // ?? false like the billing fields: a payload cached before this field
            // existed would otherwise send undefined and look like a no-op save.
            show_pieces: profile.show_pieces ?? false,
            track_snacks: profile.track_snacks,
            default_day_layout: profile.default_day_layout ?? [],
          }}
          onSubmit={handleSubmit}
          submitLabel={t("settings.save")}
          loading={mutation.isPending}
        />
      )}
      {saveError && (
        <p role="alert" style={{ marginTop: "0.75rem", marginBottom: 0, color: "#b91c1c", fontSize: "0.9rem" }}>
          {t(saveError)}
        </p>
      )}

      {/* Pantry staples sits here, beside "Include spices", so both shopping-list
          exclusion controls live in one place. It keeps its own save (separate
          PUT /api/staples), independent of the preferences form's combined save.
          Gated on !isLoading so it paints WITH the form rather than jumping down
          when the (possibly cold-cache) profile resolves — the #270 CLS guardrail. */}
      {!isLoading && (
        <div style={{ marginTop: "1.25rem" }}>
          <PantryStaples onDirtyChange={setStaplesDirty} />
        </div>
      )}

      {/* Account address. Also reachable from the confirm-your-email banner, but
          that banner only renders for UNVERIFIED users — a verified user who
          loses access to their inbox has exactly the same problem and nothing to
          click, so the entry point has to exist here too.

          Hidden for demo sessions: the address is server-generated, the account
          is deleted within hours, and the endpoint refuses them with a 403 — so
          the control could only ever fail. */}
      {!isDemo && (
      <div
        style={{
          marginTop: "1.25rem",
          borderTop: "1px solid #e5e7eb",
          paddingTop: "1rem",
        }}
      >
        <div style={{ fontSize: 13, color: "#6b7280", marginBottom: "0.4rem" }}>
          {t("settings.emailAddress")}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "0.75rem",
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontSize: 14, color: "#111827", wordBreak: "break-all" }}>
            {email}
          </span>
          <button
            type="button"
            onClick={() => setShowChangeEmail(true)}
            style={{
              padding: "0.4rem 0.75rem",
              border: "1px solid #d1d5db",
              borderRadius: 6,
              background: "#f9fafb",
              color: "#111827",
              cursor: "pointer",
              fontSize: 13,
              whiteSpace: "nowrap",
            }}
          >
            {t("settings.changeEmail")}
          </button>
        </div>
      </div>
      )}

      {/* Feedback entry point — a low-friction way for any logged-in user to report
          a bug or request a feature. Opens above this popup (higher z-index). */}
      <div
        style={{
          marginTop: "1.25rem",
          borderTop: "1px solid #e5e7eb",
          paddingTop: "1rem",
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
        }}
      >
        <button
          type="button"
          onClick={() => setShowFeedback(true)}
          style={{
            flex: 1,
            padding: "0.55rem 0.75rem",
            border: "1px solid #d1d5db",
            borderRadius: 6,
            background: "#f9fafb",
            color: "#111827",
            cursor: "pointer",
            fontSize: 14,
            fontWeight: 600,
          }}
        >
          {t("settings.sendFeedback")}
        </button>
        <InfoHint
          label={t("settings.feedbackHintLabel")}
          text={t("settings.feedbackHintText")}
        />
      </div>
    </div>
    </div>
    {showFeedback && (
      <FeedbackModal page="settings" onClose={() => setShowFeedback(false)} />
    )}
    {showChangeEmail && (
      <ChangeEmailModal onClose={() => setShowChangeEmail(false)} />
    )}
    </>
  );
}
