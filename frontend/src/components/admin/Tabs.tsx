import type { CSSProperties, KeyboardEvent } from "react";
import { colors } from "./theme";
import { tabButtonId, tabPanelId, type TabDef } from "./tabIds";

interface TabsProps {
  tabs: TabDef[];
  /** Currently-selected tab id (controlled). */
  active: string;
  onChange: (id: string) => void;
  /** Accessible name for the tablist. */
  ariaLabel: string;
  /**
   * Prefix for the generated tab/panel element ids, so the `aria-controls` /
   * `aria-labelledby` wiring stays unique if more than one tab group mounts.
   */
  idBase?: string;
}

/**
 * Accessible, dependency-free tab bar (WAI-ARIA tabs pattern): one focusable
 * tab at a time (roving `tabIndex`), Arrow/Home/End move selection and focus
 * together, and `aria-controls` links each tab to its panel. Controlled — the
 * parent owns the active id and renders the matching panel with
 * `role="tabpanel"` + `id={tabPanelId(...)}` + `aria-labelledby={tabButtonId(...)}`.
 *
 * Styling assumes it sits on the admin surface's pinned light background (see
 * theme.ts) — the active tab is marked by an accent underline AND weight/colour,
 * never colour alone.
 */
export function Tabs({ tabs, active, onChange, ariaLabel, idBase = "admin" }: TabsProps) {
  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number | null = null;
    if (e.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    if (next === null) return;
    e.preventDefault();
    const target = tabs[next];
    onChange(target.id);
    // Move focus to follow selection, per the ARIA tabs pattern.
    document.getElementById(tabButtonId(idBase, target.id))?.focus();
  }

  return (
    <div role="tablist" aria-label={ariaLabel} style={tablistStyle}>
      {tabs.map((t, i) => {
        const selected = t.id === active;
        return (
          <button
            key={t.id}
            id={tabButtonId(idBase, t.id)}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={tabPanelId(idBase, t.id)}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => onKeyDown(e, i)}
            style={tabStyle(selected)}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

const tablistStyle: CSSProperties = {
  display: "flex",
  gap: "0.25rem",
  flexWrap: "wrap",
  borderBottom: `2px solid ${colors.border}`,
  marginBottom: "1.5rem",
};

function tabStyle(selected: boolean): CSSProperties {
  return {
    padding: "0.55rem 1.1rem",
    background: "none",
    border: "none",
    cursor: "pointer",
    fontSize: 15,
    fontWeight: selected ? 600 : 400,
    color: selected ? colors.accent : colors.textBody,
    borderBottom: `2px solid ${selected ? colors.accent : "transparent"}`,
    marginBottom: -2,
  };
}
