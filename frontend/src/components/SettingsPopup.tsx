import { useAuth } from "../contexts/AuthContext";
import { useUserProfile, useUpdateUserProfile } from "../hooks/useServerState";
import { PreferencesForm } from "./PreferencesForm";
import type { PreferencesFormValues } from "./PreferencesForm";

interface SettingsPopupProps {
  onClose: () => void;
}

export function SettingsPopup({ onClose }: SettingsPopupProps) {
  const { userId } = useAuth();
  const { data: profile, isLoading } = useUserProfile(userId);
  const mutation = useUpdateUserProfile();

  const handleSubmit = async (values: PreferencesFormValues) => {
    try {
      await mutation.mutateAsync({
        country: values.country || null,
        variability: values.variability,
        include_spices: values.include_spices,
      });
      onClose();
    } catch {
      alert("Failed to save preferences. Please try again.");
    }
  };

  return (
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
        if (e.target === e.currentTarget) onClose();
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
          onClick={onClose}
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

      {isLoading && <p>Loading...</p>}

      {profile && (
        <PreferencesForm
          initialValues={{
            country: profile.country ?? "",
            variability: profile.variability,
            include_spices: profile.include_spices,
          }}
          onSubmit={handleSubmit}
          submitLabel="Save"
          loading={mutation.isPending}
        />
      )}
    </div>
    </div>
  );
}
