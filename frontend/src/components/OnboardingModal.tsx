import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useUpdateUserProfile } from "../hooks/useServerState";
import { PreferencesForm } from "./PreferencesForm";
import { useI18n, type TranslationKey } from "../i18n";
import type { PreferencesFormValues } from "./PreferencesForm";

export function OnboardingModal() {
  const { setOnboardingCompleted } = useAuth();
  const { t } = useI18n();
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
        <PreferencesForm
          initialValues={{
            country: "",
            language: "English",
            variability: "traditional",
            measurement_system: "metric",
            include_spices: true,
            show_pieces: false,
            track_snacks: true,
            need_to_use_enabled: true,
            // Opt-in: onboarding shows the checkbox unticked rather than enrolling a
            // brand-new user into being asked a question they have no context for.
            waste_tracking_enabled: false,
            default_day_layout: [],
          }}
          onSubmit={handleSubmit}
          submitLabel={t("onboarding.submit")}
          loading={mutation.isPending}
        />
        {saveError && (
          <p role="alert" style={{ marginTop: "0.75rem", marginBottom: 0, color: "#b91c1c", fontSize: "0.9rem" }}>
            {t(saveError)}
          </p>
        )}
      </div>
    </div>
  );
}
