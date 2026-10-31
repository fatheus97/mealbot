import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useUpdateUserProfile, useUserProfile } from "../hooks/useServerState";
import { PreferencesForm } from "./PreferencesForm";
import { useI18n, type TranslationKey } from "../i18n";
import { preferencesFromProfile } from "../utils/preferences";
import type { PreferencesFormValues } from "./PreferencesForm";

export function OnboardingModal() {
  const { userId, setOnboardingCompleted } = useAuth();
  const { t } = useI18n();
  // The form is seeded from the saved profile (see preferencesFromProfile for
  // why defaults are wrong here) and waits for it: PreferencesForm reads
  // initialValues once, on mount, so a form painted with defaults while the
  // profile loads would keep them after it arrives.
  const { data: profile, isError, refetch } = useUserProfile(userId);
  const mutation = useUpdateUserProfile();
  // The KEY, not the sentence: an error already translated cannot follow a
  // later language switch. See AuthBar for the same shape.
  const [saveError, setSaveError] = useState<TranslationKey | null>(null);

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
        need_to_use_enabled: values.need_to_use_enabled,
        waste_tracking_enabled: values.waste_tracking_enabled,
        default_day_layout: values.default_day_layout,
        onboarding_completed: true,
      });
      setOnboardingCompleted(true);
    } catch {
      setSaveError("settings.saveFailed");
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.6)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        style={{
          backgroundColor: "white",
          color: "#111",
          borderRadius: "12px",
          padding: "2rem",
          maxWidth: "480px",
          width: "90%",
          maxHeight: "90vh",
          overflowY: "auto",
          boxShadow: "0 8px 32px rgba(0,0,0,0.3)",
        }}
      >
        <h2 style={{ marginTop: 0, marginBottom: "0.25rem" }}>{t("onboarding.title")}</h2>
        <p style={{ color: "#666", marginTop: 0, marginBottom: "1.5rem" }}>
          {t("onboarding.subtitle")}
        </p>
        {profile ? (
          <PreferencesForm
            initialValues={preferencesFromProfile(profile)}
            onSubmit={handleSubmit}
            submitLabel={t("onboarding.submit")}
            loading={mutation.isPending}
          />
        ) : isError ? (
          // No defaults form as a fallback: for a returning user that is the
          // overwrite this component exists to prevent. The modal has no close,
          // so a retry is the only way on.
          <div>
            <p role="alert" style={{ marginTop: 0, color: "#b91c1c", fontSize: "0.9rem" }}>
              {t("onboarding.loadFailed")}
            </p>
            <button
              type="button"
              onClick={() => void refetch()}
              style={{
                padding: "0.4rem 0.75rem",
                border: "1px solid #d1d5db",
                borderRadius: 6,
                background: "#f9fafb",
                color: "#111827",
                cursor: "pointer",
              }}
            >
              {t("onboarding.retry")}
            </button>
          </div>
        ) : (
          <p>{t("settings.loading")}</p>
        )}
        {saveError && (
          <p role="alert" style={{ marginTop: "0.75rem", marginBottom: 0, color: "#b91c1c", fontSize: "0.9rem" }}>
            {t(saveError)}
          </p>
        )}
      </div>
    </div>
  );
}
