import { useAuth } from "../contexts/AuthContext";
import { useUpdateUserProfile } from "../hooks/useServerState";
import { PreferencesForm } from "./PreferencesForm";
import type { PreferencesFormValues } from "./PreferencesForm";

export function OnboardingModal() {
  const { setOnboardingCompleted } = useAuth();
  const mutation = useUpdateUserProfile();

  const handleSubmit = async (values: PreferencesFormValues) => {
    try {
      await mutation.mutateAsync({
        country: values.country || null,
        variability: values.variability,
        include_spices: values.include_spices,
        track_snacks: values.track_snacks,
        onboarding_completed: true,
      });
      setOnboardingCompleted(true);
    } catch {
      alert("Failed to save preferences. Please try again.");
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
        <h2 style={{ marginTop: 0, marginBottom: "0.25rem" }}>Welcome! Set up your preferences</h2>
        <p style={{ color: "#666", marginTop: 0, marginBottom: "1.5rem" }}>
          These help us generate meal plans tailored to you.
        </p>
        <PreferencesForm
          initialValues={{ country: "", variability: "traditional", include_spices: true, track_snacks: true }}
          onSubmit={handleSubmit}
          submitLabel="Get Started"
          loading={mutation.isPending}
        />
      </div>
    </div>
  );
}
