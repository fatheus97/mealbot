import { useState } from "react";
import { COUNTRIES } from "../data/countries";
import { LANGUAGES } from "../data/languages";
import type { Variability } from "../types";

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

export function PreferencesForm({ initialValues, onSubmit, submitLabel, loading }: PreferencesFormProps) {
  const [country, setCountry] = useState(initialValues.country);
  const [language, setLanguage] = useState(initialValues.language);
  const [variability, setVariability] = useState<Variability>(initialValues.variability);
  const [includeSpices, setIncludeSpices] = useState(initialValues.include_spices);
  const [trackSnacks, setTrackSnacks] = useState(initialValues.track_snacks);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({ country, language, variability, include_spices: includeSpices, track_snacks: trackSnacks });
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
          placeholder="Start typing to search..."
          style={{ padding: "0.5rem", fontSize: "1rem", border: "1px solid #ccc", borderRadius: "4px" }}
        />
        <datalist id="country-list">
          {COUNTRIES.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
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
          placeholder="e.g. English, Czech, Spanish..."
          style={{ padding: "0.5rem", fontSize: "1rem", border: "1px solid #ccc", borderRadius: "4px" }}
        />
        <datalist id="language-list">
          {LANGUAGES.map((l) => (
            <option key={l} value={l} />
          ))}
        </datalist>
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
        disabled={loading}
        style={{
          padding: "0.6rem 1.5rem",
          fontSize: "1rem",
          backgroundColor: "#2563eb",
          color: "white",
          border: "none",
          borderRadius: "6px",
          cursor: loading ? "not-allowed" : "pointer",
          opacity: loading ? 0.7 : 1,
          alignSelf: "flex-start",
        }}
      >
        {loading ? "Saving..." : submitLabel}
      </button>
    </form>
  );
}
