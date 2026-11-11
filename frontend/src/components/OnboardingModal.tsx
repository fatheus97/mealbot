import { useId, useState, type CSSProperties } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../contexts/AuthContext";
import {
  useAnswerRestock,
  useFridge,
  useUpdateUserProfile,
  useUserProfile,
  type ShelfData,
} from "../hooks/useServerState";
import { PreferencesForm } from "./PreferencesForm";
import { useI18n, type TranslationKey } from "../i18n";
import { preferencesFromProfile } from "../utils/preferences";
import type { PreferencesFormValues } from "./PreferencesForm";
import type { RestockStatus, StockItem } from "../types";

// The stock step's buttons: PreferencesForm's submit look, and the retry
// button's colours at the same size.
const primaryButton: CSSProperties = {
  padding: "0.6rem 1.5rem",
  fontSize: "1rem",
  backgroundColor: "#2563eb",
  color: "white",
  border: "none",
  borderRadius: 6,
  cursor: "pointer",
};
const secondaryButton: CSSProperties = {
  padding: "0.6rem 1.5rem",
  fontSize: "1rem",
  background: "#f9fafb",
  color: "#111827",
  border: "1px solid #d1d5db",
  borderRadius: 6,
  cursor: "pointer",
};

/**
 * First-run setup: the preferences, then, for an empty fridge, an offer to
 * stock it (docs/restock-design.md, "First run"). The offer only opens
 * MainLayout's RestockDialog through `onStartRestock`. The dialog must not
 * render in here: this modal unmounts on any profile re-read once the PATCH
 * has landed (a 403 triggers one), and that would drop paid scans.
 */
export function OnboardingModal({ onStartRestock }: { onStartRestock: () => void }) {
  const { userId, setOnboardingCompleted, emailVerified } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  // The form is seeded from the saved profile (see preferencesFromProfile for
  // why defaults are wrong here) and waits for it: PreferencesForm reads
  // initialValues once, on mount, so a form painted with defaults while the
  // profile loads would keep them after it arrives.
  const { data: profile, isError, refetch } = useUserProfile(userId);
  // Observed here, so the PATCH's ['fridge'] invalidation refetches it, and
  // mutateAsync waits for that, even before Fridge has mounted its own.
  useFridge(userId);
  const mutation = useUpdateUserProfile();
  // The KEY, not the sentence: an error already translated cannot follow a
  // later language switch. See AuthBar for the same shape.
  const [saveError, setSaveError] = useState<TranslationKey | null>(null);
  const [step, setStep] = useState<"prefs" | "stock">("prefs");
  const titleId = useId();
  const textId = useId();
  const pointerId = useId();
  const answerRestock = useAnswerRestock();

  // The stock step IS the restock question, asked at first run: any of its
  // buttons answers it, so RestockPrompt does not ask "Start fresh?" right
  // after (an admin's onboarding reset over a stale, empty fridge would).
  // The cache is seeded first: the prompt's query starts the moment
  // onboarding completes, and must not show it while the answer is in flight.
  const finishStock = (start: boolean) => {
    if (userId !== null) {
      queryClient.setQueryData<RestockStatus>(["restock", userId], { due: false, days_since_write: null });
    }
    answerRestock.mutate();
    setOnboardingCompleted(true);
    if (start) onStartRestock();
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
        need_to_use_enabled: values.need_to_use_enabled,
        waste_tracking_enabled: values.waste_tracking_enabled,
        default_day_layout: values.default_day_layout,
        onboarding_completed: true,
      });
    } catch {
      setSaveError("settings.saveFailed");
      return;
    }
    // Read from the cache, not this render: the PATCH just refetched the
    // fridge. Only a list that loaded with its token (RestockDialog reads it at
    // mount) and holds nothing gets the offer. A full fridge (an admin reset, a
    // new member of a shared household) or one that failed to load closes the
    // modal as before.
    const fridge = queryClient.getQueryState<ShelfData<StockItem>>(["fridge", userId]);
    if (fridge?.status === "success" && fridge.data?.token != null && fridge.data.items.length === 0) {
      // The server flag is already true: write the session hint now, as
      // setOnboardingCompleted would, so a reload or a second tab (the
      // confirmation email) skips the preferences form instead of showing it
      // until the profile loads. The local flag stays false: this step shows.
      window.localStorage.setItem("mealbot_onboarding", "true");
      setStep("stock");
    } else {
      setOnboardingCompleted(true);
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
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        // The stock step moves focus to its button, so the question (and for an
        // unconfirmed email, the pointer) must be the dialog's description.
        aria-describedby={step === "stock" && !emailVerified ? `${textId} ${pointerId}` : textId}
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
        {step === "stock" ? (
          // Every button finishes onboarding: the server flag is already true,
          // so a reload skips this screen anyway.
          <>
            <h2 id={titleId} style={{ marginTop: 0, marginBottom: "0.25rem" }}>{t("onboarding.stockTitle")}</h2>
            <p id={textId} style={{ color: "#666", marginTop: 0, marginBottom: "1.5rem" }}>
              {t("onboarding.stockText")}
            </p>
            {emailVerified ? (
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                <button
                  type="button"
                  autoFocus
                  onClick={() => finishStock(true)}
                  style={primaryButton}
                >
                  {t("onboarding.stockScan")}
                </button>
                <button type="button" onClick={() => finishStock(false)} style={secondaryButton}>
                  {t("onboarding.stockLater")}
                </button>
              </div>
            ) : (
              // Every scan returns 403 until the email is confirmed.
              <>
                <p id={pointerId} style={{ marginTop: 0, marginBottom: "1.5rem" }}>{t("onboarding.stockVerifyFirst")}</p>
                <button type="button" autoFocus onClick={() => finishStock(false)} style={primaryButton}>
                  {t("onboarding.stockOk")}
                </button>
              </>
            )}
          </>
        ) : (
          <>
            <h2 id={titleId} style={{ marginTop: 0, marginBottom: "0.25rem" }}>{t("onboarding.title")}</h2>
            <p id={textId} style={{ color: "#666", marginTop: 0, marginBottom: "1.5rem" }}>
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
          </>
        )}
      </div>
    </div>
  );
}
