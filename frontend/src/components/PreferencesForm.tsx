import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import type { MeasurementSystem, Variability } from "../types";
import type { MealType } from "../constants/mealTypes";
import { authFetch } from "../api.ts";
import { DayLayoutEditor } from "./DayLayoutEditor";
import { useI18n } from "../i18n";

export interface PreferencesFormValues {
  country: string;
  language: string;
  variability: Variability;
  measurement_system: MeasurementSystem;
  include_spices: boolean;
  show_pieces: boolean;
  track_snacks: boolean;
  need_to_use_enabled: boolean;
  // [] means "no default set" (the backend clears the column); a populated
  // list is stored verbatim and used as the per-day shape in Phase 3.
  default_day_layout: MealType[];
}

interface PreferencesFormProps {
  initialValues: PreferencesFormValues;
  onSubmit: (values: PreferencesFormValues) => void;
  submitLabel: string;
  loading?: boolean;
}

// Fetch a canonical whitelist from the backend. Returns [list, loaded]:
// `loaded` stays false on network failure so the form falls back to
// server-side validation instead of locking the user out.
function useWhitelist(path: string, key: string): [string[], boolean] {
  const [list, setList] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    Promise.resolve(authFetch(path))
      .then((r) => (r?.ok ? r.json() : null))
      .then((data: Record<string, unknown> | null) => {
        const entries = data?.[key];
        if (Array.isArray(entries)) {
          setList(entries as string[]);
          setLoaded(true);
        }
      })
      .catch(() => { /* keep loaded=false → skip client-side gate */ });
  }, [path, key]);
  return [list, loaded];
}

// Tab/Enter → complete the input to the first case-insensitive prefix match
// from `list`. If the current value is already a canonical entry or nothing
// matches, leave the default behaviour alone (Enter may submit, Tab may move
// focus). Also canonicalizes case: typing "italy" + Tab → "Italy".
function completeOnKey(
  list: string[],
  value: string,
  setValue: (v: string) => void,
): (e: KeyboardEvent<HTMLInputElement>) => void {
  return (e) => {
    if (e.key !== "Tab" && e.key !== "Enter") return;
    const raw = value.trim();
    if (!raw) return;
    if (list.includes(raw)) return; // already canonical
    const lower = raw.toLowerCase();
    const match = list.find((item) => item.toLowerCase().startsWith(lower));
    if (!match) return;
    e.preventDefault();
    setValue(match);
  };
}

