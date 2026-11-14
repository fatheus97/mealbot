import type { CSSProperties } from "react";
import { useI18n, type TranslationKey } from "../i18n";
import { Trans } from "../i18n/Trans";
import { formatNumber } from "../i18n/localeFormat";
import { formatISODate } from "../utils/planDates";
import type { Locale } from "../store/useLocaleStore";
import type { MealNutrition, NutrientValues, SourceAttribution } from "../types";

// The per-meal nutrition chip and its inline panel (docs/nutrition-design.md,
// "What the user sees"). Both render inside MealCard, on MealPlanner's explicit
// light surface; each sets its own background AND colour anyway, so neither
// depends on where it lands.
//
// Rounding is display-only (the API sends unrounded values so the maths can be
// redone). An approximate figure rounds to the nearest 10 kcal and 1 g, with
// "<10" / "<1" for a trace. An "at least" figure rounds DOWN, because rounding
// a lower bound up would state a minimum the meal does not reach. The
// provenance table keeps whole kcal, because its job is to let anyone redo the
// sum.

function roundedKcal(kcal: number, locale: Locale, atLeast: boolean): string {
  if (atLeast) return formatNumber(Math.floor(kcal / 10) * 10, locale);
  if (kcal > 0 && kcal < 5) return `<${formatNumber(10, locale)}`;
  return formatNumber(Math.round(kcal / 10) * 10, locale);
}

function roundedGrams(grams: number, locale: Locale, atLeast: boolean): string {
  if (atLeast) return formatNumber(Math.floor(grams), locale);
  if (grams > 0 && grams < 0.5) return `<${formatNumber(1, locale)}`;
  return formatNumber(Math.round(grams), locale);
}

const chipStyle: CSSProperties = {
  marginLeft: "0.4rem",
  padding: "0.1rem 0.5rem",
  borderRadius: "10px",
  fontSize: "0.75rem",
  fontWeight: 600,
  // Neutral grey on purpose: the design bans green/red coding of nutrition.
  background: "#f3f4f6",
  color: "#374151",
  border: "1px solid #d1d5db",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

export function NutritionChip({
  figure,
  expanded,
  panelId,
  isMobile,
  onToggle,
}: {
  figure: MealNutrition;
  expanded: boolean;
  panelId: string;
  isMobile: boolean;
  onToggle: () => void;
}) {
  const { t, locale } = useI18n();
  let label = t("nutrition.chipNoData");
  if (figure.per_serving) {
    const kcal = roundedKcal(figure.per_serving.kcal, locale, !figure.complete);
    const key: TranslationKey = figure.complete
      ? isMobile ? "nutrition.chipShort" : "nutrition.chip"
      : isMobile ? "nutrition.chipAtLeastShort" : "nutrition.chipAtLeast";
    label = t(key, { kcal });
  }
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      // Only while open: the panel is not in the DOM otherwise, and a
      // reference to a missing id is an ARIA error.
      aria-controls={expanded ? panelId : undefined}
      style={chipStyle}
    >
      {label}
    </button>
  );
}

/** The chip's box, invisible, held while the figures load so the header row
 *  does not grow (and push the card down) when they arrive. A real disabled
 *  button, so it gets exactly the chip's size, mobile min-height included. */
export function NutritionChipPlaceholder({ isMobile }: { isMobile: boolean }) {
  const { t, locale } = useI18n();
  return (
    <button type="button" disabled tabIndex={-1} aria-hidden="true" style={{ ...chipStyle, visibility: "hidden" }}>
      {t(isMobile ? "nutrition.chipShort" : "nutrition.chip", { kcal: formatNumber(1000, locale) })}
    </button>
  );
}

const panelStyle: CSSProperties = {
  margin: "0.5rem 0",
  padding: "0.5rem 0.75rem",
  backgroundColor: "#fff",
  color: "#111",
  border: "1px solid #ddd",
  borderRadius: "6px",
  fontSize: "0.85rem",
};
const muted: CSSProperties = { color: "#555", margin: "0.35rem 0" };
const th: CSSProperties = { textAlign: "left", padding: "0.2rem 0.5rem 0.2rem 0", fontWeight: 600 };
const td: CSSProperties = { padding: "0.2rem 0.5rem 0.2rem 0", verticalAlign: "top" };
const num: CSSProperties = { ...td, textAlign: "right", whiteSpace: "nowrap" };
const row: CSSProperties = { borderBottom: "1px solid #eee" };
// index.css paints links #646cff, which fails AA on this white panel.
const link: CSSProperties = { color: "#1d4ed8", textDecoration: "underline" };

