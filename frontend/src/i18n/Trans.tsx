import { Fragment, type ReactNode } from "react";
import { useI18n, type TranslationKey, type Vars } from ".";

/**
 * A translated sentence that contains markup — a link, a bold run, a button.
 *
 * The alternative is splitting the sentence at each tag and translating the
 * fragments ("I accept the" + <a>Terms</a> + "and" + <a>Privacy</a>). That is
 * the single most common way i18n goes wrong, because it silently assumes every
 * language keeps English word order AND leaves each fragment's grammar
 * undecidable in isolation — a Czech noun after a preposition changes case, so
 * "Terms of Service" alone has no correct translation.
 *
 * Here the sentence stays one key with `{name}` holes, and the caller supplies a
 * React node per hole. The translator sees the whole sentence and can move the
 * holes wherever the language needs them.
 *
 *     <Trans k="auth.acceptTerms" nodes={{ terms: <a …/>, privacy: <a …/> }} />
 *
 * Nodes are inserted as-is and never parsed as HTML, so a translation string
 * cannot introduce markup — the set of tags is fixed by the calling component.
 */
export function Trans({
  k,
  nodes,
  vars,
}: {
  k: TranslationKey;
  /** React node per `{name}` placeholder. */
  nodes: Record<string, ReactNode>;
  /** Plain string/number placeholders, substituted before splitting. */
  vars?: Vars;
}) {
  const { t } = useI18n();

  // Split on the placeholders, keeping them (capturing group), then swap each
  // one for its node. Anything without a node stays literal text — the same
  // "a visible hole beats a silent blank" rule as interpolate().
  const parts = t(k, vars).split(/(\{\w+\})/g);

  return (
    <>
      {parts.map((part, i) => {
        const match = /^\{(\w+)\}$/.exec(part);
        if (match && Object.hasOwn(nodes, match[1])) {
          return <Fragment key={i}>{nodes[match[1]]}</Fragment>;
        }
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}
