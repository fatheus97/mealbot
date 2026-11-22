import { useI18n, type TranslationKey } from "../../i18n";
import { Trans } from "../../i18n/Trans";
import { useCookTemperatures } from "../../hooks/useServerState";
import type { CookCategory, CookSource, CookTemperatureLine, IngredientAmount } from "../../types";

// Literal maps, never `storage.${category}`: a template key would exempt every
// storage.* key from the orphan check (keyUsage.test.ts). The CI job "locale
// parity" checks these unions against backend/data/storage.
const FOOD_KEY: Record<CookCategory, TranslationKey> = {
  poultry: "storage.foodPoultry",
  minced: "storage.foodMinced",
  pork: "storage.foodPork",
  egg: "storage.foodEgg",
  fish: "storage.foodFish",
};
const SOURCE_KEY: Record<CookSource, TranslationKey> = {
  szu: "storage.sourceSzu",
  fsa: "storage.sourceFsa",
  efsa: "storage.sourceEfsa",
  usda: "storage.sourceUsda",
};

// Pages for people at higher risk (docs/food-storage-design.md). Constants, so
// the line still renders when the lookup fails or nothing matched.
export const NHS_AT_RISK_URL = "https://www.nhs.uk/pregnancy/keeping-well/foods-to-avoid/";
export const SZU_AT_RISK_URL = "https://szu.gov.cz/wp-content/uploads/2023/02/alim_nakazy_shrnuti_FIN_2022.pdf";

// Light enough on cook mode's #0b1220; the app's usual link blue is not.
const link: React.CSSProperties = { color: "#93c5fd" };
const line: React.CSSProperties = { margin: "0 0 0.35rem" };

const externalLink = (href: string, text: string) => (
  // A new tab: leaving the SPA would lose an unsaved Cook Now recipe.
  <a href={href} target="_blank" rel="noopener noreferrer" style={link}>
    {text}
  </a>
);

/** How hot the dish's meat, fish and eggs are cooked, one line per matched
 *  category, then the line for people at higher risk. Every number comes from
 *  the server's table (design check 7); none is written here. */
export function CookTemperatures({ ingredients }: { ingredients: IngredientAmount[] }) {
  const { t } = useI18n();
  const { data } = useCookTemperatures(ingredients);

  const text = (row: CookTemperatureLine): string => {
    const food = t(FOOD_KEY[row.category]);
    const figure =
      row.hold_c !== null && row.hold_min !== null
        ? t("storage.cookHold", { food, core: row.core_c, hold: row.hold_c, minutes: row.hold_min })
        : t("storage.cookCore", { food, core: row.core_c });
    const sources = row.sources.map((s) => t(SOURCE_KEY[s])).join(", ");
    return `${figure} ${t(row.us_only ? "storage.cookSourceUs" : "storage.cookSources", { sources })}`;
  };

  // A category or source this build does not know is skipped rather than
  // rendered as a raw key; the CI contract job keeps the two sides in step.
  const known = (data?.lines ?? []).filter(
    (row) => Object.hasOwn(FOOD_KEY, row.category) && row.sources.every((s) => Object.hasOwn(SOURCE_KEY, s)),
  );

  return (
    <>
      {known.map((row) => (
        <p key={row.category} style={line}>
          {text(row)}
        </p>
      ))}
      <p style={line}>
        <Trans
          k="storage.atRisk"
          nodes={{ nhs: externalLink(NHS_AT_RISK_URL, "NHS"), szu: externalLink(SZU_AT_RISK_URL, "SZÚ") }}
        />
      </p>
    </>
  );
}