function PerServing({ values, complete }: { values: NutrientValues; complete: boolean }) {
  const { t, locale } = useI18n();
  const atLeast = !complete;
  const g = t("editor.grams");
  const macros: [TranslationKey, number][] = [
    ["nutrition.protein", values.protein],
    ["nutrition.fat", values.fat],
    ["nutrition.carbohydrate", values.carbohydrate],
  ];
  return (
    <table style={{ borderCollapse: "collapse", margin: "0.25rem 0" }}>
      <caption style={{ textAlign: "left", fontWeight: 600, paddingBottom: "0.2rem" }}>
        {t(complete ? "nutrition.perServing" : "nutrition.perServingAtLeast")}
      </caption>
      <tbody>
        <tr style={row}>
          <th scope="row" style={th}>{t("nutrition.energy")}</th>
          <td style={num}>
            {roundedKcal(values.kcal, locale, atLeast)} {t("nutrition.kcalUnit")}{" "}
            <small style={{ color: "#555" }}>
              ({roundedKcal(values.kj, locale, atLeast)} {t("nutrition.kjUnit")})
            </small>
          </td>
        </tr>
        {macros.map(([key, grams]) => (
          <tr key={key} style={row}>
            <th scope="row" style={th}>{t(key)}</th>
            <td style={num}>{roundedGrams(grams, locale, atLeast)} {g}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Provenance({ figure }: { figure: MealNutrition }) {
  const { t, locale } = useI18n();
  const rows = figure.ingredients.filter(
    (ing) => (ing.status === "counted" || ing.status === "seasoning") && ing.alim_code !== null,
  );
  if (rows.length === 0) return null;
  return (
    <>
      {/* Six columns do not fit 375px; the table scrolls inside the panel. */}
      <div style={{ overflowX: "auto", margin: "0.35rem 0" }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #ccc" }}>
              <th scope="col" style={th}>{t("nutrition.colIngredient")}</th>
              <th scope="col" style={{ ...th, textAlign: "right" }}>{t("nutrition.colGrams")}</th>
              <th scope="col" style={th}>{t("nutrition.colFood")}</th>
              <th scope="col" style={{ ...th, textAlign: "right" }}>{t("nutrition.colPer100")}</th>
              <th scope="col" style={{ ...th, textAlign: "right" }}>{t("nutrition.colDish")}</th>
              <th scope="col" style={th}>{t("nutrition.colConfidence")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((ing, i) => (
              <tr key={i} style={row}>
                <td style={td}>{ing.name}</td>
                {/* A seasoning is a "to taste" placeholder: the recipe gives no
                    amount, so neither does the table, and it adds 0. */}
                <td style={num}>
                  {ing.status === "seasoning"
                    ? t("nutrition.toTaste")
                    : `${roundedGrams(ing.grams, locale, false)} ${t("editor.grams")}`}
                </td>
                <td style={td}>{ing.source_name} ({ing.alim_code})</td>
                <td style={num}>{ing.per_100g ? formatNumber(ing.per_100g.kcal, locale) : ""}</td>
                <td style={num}>{ing.contribution ? formatNumber(ing.contribution.kcal, locale) : ""}</td>
                <td style={td}>{ing.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* Outside the scroll box: anything that pops out of it (an InfoHint
          bubble) is clipped, since overflow-x:auto makes overflow-y auto too. */}
      <p style={muted}>{t("nutrition.confidenceHint")}</p>
    </>
  );
}

export function NutritionPanel({
  id,
  figure,
  source,
}: {
  id: string;
  figure: MealNutrition;
  source: SourceAttribution;
}) {
  const { t, tn, locale } = useI18n();
  const notCounted = figure.ingredients
    .filter((ing) => ing.status === "not_counted" && ing.reason !== null)
    .map((ing) => `${ing.name} (${t(`nutritionReason.${ing.reason}` as TranslationKey)})`);
  return (
    <div id={id} style={panelStyle}>
      {figure.per_serving ? (
        <>
          <PerServing values={figure.per_serving} complete={figure.complete} />
          <p style={muted}>
            {tn("nutrition.servings", figure.servings)} {t("nutrition.servingNote")}
          </p>
        </>
      ) : (
        <p style={{ margin: "0.35rem 0" }}>{t("nutrition.notEnoughData")}</p>
      )}
      {figure.leftover_of && <p style={muted}>{t("nutrition.leftoverNote")}</p>}
      {notCounted.length > 0 && (
        <p style={{ margin: "0.35rem 0" }}>{t("nutrition.notCounted", { names: notCounted.join(", ") })}</p>
      )}
      <Provenance figure={figure} />
      <p style={muted}>
        {t("nutrition.captionCalculated")} {t("nutrition.captionRealValues")}{" "}
        {t("nutrition.captionNotAdvice")}
      </p>
      {/* Rendered here, inside the panel, so no surface can show a figure
          without its attribution (Etalab 2.0: grantor and update date). */}
      <p style={{ ...muted, marginBottom: 0 }}>
        <Trans
          k="nutrition.source"
          nodes={{
            source: (
              <a href={`https://doi.org/${source.doi}`} target="_blank" rel="noopener noreferrer" style={link}>
                {source.name} ({source.publisher})
              </a>
            ),
          }}
          vars={{ date: formatISODate(source.published, locale) }}
        />
      </p>
    </div>
  );
}
