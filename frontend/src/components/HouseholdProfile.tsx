import { useState, type CSSProperties } from "react";
import { useAuth } from "../contexts/AuthContext";
import { ALLERGENS, DIET_TYPES, type Allergen, type DietType } from "../constants/dietary";
import { FIELD_LIMITS } from "../constants/fieldLimits";
import {
  useDeleteDietaryProfile,
  useDietaryProfile,
  useSaveDietaryProfile,
} from "../hooks/useServerState";
import { useI18n } from "../i18n";
import { formatDate } from "../i18n/localeFormat";
import type { DietaryProfile } from "../types";
import { DietarySelector } from "./DietarySelector";
import { HealthConsentCheckbox } from "./HealthConsentCheckbox";
import { InfoHint } from "./InfoHint";
import { IngredientChipInput } from "./IngredientChipInput";

interface Draft {
  dietTypes: DietType[];
  allergens: Allergen[];
  avoid: string[];
}

/** The saved profile as the editor shows it. A value a later release dropped
 *  from the lists is left out, so saving drops it too. */
function fromProfile(profile: DietaryProfile | null | undefined): Draft {
  return {
    dietTypes: (profile?.diet_types ?? []).filter((d): d is DietType =>
      (DIET_TYPES as readonly string[]).includes(d),
    ),
    allergens: (profile?.allergens ?? []).filter((a): a is Allergen =>
      (ALLERGENS as readonly string[]).includes(a),
    ),
    avoid: profile?.avoid_ingredients ?? [],
  };
}

const toggle = <T,>(list: T[], value: T): T[] =>
  list.includes(value) ? list.filter((x) => x !== value) : [...list, value];

/**
 * A person's own saved diets, allergies and ingredients to avoid, which every
 * plan for a shared household is cooked with (docs/household-design.md,
 * "Diets, allergies and consent"). Shown inside the Household section, so only
 * while households are on.
 *
 * Nothing is edited until the user changes something: until then the editor
 * shows the server's copy, so there is no seeding effect to race a reload.
 *
 * THEME: lives inside SettingsPopup's explicit light surface.
 */
export function HouseholdProfile() {
  const { userId, healthConsent } = useAuth();
  const { t, locale } = useI18n();
  const { data: profile, isError } = useDietaryProfile(userId);
  const save = useSaveDietaryProfile();
  const remove = useDeleteDietaryProfile();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shown = draft ?? fromProfile(profile);
  const carries = shown.dietTypes.length > 0 || shown.allergens.length > 0 || shown.avoid.length > 0;
  const copy = { rateLimited: t("household.rateLimited"), fallback: t("household.profileFailed") };
  const edit = (next: Draft) => {
    setDraft(next);
    setSaved(false);
  };

  const handleSave = async () => {
    setError(null);
    try {
      await save.mutateAsync({
        body: {
          diet_types: shown.dietTypes,
          allergens: shown.allergens,
          avoid_ingredients: shown.avoid,
        },
        copy,
      });
      setDraft(null);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("household.profileFailed"));
    }
  };

  const handleRemove = async () => {
    setError(null);
    try {
      await remove.mutateAsync(copy);
      setDraft(null);
      setConfirmingRemove(false);
      setSaved(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("household.profileFailed"));
    }
  };

  return (
    <div style={{ marginTop: "1rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.5rem" }}>
        <span style={{ fontSize: 13, color: "#6b7280" }}>{t("household.profileTitle")}</span>
        <InfoHint label={t("household.profileHintLabel")} text={t("household.profileHint")} />
      </div>
      {isError && (
        <p role="alert" style={errorText}>
          {t("household.profileLoadFailed")}
        </p>
      )}
      <DietarySelector
        dietTypes={shown.dietTypes}
        allergens={shown.allergens}
        onToggleDiet={(d) => edit({ ...shown, dietTypes: toggle(shown.dietTypes, d) })}
        onToggleAllergen={(a) => edit({ ...shown, allergens: toggle(shown.allergens, a) })}
        disabled={save.isPending}
      />
      <label htmlFor="household-profile-avoid" style={{ display: "block", fontSize: 13, margin: "0.5rem 0 0.25rem" }}>
        {t("cookNow.avoid")}
      </label>
      <IngredientChipInput
        id="household-profile-avoid"
        values={shown.avoid}
        onChange={(avoid) => edit({ ...shown, avoid })}
        suggestions={[]}
        placeholder={t("cookNow.avoidPlaceholder")}
        maxItems={FIELD_LIMITS.avoidIngredients}
      />
      <HealthConsentCheckbox active={carries && draft !== null} id="health-consent-profile" lightSurface />
      <div style={{ ...row, marginTop: "0.5rem" }}>
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={draft === null || save.isPending || (carries && !healthConsent)}
          style={{ ...secondary, opacity: draft === null || save.isPending ? 0.6 : 1 }}
        >
          {save.isPending ? t("household.profileSaving") : t("household.profileSave")}
        </button>
        {draft !== null && (
          <button type="button" onClick={() => setDraft(null)} disabled={save.isPending} style={secondary}>
            {t("household.cancel")}
          </button>
        )}
      </div>
      {/* Reserved line, so a status appearing never moves the buttons below. */}
      <p aria-live="polite" style={{ ...note, minHeight: "1rem", margin: "0.35rem 0 0" }}>
        {saved
          ? t("household.profileSaved")
          : profile?.updated_at
            ? t("household.profileSavedOn", { date: formatDate(profile.updated_at, locale) })
            : ""}
      </p>
      {profile?.updated_at && (
        <div style={{ marginTop: "0.5rem" }}>
          {!confirmingRemove ? (
            <button type="button" onClick={() => setConfirmingRemove(true)} style={danger}>
              {t("household.profileRemove")}
            </button>
          ) : (
            <div>
              <p style={{ fontSize: 13, color: "#111827", margin: "0 0 0.5rem" }}>
                {t("household.profileRemoveConfirm")}
              </p>
              <div style={row}>
                <button
                  type="button"
                  onClick={() => void handleRemove()}
                  disabled={remove.isPending}
                  style={{ ...danger, opacity: remove.isPending ? 0.6 : 1 }}
                >
                  {remove.isPending ? t("household.profileRemoving") : t("household.profileRemoveButton")}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmingRemove(false)}
                  disabled={remove.isPending}
                  style={secondary}
                >
                  {t("household.cancel")}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
      {error && (
        <p role="alert" style={errorText}>
          {error}
        </p>
      )}
    </div>
  );
}

const row: CSSProperties = { display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" };

const note: CSSProperties = { fontSize: 12, color: "#4b5563" };

const errorText: CSSProperties = { margin: "0.4rem 0 0", color: "#b91c1c", fontSize: 12 };

const secondary: CSSProperties = {
  padding: "0.5rem 0.75rem",
  border: "1px solid #d1d5db",
  borderRadius: 6,
  background: "#f9fafb",
  color: "#111827",
  cursor: "pointer",
  fontSize: 13,
};

const danger: CSSProperties = {
  padding: "0.5rem 0.75rem",
  border: "1px solid #fecaca",
  borderRadius: 6,
  background: "#fef2f2",
  color: "#b91c1c",
  cursor: "pointer",
  fontSize: 13,
};
