import type { PreferencesFormValues } from "../components/PreferencesForm";
import type { UserProfile } from "../types";

/**
 * The preferences form's starting values: the user's SAVED profile.
 *
 * Shared by Settings and onboarding. Onboarding is not only a first run: admin
 * "Reset onboarding" clears just the onboarding_completed flag, so a returning
 * user lands there with every preference still stored. Seeding that form from
 * hard-coded defaults saved the defaults over all of them on "Get Started".
 *
 * Each fallback is the column default in db_models.User, so a brand-new
 * account (whose profile holds exactly those defaults) sees what onboarding
 * always showed.
 */
export function preferencesFromProfile(profile: UserProfile): PreferencesFormValues {
  return {
    country: profile.country ?? "",
    language: profile.language,
    variability: profile.variability,
    measurement_system: profile.measurement_system ?? "metric",
    include_spices: profile.include_spices,
    // ?? false like the billing fields: a payload cached before this field
    // existed would otherwise send undefined and look like a no-op save.
    show_pieces: profile.show_pieces ?? false,
    track_snacks: profile.track_snacks,
    // ?? true (not false): the feature already exists and defaults on, so a
    // payload cached before this field existed should read as "still
    // enabled", not silently opt the user out.
    need_to_use_enabled: profile.need_to_use_enabled ?? true,
    // Opt-in: false is the column default, never an enrolment the user did
    // not choose.
    waste_tracking_enabled: profile.waste_tracking_enabled ?? false,
    default_day_layout: profile.default_day_layout ?? [],
  };
}
