import type { CSSProperties } from "react";
import { useI18n } from "../i18n";
import {
  useLocaleStore,
  UI_LOCALES,
  LOCALE_NAMES,
  type Locale,
} from "../store/useLocaleStore";

/**
 * UI language picker.
 *
 * ─── Why a <select> and not flags ──────────────────────────────────────────
 * A flag is a COUNTRY, and a country is not a language. English has no flag
 * that is not wrong for most of the people who speak it — picking the US or UK
 * one tells a reader in Ireland, India or Australia that this menu is not for
 * them, and the same trap waits for German (DE/AT/CH) and Portuguese (PT/BR).
 * Flags also carry political weight no settings control should be asserting.
 *
 * The native <select> costs nothing and brings keyboard support, screen-reader
 * announcement, and the platform's own picker on mobile — all of which a
 * custom flag dropdown would have to reimplement. It also stays legible as the
 * list grows past the point where a row of flags fits.
 *
 * Each language is named IN ITSELF ("Čeština", not "Czech"): someone who needs
 * this control is, by definition, the person least able to read the current
 * language.
 *
 * ─── Deliberately dependency-free ──────────────────────────────────────────
 * No auth, no react-query, no profile fetch. It reads and writes one zustand
 * value, so it can be mounted anywhere — including logged-out screens and,
 * later, the static landing page — without dragging providers along.
 */
export function LanguageSwitcher({ style }: { style?: CSSProperties }) {
  const { t, locale } = useI18n();
  const setLocale = useLocaleStore((s) => s.setLocale);

  return (
    <label style={{ ...wrap, ...style }}>
      {/* Visually hidden rather than absent: an unlabelled <select> announces
          only its current value, so a screen-reader user hears "English" with
          no indication of what it controls. */}
      <span style={srOnly}>{t("lang.label")}</span>
      <span aria-hidden="true" style={{ fontSize: "1rem", lineHeight: 1 }}>
        🌐
      </span>
      <select
        value={locale}
        onChange={(e) => setLocale(e.target.value as Locale)}
        style={select}
      >
        {UI_LOCALES.map((code) => (
          <option key={code} value={code}>
            {LOCALE_NAMES[code]}
          </option>
        ))}
      </select>
    </label>
  );
}

const wrap: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: "0.3rem",
  cursor: "pointer",
};

// Explicit background AND colour together, per .claude/rules/frontend.md: a
// bare <select> inherits the adaptive text colour, which goes white-on-white
// once a background is set anywhere up the tree.
//
// NO inline `fontSize`. index.css forces `select { font-size: 16px }` under
// 640px because iOS auto-zooms the whole page when a focused field is smaller,
// and an inline value silently beats that stylesheet rule. This control is the
// first thing a non-English speaker reaches for, so zooming the layout out from
// under them on tap is the worst possible place for it.
const select: CSSProperties = {
  padding: "0.3rem 0.4rem",
  borderRadius: 6,
  border: "1px solid #94a3b8",
  backgroundColor: "#ffffff",
  color: "#111111",
  fontFamily: "inherit",
  cursor: "pointer",
};

/**
 * The standard clip-rect pattern: removed from the visual layout but still in
 * the accessibility tree. `display:none` / `visibility:hidden` would take it
 * out of both, which is exactly what must not happen to a label.
 */
const srOnly: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
  border: 0,
};
