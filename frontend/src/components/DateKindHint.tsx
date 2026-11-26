import { useI18n } from "../i18n";
import type { DateKind } from "../types";
import { InfoHint } from "./InfoHint";

/**
 * Says whose estimate a date is (docs/food-storage-design.md, "What the user
 * sees"): the FoodKeeper table's or the AI's. A pack date and an unknown
 * kind get none: the first speaks for itself, the second has nothing to say.
 */
export function DateKindHint({ kind }: { kind: DateKind | null | undefined }) {
  const { t } = useI18n();
  const text =
    kind === "estimated_table" ? t("storage.kindHintTable")
      : kind === "estimated_ai" ? t("storage.kindHintAi")
        : null;
  if (text === null) return null;
  return (
    <span style={{ marginLeft: "0.3rem" }}>
      <InfoHint text={text} label={t("storage.kindHintLabel")} />
    </span>
  );
}
