import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import type { Variability } from "../types";
import { authFetch } from "../api.ts";

export interface PreferencesFormValues {
  country: string;
  language: string;
  variability: Variability;
  include_spices: boolean;
  track_snacks: boolean;
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
  const [country, setCountry] = useState(initialValues.country);
  const [language, setLanguage] = useState(initialValues.language);
  const [variability, setVariability] = useState<Variability>(initialValues.variability);
  const [includeSpices, setIncludeSpices] = useState(initialValues.include_spices);
  const [trackSnacks, setTrackSnacks] = useState(initialValues.track_snacks);

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
      include_spices: includeSpices,
      track_snacks: trackSnacks,
    });
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        <span style={{ fontWeight: 600 }}>Country</span>
        <span style={{ fontSize: "0.85rem", color: "#666" }}>
          Used for local ingredient availability and regional recipes
        </span>
        <input
          list="country-list"
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          onKeyDown={completeOnKey(countries, country, setCountry)}
          placeholder="Start typing to search..."
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
            Pick a country from the list.
          </span>
        )}
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        <span style={{ fontWeight: 600 }}>Language</span>
        <span style={{ fontSize: "0.85rem", color: "#666" }}>
          Meal plans, recipes, and ingredient names will be generated in this language
        </span>
        <input
          list="language-list"
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          onKeyDown={completeOnKey(languages, language, setLanguage)}
          placeholder="e.g. English, Czech, Spanish..."
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
            Pick a language from the list.
          </span>
        )}
      </label>

      <fieldset style={{ border: "1px solid #ddd", borderRadius: "6px", padding: "0.75rem 1rem" }}>
        <legend style={{ fontWeight: 600, padding: "0 0.25rem" }}>Cuisine Style</legend>
        <div style={{ display: "flex", gap: "1.5rem", marginTop: "0.25rem" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer" }}>
            <input
              type="radio"
              name="variability"
              value="traditional"
              checked={variability === "traditional"}
              onChange={() => setVariability("traditional")}
            />
            Traditional
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer" }}>
            <input
              type="radio"
              name="variability"
              value="experimental"
              checked={variability === "experimental"}
              onChange={() => setVariability("experimental")}
            />
            Experimental
          </label>
        </div>
        <p style={{ fontSize: "0.85rem", color: "#666", margin: "0.5rem 0 0" }}>
          {variability === "traditional"
            ? "Classic dishes typical for your country"
            : "Creative combinations, fusion cuisine, and novel techniques"}
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
          <span style={{ fontWeight: 600 }}>Include spices in shopping list</span>
          <br />
          <span style={{ fontSize: "0.85rem", color: "#666" }}>
            If off, spices won't appear in stock/shopping lists (they'll still be in recipe steps)
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
          <span style={{ fontWeight: 600 }}>Track snacks from receipts</span>
          <br />
          <span style={{ fontSize: "0.85rem", color: "#666" }}>
            If off, ready-to-eat items (desserts, snacks, drinks) are excluded when scanning receipts
          </span>
        </span>
      </label>

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
        {loading ? "Saving..." : submitLabel}
      </button>
    </form>
  );
}
