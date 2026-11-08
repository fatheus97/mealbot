import type { CSSProperties } from "react";
import { useAuth } from "../contexts/AuthContext";
import { ALLERGENS, DIET_TYPES, type Allergen, type DietType } from "../constants/dietary";
import { MUTED_PAGE_TEXT } from "../constants/theme";
import type { EaterChoice } from "../hooks/useEaterChoice";
import { useI18n } from "../i18n";
import type { HouseholdMember } from "../types";
import { InfoHint } from "./InfoHint";

const isDiet = (d: string): d is DietType => (DIET_TYPES as readonly string[]).includes(d);
const isAllergen = (a: string): a is Allergen => (ALLERGENS as readonly string[]).includes(a);

/**
 * Who a plan or a Cook Now recipe is cooked for, in a shared household, and
 * the union of their saved diets, allergies and ingredients to avoid, shown
 * before Generate (docs/household-design.md, "Diets, allergies and consent").
 * Renders nothing for someone alone in their household, or while households
 * are off: their plans keep today's behaviour, only the typed fields.
 *
 * A member whose consent is not current comes without their profile (the
 * server will not use it), so the summary leaves them out and a note names
 * them instead; for you, the form's consent box covers it.
 *
 * THEME: sits on the adaptive page, so text keeps the page's colour and the
 * muted lines use MUTED_PAGE_TEXT.
 */
export function EaterPicker({
  choice,
  purpose = "cook",
}: {
  choice: EaterChoice;
  /** "repeat": above the plan list, where nothing is picked below and the
   *  copy is checked against the union rather than cooked from it. */
  purpose?: "cook" | "repeat";
}) {
  const { userId } = useAuth();
  const { t } = useI18n();
  const { members, eaters, pick } = choice;
  if (members.length < 2) return null;

  const ticked = members.filter((m) => eaters === null || eaters.includes(m.id));
  // Someone always stays ticked: an empty selection would send `eaters: []`,
  // a plan checked against nobody's saved allergies, and "cooking for nobody"
  // is never what an unticking click meant.
  const lastOne = ticked.length === 1 ? ticked[0].id : null;
  const toggle = (id: number) => {
    if (id === lastOne) return;
    const current = eaters ?? members.map((m) => m.id);
    pick(current.includes(id) ? current.filter((x) => x !== id) : [...current, id]);
  };

  const union = (field: (m: HouseholdMember) => string[]) => [
    ...new Set(ticked.flatMap((m) => (m.profile ? field(m) : []))),
  ];
  const diets = union((m) => m.profile?.diet_types ?? []).filter(isDiet);
  const allergens = union((m) => m.profile?.allergens ?? []).filter(isAllergen);
  const avoid = union((m) => m.profile?.avoid_ingredients ?? []);
  const flagged = ticked.filter((m) => m.needs_consent);
  const others = flagged.filter((m) => m.id !== userId);
  const nothing = diets.length === 0 && allergens.length === 0 && avoid.length === 0;

  return (
    <fieldset style={{ border: "none", margin: 0, padding: 0 }}>
      <legend style={{ display: "flex", alignItems: "center", gap: "0.4rem", padding: 0, fontWeight: 600, fontSize: "0.85rem" }}>
        {t("eaters.title")}
        <InfoHint
          label={t("eaters.hintLabel")}
          text={t(purpose === "repeat" ? "eaters.hintRepeat" : "eaters.hint")}
        />
      </legend>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem 1rem", margin: "0.35rem 0" }}>
        {members.map((member) => (
          <label key={member.id} style={{ display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer", overflowWrap: "anywhere" }}>
            <input
              type="checkbox"
              checked={eaters === null || eaters.includes(member.id)}
              disabled={member.id === lastOne}
              onChange={() => toggle(member.id)}
            />
            {member.id === userId ? t("eaters.you", { email: member.email }) : member.email}
          </label>
        ))}
      </div>
      <div style={{ ...MUTED_PAGE_TEXT, fontSize: "0.8rem" }}>
        {nothing ? (
          // Not while someone ticked has data the notes below name: that would
          // say they have nothing saved.
          flagged.length === 0 && <p style={line}>{t("eaters.summaryNone")}</p>
        ) : (
          <>
            <p style={line}>{t(purpose === "repeat" ? "eaters.summaryTitleRepeat" : "eaters.summaryTitle")}</p>
            {diets.length > 0 && (
              <p style={line}>
                {t("eaters.summaryDiets", { list: diets.map((d) => t(`diet.${d}` as const)).join(", ") })}
              </p>
            )}
            {allergens.length > 0 && (
              <p style={line}>
                {t("eaters.summaryAllergies", {
                  list: allergens.map((a) => t(`allergen.${a}` as const)).join(", "),
                })}
              </p>
            )}
            {avoid.length > 0 && <p style={line}>{t("eaters.summaryAvoid", { list: avoid.join(", ") })}</p>}
          </>
        )}
        {diets.includes("baby_food") && <p style={line}>{t("eaters.babyFood")}</p>}
      </div>
      {choice.youNeedConsent && (
        <p role="note" style={{ ...line, fontSize: "0.8rem" }}>
          {t("eaters.needsYourConsent")}
        </p>
      )}
      {others.map((member) => (
        <p key={member.id} role="note" style={{ ...line, fontSize: "0.8rem" }}>
          {t("eaters.needsConsent", { email: member.email })}
        </p>
      ))}
    </fieldset>
  );
}

const line: CSSProperties = { margin: "0.15rem 0" };
