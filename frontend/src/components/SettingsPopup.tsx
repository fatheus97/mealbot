import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useUserProfile, useUpdateUserProfile } from "../hooks/useServerState";
import { PreferencesForm } from "./PreferencesForm";
import type { PreferencesFormValues } from "./PreferencesForm";
import { PantryStaples } from "./PantryStaples";
import { FeedbackModal } from "./FeedbackModal";
import { InfoHint } from "./InfoHint";

interface SettingsPopupProps {
  onClose: () => void;
}

export function SettingsPopup({ onClose }: SettingsPopupProps) {
  const { userId } = useAuth();
  const { data: profile, isLoading } = useUserProfile(userId);
  const mutation = useUpdateUserProfile();
  const [saveError, setSaveError] = useState<string | null>(null);
  const [staplesDirty, setStaplesDirty] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [showFeedback, setShowFeedback] = useState(false);

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
        include_spices: values.include_spices,
        track_snacks: values.track_snacks,
        // Send the raw array (possibly []). The backend treats [] as "clear"
        // and a populated list as the new stored layout.
        default_day_layout: values.default_day_layout,
      });
      requestClose();
    } catch {
      setSaveError("Failed to save preferences. Please try again.");
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
        <h3 style={{ margin: 0 }}>Settings</h3>
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
          aria-label="Close settings"
        >
          ✕
        </button>
      </div>

      {confirmDiscard && (
        <div
          role="alertdialog"
          aria-label="Discard unsaved pantry staples"
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
            You have unsaved pantry staples. Discard them?
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
              Discard &amp; close
            </button>
            <button
              type="button"
              onClick={() => setConfirmDiscard(false)}
              style={{ padding: "0.35rem 0.75rem", border: "1px solid #94a3b8", borderRadius: 6, background: "#fff", color: "#111", cursor: "pointer", fontSize: "0.85rem" }}
            >
              Keep editing
            </button>
          </div>
        </div>
      )}

      {isLoading && <p>Loading...</p>}

      {profile && (
        <PreferencesForm
          initialValues={{
            country: profile.country ?? "",
            language: profile.language,
            variability: profile.variability,
            include_spices: profile.include_spices,
            show_pieces: profile.show_pieces,
            track_snacks: profile.track_snacks,
            default_day_layout: profile.default_day_layout ?? [],
          }}
          onSubmit={handleSubmit}
          submitLabel="Save preferences"
          loading={mutation.isPending}
        />
      )}
      {saveError && (
        <p role="alert" style={{ marginTop: "0.75rem", marginBottom: 0, color: "#b91c1c", fontSize: "0.9rem" }}>
          {saveError}
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
          💬 Send feedback
        </button>
        <InfoHint
          label="How feedback credit works"
          text="Earn €1 off for every accepted bug report or feature request — up to €3/month. It shows up as a “Feedback reward” credit on your next invoice, so you'll need to be on the monthly plan (subscribed or on a free trial) to receive it — annual plans are already discounted."
        />
      </div>
    </div>
    </div>
    {showFeedback && (
      <FeedbackModal page="settings" onClose={() => setShowFeedback(false)} />
    )}
    </>
  );
}