export function PreferencesForm({ initialValues, onSubmit, submitLabel, loading }: PreferencesFormProps) {
  const { t } = useI18n();
  const [country, setCountry] = useState(initialValues.country);
  const [language, setLanguage] = useState(initialValues.language);
  const [variability, setVariability] = useState<Variability>(initialValues.variability);
  const [measurementSystem, setMeasurementSystem] = useState<MeasurementSystem>(
    initialValues.measurement_system,
  );
  const [includeSpices, setIncludeSpices] = useState(initialValues.include_spices);
  const [showPieces, setShowPieces] = useState(initialValues.show_pieces);
  const [trackSnacks, setTrackSnacks] = useState(initialValues.track_snacks);
  const [needToUseEnabled, setNeedToUseEnabled] = useState(initialValues.need_to_use_enabled);
  const [defaultDayLayout, setDefaultDayLayout] = useState<MealType[]>(
    initialValues.default_day_layout,
  );

  const [countries, countriesLoaded] = useWhitelist("/countries", "countries");
  const [languages, languagesLoaded] = useWhitelist("/languages", "languages");

  const countrySet = useMemo(() => new Set(countries), [countries]);
  const languageSet = useMemo(() => new Set(languages), [languages]);

  // Country is optional (stored NULL when blank). Language is required — the
  // backend column is NOT NULL with a default, and the LLM needs a value.
  const countryValid =
    !countriesLoaded || country.trim() === "" || countrySet.has(country.trim());
  const languageValid =
    !languagesLoaded || (language.trim() !== "" && languageSet.has(language.trim()));

  const canSubmit = !loading && countryValid && languageValid;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      country: country.trim(),
      language: language.trim(),
      variability,
      measurement_system: measurementSystem,
      include_spices: includeSpices,
      show_pieces: showPieces,
      track_snacks: trackSnacks,
      need_to_use_enabled: needToUseEnabled,
      default_day_layout: defaultDayLayout,
    });
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        <span style={{ fontWeight: 600 }}>{t("prefs.country")}</span>
        <span style={{ fontSize: "0.85rem", color: "#666" }}>
          {t("prefs.countryHint")}
        </span>
        <input
          list="country-list"
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          onKeyDown={completeOnKey(countries, country, setCountry)}
          placeholder={t("prefs.countryPlaceholder")}
          aria-invalid={!countryValid}
          style={{
            padding: "0.5rem",
            fontSize: "1rem",
            border: `1px solid ${countryValid ? "#ccc" : "#dc2626"}`,
            borderRadius: "4px",
          }}
        />
        <datalist id="country-list">
          {countries.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
        {!countryValid && (
          <span style={{ fontSize: "0.85rem", color: "#dc2626" }}>
            {t("prefs.countryInvalid")}
          </span>
        )}
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        <span style={{ fontWeight: 600 }}>{t("prefs.language")}</span>
        <span style={{ fontSize: "0.85rem", color: "#666" }}>
          {t("prefs.languageHint")}
        </span>
        <input
          list="language-list"
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          onKeyDown={completeOnKey(languages, language, setLanguage)}
          placeholder={t("prefs.languagePlaceholder")}
          aria-invalid={!languageValid}
          style={{
            padding: "0.5rem",
            fontSize: "1rem",
            border: `1px solid ${languageValid ? "#ccc" : "#dc2626"}`,
            borderRadius: "4px",
          }}
        />
        <datalist id="language-list">
          {languages.map((l) => (
            <option key={l} value={l} />
          ))}
        </datalist>
        {!languageValid && (
          <span style={{ fontSize: "0.85rem", color: "#dc2626" }}>
            {t("prefs.languageInvalid")}
          </span>
        )}
      </label>

      <fieldset style={{ border: "1px solid #ddd", borderRadius: "6px", padding: "0.75rem 1rem" }}>
        <legend style={{ fontWeight: 600, padding: "0 0.25rem" }}>{t("prefs.cuisineStyle")}</legend>
        <div style={{ display: "flex", gap: "1.5rem", marginTop: "0.25rem" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer" }}>
            <input
              type="radio"
              name="variability"
              value="traditional"
              checked={variability === "traditional"}
              onChange={() => setVariability("traditional")}
            />
            {t("prefs.traditional")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer" }}>
            <input
              type="radio"
              name="variability"
              value="experimental"
              checked={variability === "experimental"}
              onChange={() => setVariability("experimental")}
            />
            {t("prefs.experimental")}
          </label>
        </div>
        <p style={{ fontSize: "0.85rem", color: "#666", margin: "0.5rem 0 0" }}>
          {variability === "traditional"
            ? t("prefs.traditionalHint")
            : t("prefs.experimentalHint")}
        </p>
      </fieldset>

      {/* Backend column, prompt variable and PATCH validation for this have
          existed since the first migration — it just had no control, so every
          user sat on the "metric" default. Affects recipe STEPS only; the
          structured ingredient amounts are always grams. */}
      <fieldset style={{ border: "1px solid #ddd", borderRadius: "6px", padding: "0.75rem 1rem" }}>
        <legend style={{ fontWeight: 600, padding: "0 0.25rem" }}>{t("prefs.units")}</legend>
        <div style={{ display: "flex", gap: "1.5rem", marginTop: "0.25rem", flexWrap: "wrap" }}>
          {([
            ["metric", "prefs.unitsMetric"],
            ["imperial", "prefs.unitsImperial"],
            ["none", "prefs.unitsNone"],
          ] as const).map(([value, labelKey]) => (
            <label key={value} style={{ display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer" }}>
              <input
                type="radio"
                name="measurement_system"
                value={value}
                checked={measurementSystem === value}
                onChange={() => setMeasurementSystem(value)}
              />
              {t(labelKey)}
            </label>
          ))}
        </div>
        <p style={{ fontSize: "0.85rem", color: "#666", margin: "0.5rem 0 0" }}>
          {measurementSystem === "metric"
            ? t("prefs.unitsMetricHint")
            : measurementSystem === "imperial"
              ? t("prefs.unitsImperialHint")
              : t("prefs.unitsNoneHint")}
        </p>
      </fieldset>

      <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={includeSpices}
          onChange={(e) => setIncludeSpices(e.target.checked)}
          style={{ width: "18px", height: "18px" }}
        />
        <span>
          <span style={{ fontWeight: 600 }}>{t("prefs.includeSpices")}</span>
          <br />
          <span style={{ fontSize: "0.85rem", color: "#666" }}>
            {t("prefs.includeSpicesHint")}
          </span>
        </span>
      </label>

      <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={showPieces}
          onChange={(e) => setShowPieces(e.target.checked)}
          style={{ width: "18px", height: "18px" }}
        />
        <span>
          <span style={{ fontWeight: 600 }}>{t("prefs.showPieces")}</span>
          <br />
          <span style={{ fontSize: "0.85rem", color: "#666" }}>
            {t("prefs.showPiecesHint")}
          </span>
        </span>
      </label>

      <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={trackSnacks}
          onChange={(e) => setTrackSnacks(e.target.checked)}
          style={{ width: "18px", height: "18px" }}
        />
        <span>
          <span style={{ fontWeight: 600 }}>{t("prefs.trackSnacks")}</span>
          <br />
          <span style={{ fontSize: "0.85rem", color: "#666" }}>
            {t("prefs.trackSnacksHint")}
          </span>
        </span>
      </label>

      <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={needToUseEnabled}
          onChange={(e) => setNeedToUseEnabled(e.target.checked)}
          style={{ width: "18px", height: "18px" }}
        />
        <span>
          <span style={{ fontWeight: 600 }}>{t("prefs.needToUseEnabled")}</span>
          <br />
          <span style={{ fontSize: "0.85rem", color: "#666" }}>
            {t("prefs.needToUseEnabledHint")}
          </span>
        </span>
      </label>

      <fieldset style={{ border: "1px solid #ddd", borderRadius: "6px", padding: "0.75rem 1rem" }}>
        <legend style={{ fontWeight: 600, padding: "0 0.25rem" }}>{t("prefs.dayLayout")}</legend>
        <p style={{ fontSize: "0.85rem", color: "#666", margin: "0 0 0.5rem 0" }}>
          {t("prefs.dayLayoutHint")}
        </p>
        <DayLayoutEditor
          value={defaultDayLayout}
          onChange={setDefaultDayLayout}
          disabled={loading}
          ariaLabel={t("prefs.dayLayout")}
        />
      </fieldset>

      <button
        type="submit"
        disabled={!canSubmit}
        style={{
          padding: "0.6rem 1.5rem",
          fontSize: "1rem",
          backgroundColor: "#2563eb",
          color: "white",
          border: "none",
          borderRadius: "6px",
          cursor: canSubmit ? "pointer" : "not-allowed",
          opacity: canSubmit ? 1 : 0.7,
          alignSelf: "flex-start",
        }}
      >
        {loading ? t("prefs.saving") : submitLabel}
      </button>
    </form>
  );
}
