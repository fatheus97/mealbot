// src/App.tsx
import { useEffect, useState } from "react";
import type {
  MealPlanRequest,
  MealPlanResponse,
  MealHistoryItem,
  StockItem,
  AuthResponse,
  UserProfile,
  MeasurementSystem,
  Variability,
} from "./types";

const API_BASE = "http://localhost:8000/api";
const USER_ID_KEY = "mealbot_user_id";
const USER_EMAIL_KEY = "mealbot_user_email";
const PLAN_SETTINGS_KEY = "mealbot_plan_settings_v1";
const FALLBACK_COUNTRIES: string[] = [
  "Afghanistan","Albania","Algeria","Andorra","Angola","Antigua and Barbuda","Argentina","Armenia","Australia","Austria","Azerbaijan",
  "Bahamas","Bahrain","Bangladesh","Barbados","Belarus","Belgium","Belize","Benin","Bhutan","Bolivia","Bosnia and Herzegovina","Botswana","Brazil","Brunei","Bulgaria","Burkina Faso","Burundi",
  "Cabo Verde","Cambodia","Cameroon","Canada","Central African Republic","Chad","Chile","China","Colombia","Comoros","Congo (Democratic Republic of the)","Congo (Republic of the)","Costa Rica","Côte d’Ivoire","Croatia","Cuba","Cyprus","Czechia",
  "Denmark","Djibouti","Dominica","Dominican Republic",
  "Ecuador","Egypt","El Salvador","Equatorial Guinea","Eritrea","Estonia","Eswatini","Ethiopia",
  "Fiji","Finland","France",
  "Gabon","Gambia","Georgia","Germany","Ghana","Greece","Grenada","Guatemala","Guinea","Guinea-Bissau","Guyana",
  "Haiti","Honduras","Hungary",
  "Iceland","India","Indonesia","Iran","Iraq","Ireland","Israel","Italy",
  "Jamaica","Japan","Jordan",
  "Kazakhstan","Kenya","Kiribati","Kosovo","Kuwait","Kyrgyzstan",
  "Laos","Latvia","Lebanon","Lesotho","Liberia","Libya","Liechtenstein","Lithuania","Luxembourg",
  "Madagascar","Malawi","Malaysia","Maldives","Mali","Malta","Marshall Islands","Mauritania","Mauritius","Mexico","Micronesia","Moldova","Monaco","Mongolia","Montenegro","Morocco","Mozambique","Myanmar",
  "Namibia","Nauru","Nepal","Netherlands","New Zealand","Nicaragua","Niger","Nigeria","North Korea","North Macedonia","Norway",
  "Oman",
  "Pakistan","Palau","Panama","Papua New Guinea","Paraguay","Peru","Philippines","Poland","Portugal",
  "Qatar",
  "Romania","Russia","Rwanda",
  "Saint Kitts and Nevis","Saint Lucia","Saint Vincent and the Grenadines","Samoa","San Marino","São Tomé and Príncipe","Saudi Arabia","Senegal","Serbia","Seychelles","Sierra Leone","Singapore","Slovakia","Slovenia","Solomon Islands","Somalia","South Africa","South Korea","South Sudan","Spain","Sri Lanka","Sudan","Suriname","Sweden","Switzerland","Syria",
  "Taiwan","Tajikistan","Tanzania","Thailand","Timor-Leste","Togo","Tonga","Trinidad and Tobago","Tunisia","Turkey","Turkmenistan","Tuvalu",
  "Uganda","Ukraine","United Arab Emirates","United Kingdom","United States","Uruguay","Uzbekistan",
  "Vanuatu","Vatican City","Venezuela","Vietnam",
  "Yemen",
  "Zambia","Zimbabwe",
  "Palestine"
];
// Best effort: use browser-provided region list if available, fallback otherwise.
function getCountryOptions(): string[] {
  try {
    const intlAny = Intl as any;
    if (typeof intlAny.supportedValuesOf === "function" && typeof intlAny.DisplayNames === "function") {
      const regions = intlAny.supportedValuesOf("region") as string[];
      const dn = new intlAny.DisplayNames(["en"], { type: "region" });

      const names = regions
        .map((code) => dn.of(code))
        .filter((n: string | undefined): n is string => Boolean(n))
        .filter((n: string) => n.toLowerCase() !== "unknown region")
        .sort((a: string, b: string) => a.localeCompare(b));

      return Array.from(new Set(names));
    }
  } catch {
    // ignore and fallback
  }
  return FALLBACK_COUNTRIES;
}

const COUNTRY_OPTIONS = getCountryOptions();

function splitToArray(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function App() {
  const [userId, setUserId] = useState<number | null>(null);

  const [fridge, setFridge] = useState<StockItem[]>([
    { name: "chicken breast", quantity_grams: 600, need_to_use: true },
    { name: "rice", quantity_grams: 500, need_to_use: false },
    { name: "spinach", quantity_grams: 200, need_to_use: true },
  ]);


  const [days, setDays] = useState<number>(3);
  const [tastePrefs, setTastePrefs] = useState<string>("spicy, asian");
  const [avoid, setAvoid] = useState<string>("");
  const [dietType, setDietType] = useState<string>("high_protein");
  const [mealsPerDay, setMealsPerDay] = useState<number>(3);
  const [peopleCount, setPeopleCount] = useState<number>(2);

  const [planSettingsHydrated, setPlanSettingsHydrated] = useState<boolean>(false);
  const [plan, setPlan] = useState<MealPlanResponse | null>(null);
  const [history, setHistory] = useState<MealHistoryItem[]>([]);
  const [loadingPlan, setLoadingPlan] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [fridgeNotice, setFridgeNotice] = useState<string | null>(null);
  const [historyLoadedOnce, setHistoryLoadedOnce] = useState<boolean>(false);
  const [bootstrapping, setBootstrapping] = useState<boolean>(true);
  const [authNotice, setAuthNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [confirmNotice, setConfirmNotice] = useState<string | null>(null);

  const [email, setEmail] = useState<string>(() => {
    return window.localStorage.getItem(USER_EMAIL_KEY) ?? "";
  });

  const [authLoading, setAuthLoading] = useState<boolean>(false);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [profileDraft, setProfileDraft] = useState<{
    country: string;
    measurement_system: MeasurementSystem;
    variability: Variability;
    include_spices: boolean;
  }>({
    country: "",
    measurement_system: "metric",
    variability: "traditional",
    include_spices: true,
  });

  function openOnboarding(p?: UserProfile | null) {
    setProfileError(null);
    setProfileDraft({
      country: p?.country ?? "",
      measurement_system: (p?.measurement_system ?? "metric") as MeasurementSystem,
      variability: (p?.variability ?? "traditional") as Variability,
      include_spices: p?.include_spices ?? true,
    });
    setShowOnboarding(true);
  }

  async function loadUserProfile(uid: number): Promise<UserProfile | null> {
    try {
      const resp = await fetch(`${API_BASE}/users/${uid}`);
      if (resp.status === 404) return null;
      if (!resp.ok) throw new Error(`Get user profile failed: ${resp.status}`);
      const data = (await resp.json()) as UserProfile;
      setProfile(data);
      return data;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      return null;
    }
  }

  async function saveOnboarding(): Promise<void> {
    if (userId == null) return;

    const country = profileDraft.country.trim();
    if (!country) {
      setProfileError("Country is required.");
      return;
    }

    setProfileSaving(true);
    setProfileError(null);

    try {
      const resp = await fetch(`${API_BASE}/users/${userId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          country,
          measurement_system: profileDraft.measurement_system,
          variability: profileDraft.variability,
          include_spices: profileDraft.include_spices,
          onboarding_completed: true,
        }),
      });

      if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`Save profile failed: ${resp.status} ${txt}`);
      }

      const updated = (await resp.json()) as UserProfile;
      setProfile(updated);
      setShowOnboarding(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setProfileError(msg);
    } finally {
      setProfileSaving(false);
    }
  }


  // ---------------------------------------------------------------------------
  // Generate form helper
  // ---------------------------------------------------------------------------

  type PlanSettings = Partial<{
    days: number;
    mealsPerDay: number;
    peopleCount: number;
    dietType: string;
    tastePrefs: string;
    avoid: string;
  }>;

  function applyPlanSettingsFromStorage(key: string) {
    const raw = window.localStorage.getItem(key);
    if (!raw) return;

    try {
      const s = JSON.parse(raw) as PlanSettings;

      if (typeof s.days === "number") setDays(s.days);
      if (typeof s.mealsPerDay === "number") setMealsPerDay(s.mealsPerDay);
      if (typeof s.peopleCount === "number") setPeopleCount(s.peopleCount);

      if (typeof s.dietType === "string") setDietType(s.dietType);
      if (typeof s.tastePrefs === "string") setTastePrefs(s.tastePrefs);
      if (typeof s.avoid === "string") setAvoid(s.avoid);
    } catch {
      // Ignore corrupted storage
    }
  }

  // ---------------------------------------------------------------------------
  // User bootstrap – vytvoření usera / načtení lednice
  // ---------------------------------------------------------------------------

  useEffect(() => {
    (async () => {
      setBootstrapping(true);
      try {

        // Prefer stored email (or default)
        const storedEmail = window.localStorage.getItem(USER_EMAIL_KEY);
        if (storedEmail && storedEmail !== email) {
          setEmail(storedEmail);
        }

        // Restore session only if we have a stored user id
        const storedIdRaw = window.localStorage.getItem(USER_ID_KEY);
        if (!storedIdRaw) {
          // Stay logged out
          setUserId(null);
          setFridge([]); // optional; keeps UI consistent when logged out
          setProfile(null);
          setShowOnboarding(false);
          return;
        }

        const storedId = Number(storedIdRaw);
        setUserId(storedId);

        const ok = await loadFridge(storedId);
        if (!ok) {
          // Stale id → clear and stay logged out
          window.localStorage.removeItem(USER_ID_KEY);
          setUserId(null);
          setFridge([]);
          return;
        }

        const p = await loadUserProfile(storedId);
        if (p && !p.onboarding_completed) {
          openOnboarding(p);
        }

      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
      } finally {
        setBootstrapping(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------------------------------------------------------------------------
  // Loading generate form from localStorage
  // ---------------------------------------------------------------------------

  useEffect(() => {
    setPlanSettingsHydrated(false);

    // Load global defaults first (works also when logged out)
    applyPlanSettingsFromStorage(PLAN_SETTINGS_KEY);

    // Then override with per-user settings (if logged in)
    if (userId != null) {
      applyPlanSettingsFromStorage(`${PLAN_SETTINGS_KEY}:${userId}`);
    }

    setPlanSettingsHydrated(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  // ---------------------------------------------------------------------------
  // Saving generate form to localStorage
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!planSettingsHydrated) return;
    const payload = { days, mealsPerDay, peopleCount, dietType, tastePrefs, avoid };
    if (userId != null) {
      window.localStorage.setItem(`${PLAN_SETTINGS_KEY}:${userId}`, JSON.stringify(payload));
    } else {
      window.localStorage.setItem(PLAN_SETTINGS_KEY, JSON.stringify(payload)); // fallback
    }
  }, [planSettingsHydrated, userId, days, mealsPerDay, peopleCount, dietType, tastePrefs, avoid]);

  // ---------------------------------------------------------------------------
  // Fridge API
  // ---------------------------------------------------------------------------

  async function loadFridge(uid: number): Promise<boolean> {
    try {
      const resp = await fetch(`${API_BASE}/users/${uid}/fridge`);

      if (resp.status === 404) {
        // User not found (stale localStorage id)
        return false;
      }
      if (!resp.ok) {
        throw new Error(`Get fridge failed: ${resp.status}`);
      }
      console.log(resp)
      const data = (await resp.json()) as StockItem[];
      console.log(data)
      setFridge(data); // Always reflect server state (even empty list)
      setError(null);
      return true;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      return true; // avoid infinite relogin on transient errors
    }
  }


  async function saveFridge() {
    if (userId == null) return;
    try {
      let resp = await fetch(`${API_BASE}/users/${userId}/fridge`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fridge),
      });

      if (resp.status === 404) {}

      if (!resp.ok) {
        throw new Error(`Put fridge failed: ${resp.status}`);
      }
      setError(null);
      setFridgeNotice("Fridge saved.");
      window.setTimeout(() => setFridgeNotice(null), 2500);

    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setFridgeNotice(null);
    }
  }

  function updateFridgeItem(
    index: number,
    field: "name" | "quantity_grams",
    value: string
  ) {
    setFridge((prev) =>
      prev.map((item, i) =>
        i === index
          ? {
              ...item,
              [field]: field === "quantity_grams" ? Number(value) || 0 : value,
            }
          : item
      )
    );
  }

  function toggleNeedToUse(index: number, checked: boolean) {
    setFridge((prev) =>
      prev.map((item, i) => (i === index ? { ...item, need_to_use: checked } : item))
    );
  }

  function addFridgeItem() {
    setFridge((prev) => [...prev, { name: "", quantity_grams: 0, need_to_use: false }]);
  }

  function removeFridgeItem(index: number) {
    setFridge((prev) => prev.filter((_, i) => i !== index));
  }

  // ---------------------------------------------------------------------------
  // Plan API
  // ---------------------------------------------------------------------------

  async function generatePlan() {
    if (userId == null) return;
    setLoadingPlan(true);
    setError(null);
    setPlan(null);

    const body: MealPlanRequest = {
      ingredients: fridge,
      taste_preferences: splitToArray(tastePrefs),
      avoid_ingredients: splitToArray(avoid),
      diet_type: dietType ? (dietType as any) : null,
      meals_per_day: mealsPerDay,
      people_count: peopleCount,
      past_meals: [],
    };

    try {
      const resp = await fetch(
        `${API_BASE}/users/${userId}/plan?days=${days}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );
      if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`Plan failed: ${resp.status} ${txt}`);
      }
      const data = (await resp.json()) as MealPlanResponse;
      setPlan(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setLoadingPlan(false);
    }
  }

  async function confirmPlan() {
    if (userId == null || plan == null) return;

    setConfirming(true);
    setError(null);
    setConfirmNotice(null);

    try {
      const resp = await fetch(
        `${API_BASE}/users/${userId}/plans/${plan.plan_id}/confirm`,
        { method: "POST" }
      );

      if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`Confirm failed: ${resp.status} ${txt}`);
      }

      // After confirm, reload fridge + history so UI matches DB.
      await loadFridge(userId);
      await loadHistory();

      setConfirmNotice("Plan confirmed. Fridge updated.");
      window.setTimeout(() => setConfirmNotice(null), 2500);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setConfirming(false);
    }
  }


  // ---------------------------------------------------------------------------
  // History API
  // ---------------------------------------------------------------------------

  async function loadHistory() {
    if (userId == null) return;
    try {
      const resp = await fetch(
        `${API_BASE}/users/${userId}/meals?limit=20`
      );
      if (!resp.ok) {
        throw new Error(`History failed: ${resp.status}`);
      }
      const data = (await resp.json()) as MealHistoryItem[];
      setHistory(data);
      setHistoryLoadedOnce(true);
      setError(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    }
  }

  // ---------------------------------------------------------------------------
  // User API
  // ---------------------------------------------------------------------------

  async function loginOrRegister(emailToUse: string): Promise<AuthResponse> {
    setAuthLoading(true);
    setError(null);
    setHistoryLoadedOnce(false);
    setFridgeNotice(null);

    try {
      const resp = await fetch(
        `${API_BASE}/users/?email=${encodeURIComponent(emailToUse)}`,
        { method: "POST" }
      );
      if (!resp.ok) {
        throw new Error(`Create/login user failed: ${resp.status}`);
      }

      const auth = (await resp.json()) as AuthResponse;

      setUserId(auth.user_id);
      window.localStorage.setItem(USER_ID_KEY, String(auth.user_id));
      window.localStorage.setItem(USER_EMAIL_KEY, emailToUse);

      return auth;
    } finally {
      setAuthLoading(false);
    }
  }

  // ---------------------------------------------------------------------------
  // UI
  // ---------------------------------------------------------------------------

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "1rem" }}>
      <h1>Mealbot Planner</h1>
      {showOnboarding && userId != null && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 9999,
            padding: "1rem",
          }}
        >
          <div
            style={{
              background: "white",
              color: "#111",              // ✅ fixes white-on-white
              borderRadius: 8,
              width: "min(720px, 100%)",
              maxHeight: "90vh",
              overflow: "auto",
              padding: "1rem",
            }}
          >
            <h2>Finish setup</h2>
            <p style={{ marginTop: 0 }}>
              These preferences will be used for local recipes, ingredient availability, and how we format meal plans.
            </p>

            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>

              <label style={{ flex: "1 1 220px" }}>
                Country: <span style={{ color: "red" }}>*</span>
                <input
                  style={{ width: "100%" }}
                  list="country-options"
                  value={profileDraft.country}
                  onChange={(e) => setProfileDraft((p) => ({ ...p, country: e.target.value }))}
                  placeholder="Start typing…"
                />
                <datalist id="country-options">
                  {COUNTRY_OPTIONS.map((c) => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
              </label>

              <label style={{ flex: "1 1 220px" }}>
                Measurements:
                <select
                  style={{ width: "100%" }}
                  value={profileDraft.measurement_system}
                  onChange={(e) =>
                    setProfileDraft((p) => ({ ...p, measurement_system: e.target.value as MeasurementSystem }))
                  }
                >
                  <option value="none">None</option>
                  <option value="metric">Metric</option>
                  <option value="imperial">Imperial</option>
                </select>
              </label>

              <label style={{ flex: "1 1 220px" }}>
                Variability:
                <select
                  style={{ width: "100%" }}
                  value={profileDraft.variability}
                  onChange={(e) =>
                    setProfileDraft((p) => ({ ...p, variability: e.target.value as Variability }))
                  }
                >
                  <option value="traditional">Traditional</option>
                  <option value="experimental">Experimental</option>
                </select>
              </label>
            </div>

            <label style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", alignItems: "center" }}>
              <input
                type="checkbox"
                checked={profileDraft.include_spices}
                onChange={(e) => setProfileDraft((p) => ({ ...p, include_spices: e.target.checked }))}
              />
              Include spices in shopping lists and stock (otherwise I handle spices myself)
            </label>

            {profileError && (
              <p style={{ color: "red", whiteSpace: "pre-wrap", marginTop: "0.75rem" }}>
                {profileError}
              </p>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "1rem" }}>
              <button
                onClick={saveOnboarding}
                disabled={profileSaving || profileDraft.country.trim().length === 0}
              >
                {profileSaving ? "Saving..." : "Save preferences"}
              </button>
            </div>
          </div>
        </div>
      )}

      <section style={{ marginBottom: "1.5rem" }}>
        <h2>Backend status</h2>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <input
            style={{ width: 280 }}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email"
          />
          <button
            onClick={async () => {
              setAuthNotice(null);
              setError(null);
              setPlan(null);
              setHistory([]);

              const auth = await loginOrRegister(email);
              await loadFridge(auth.user_id);
              applyPlanSettingsFromStorage(`${PLAN_SETTINGS_KEY}:${auth.user_id}`);

              const p = await loadUserProfile(auth.user_id);
              const onboardingDone = p?.onboarding_completed ?? auth.onboarding_completed;

              if (auth.created || !onboardingDone) {
                openOnboarding(p);
                setAuthNotice(auth.created ? "Account created. Please finish setup." : "Please finish setup.");
              } else {
                setAuthNotice("Logged in.");
              }

              window.setTimeout(() => setAuthNotice(null), 2000);
            }}
            disabled={authLoading}
          >
            {authLoading ? "Working..." : "Login / Register"}
          </button>

          <button
            onClick={() => {
              window.localStorage.removeItem(USER_ID_KEY);
              window.localStorage.removeItem(USER_EMAIL_KEY);

              setUserId(null);
              setFridge([]);
              setPlan(null);
              setHistory([]);
              setError(null);
              setHistoryLoadedOnce(false);
              setFridgeNotice(null);
              setAuthNotice("Logged out successfully.");
              window.setTimeout(() => setAuthNotice(null), 2500);
            }}
          >
            Logout
          </button>
        </div>
        <p>
          User ID:{" "}
          <strong>
            {userId != null
              ? userId
              : (bootstrapping || authLoading)
                ? "creating..."
                : "logged out"}
          </strong>

          {authNotice && <span>{authNotice}</span>}
        </p>
        {error && (
          <p style={{ color: "red", whiteSpace: "pre-wrap" }}>
            Error: {error}
          </p>
        )}
        {profile && (
          <div style={{ marginTop: "0.5rem", fontSize: 12 }}>
            Preferences: {profile.country ?? "—"} · {profile.measurement_system} · {profile.variability} ·
            spices {profile.include_spices ? "included" : "excluded"}{" "}
            <button onClick={() => openOnboarding(profile)}>Edit</button>
          </div>
        )}
      </section>

      {userId == null ? (
        <section style={{ marginBottom: "2rem" }}>
          <h2>Fridge</h2>
          <p>Please log in to view and edit your fridge.</p>
        </section>
      ) : (
        <section style={{ marginBottom: "2rem" }}>
          <h2>Fridge</h2>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Ingredient</th>
                <th style={{ textAlign: "left" }}>Quantity (g)</th>
                <th style={{ textAlign: "left" }}>Use soon</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {fridge.map((item, idx) => (
                <tr key={idx}>
                  <td>
                    <input
                      value={item.name}
                      onChange={(e) => updateFridgeItem(idx, "name", e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      style={{ width: "6rem" }}
                      min={0}
                      step={50} // optional; doesn't matter if we hide spinners
                      value={item.quantity_grams === 0 ? "" : item.quantity_grams}
                      onChange={(e) => updateFridgeItem(idx, "quantity_grams", e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      checked={item.need_to_use}
                      onChange={(e) => toggleNeedToUse(idx, e.target.checked)}
                    />
                  </td>
                  <td>
                    <button onClick={() => removeFridgeItem(idx)}>✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: "0.5rem" }}>
            <button onClick={addFridgeItem}>Add ingredient</button>{" "}
            <button onClick={saveFridge}>Save fridge</button>
            {fridgeNotice && (
              <div style={{ marginTop: "0.5rem" }}>{fridgeNotice}</div>
            )}
          </div>
        </section>
      )}

      <section style={{ marginBottom: "2rem" }}>
        <h2>Plan settings</h2>
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <label>
            Days:{" "}
            <input
              type="number"
              min={1}
              max={7}
              value={days}
              onChange={(e) => setDays(Number(e.target.value) || 1)}
            />
          </label>
          <label>
            Meals per day:{" "}
            <input
              type="number"
              min={1}
              max={6}
              value={mealsPerDay}
              onChange={(e) =>
                setMealsPerDay(Number(e.target.value) || 1)
              }
            />
          </label>
          <label>
            People:{" "}
            <input
              type="number"
              min={1}
              max={10}
              value={peopleCount}
              onChange={(e) =>
                setPeopleCount(Number(e.target.value) || 1)
              }
            />
          </label>
          <label>
            Diet type:{" "}
            <select
              value={dietType}
              onChange={(e) => setDietType(e.target.value)}
            >
              <option value="">(none)</option>
              <option value="balanced">balanced</option>
              <option value="high_protein">high_protein</option>
              <option value="low_carb">low_carb</option>
              <option value="vegetarian">vegetarian</option>
              <option value="vegan">vegan</option>
            </select>
          </label>
        </div>
        <div style={{ marginTop: "0.5rem" }}>
          <label style={{ display: "block" }}>
            Taste preferences (comma separated):{" "}
            <input
              style={{ width: "100%" }}
              value={tastePrefs}
              onChange={(e) => setTastePrefs(e.target.value)}
            />
          </label>
          <label style={{ display: "block", marginTop: "0.5rem" }}>
            Avoid ingredients (comma separated):{" "}
            <input
              style={{ width: "100%" }}
              value={avoid}
              onChange={(e) => setAvoid(e.target.value)}
            />
          </label>
        </div>
        <div style={{ marginTop: "0.5rem" }}>
          <button
            onClick={generatePlan}
            disabled={loadingPlan || userId == null}
          >
            {loadingPlan ? "Generating..." : "Generate plan"}
          </button>{" "}
          <button onClick={loadHistory} disabled={userId == null}>
            Load meal history
          </button>
          <button onClick={confirmPlan} disabled={confirming || userId == null || plan == null}>
            {confirming ? "Confirming..." : "Confirm plan (update fridge)"}
          </button>
          {historyLoadedOnce && history.length === 0 && (
            <div style={{ marginTop: "0.5rem" }}>You have no history.</div>
          )}
          {confirmNotice && <div style={{ marginTop: "0.5rem" }}>{confirmNotice}</div>}
        </div>
      </section>

      {plan && (
        <section style={{ marginBottom: "2rem" }}>
          <h2>Generated meal plan</h2>
          {plan.days.map((day, idx) => (
            <div
              key={idx}
              style={{
                border: "1px solid #ccc",
                padding: "0.75rem",
                marginBottom: "0.75rem",
              }}
            >
              <h3>Day {idx + 1}</h3>
              {day.meals.map((meal, mIdx) => (
                <div key={mIdx} style={{ marginBottom: "0.5rem" }}>
                  <strong>
                    {meal.meal_type.toUpperCase()}: {meal.name}
                  </strong>
                  <div>
                    <em>Ingredients:</em>{" "}
                    {meal.ingredients
                      .map(
                        (ing) =>
                          `${ing.name} (${ing.quantity_grams} g)`
                      )
                      .join(", ")}
                  </div>
                  <ol>
                    {meal.steps.map((s, si) => (
                      <li key={si}>{s}</li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          ))}

          <h3>Shopping list</h3>
          <ul>
            {plan.shopping_list.map((item, idx) => (
              <li key={idx}>
                {item.name} – {item.quantity_grams} g
              </li>
            ))}
          </ul>
        </section>
      )}

      {history.length > 0 && (
        <section>
          <h2>Meal history (last {history.length})</h2>
          <ul>
            {history.map((h) => (
              <li key={h.meal_entry_id}>
                {new Date(h.created_at).toLocaleString()} –{" "}
                <strong>{h.name}</strong> ({h.meal_type}) [plan{" "}
                {h.meal_plan_id}, day {h.day_index}, meal {h.meal_index}]
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export default App;
