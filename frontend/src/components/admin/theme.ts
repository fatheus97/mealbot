import type { CSSProperties } from "react";

/**
 * Shared visual tokens for the admin surface.
 *
 * Every value here is an explicit LIGHT-theme colour. The admin dashboard pins
 * its own opaque light surface (`AdminDashboard` mounts `background:
 * colors.surface` + an explicit dark base text colour) because `index.css` is
 * the Vite dark-by-default template — so admin styling must never lean on the
 * browser's adaptive default text colour. Because the surface is opaque and
 * every text colour is explicit, the dashboard renders identically in OS light
 * AND dark mode. See `.claude/rules/frontend.md`.
 *
 * The greys below are the Tailwind slate/grey scale the panels were already
 * using ad-hoc (`#111827`, `#374151`, `#6b7280`, `#9ca3af`, `#e5e7eb`,
 * `#f3f4f6`, `#f9fafb`); this just consolidates them into one named palette so
 * every panel shares it instead of scattering the same hex across files.
 */
export const colors = {
  /** Page background the whole surface is pinned to. */
  surface: "#f9fafb",
  /** Base text colour set on the surface root. */
  baseText: "#1f2937",
  /** Card / panel background. */
  card: "#ffffff",
  /** Primary text — headings and stat values. */
  text: "#111827",
  /** Body copy. */
  textBody: "#374151",
  /**
   * Muted labels, captions, table headers, empty states and placeholder
   * dashes — everything below body copy.
   *
   * There used to be a fainter fourth tier (`textFaint: #9ca3af`) below this
   * one, used for empty-state dashes and sub-labels. It measured 2.43:1 on
   * `surface` and 2.54:1 on `card` — enabled content, well under AA — and
   * there is no room to keep the tier: #6b7280 at 4.63:1 is the LIGHTEST
   * colour that still clears 4.5 on #f9fafb, so any visibly fainter shade
   * fails by construction. Collapsed into this one rather than picking a
   * lighter value that merely looks like it passes.
   */
  textMuted: "#6b7280",
  /** Default border (cards, table header rules). */
  border: "#e5e7eb",
  /** Slightly stronger border (buttons). */
  borderStrong: "#d1d5db",
  /** Subtle border (table row separators). */
  borderSubtle: "#f3f4f6",
  /** Header underline / strong rule. */
  rule: "#334155",
  /** Error text. */
  danger: "#b91c1c",
  /** Primary accent (active tab, links). */
  accent: "#4f46e5",
} as const;

/**
 * Named bar-chart hues. These are the existing per-chart colours, centralised so
 * the charts stay visually distinct but are assigned in one place rather than
 * hardcoded at each call site.
 */
export const chart = {
  generations: "#8b5cf6",
  usage: "#4f46e5",
  usageBySurface: "#0ea5e9",
  usageByProvider: "#10b981",
  activity: "#f59e0b",
  activityBySurface: "#ef4444",
  funnel: "#0d9488",
} as const;

export const radius = 8;

/** Reusable card container (stat cards + panel wrappers). */
export const cardStyle: CSSProperties = {
  border: `1px solid ${colors.border}`,
  borderRadius: radius,
  background: colors.card,
  padding: "0.9rem 1rem",
};

/** Section heading (`<h3>`). */
export const sectionTitleStyle: CSSProperties = {
  margin: "0 0 0.75rem",
  fontSize: 16,
  color: colors.text,
};

/** Small caption above a chart / control ("By feature", etc.). */
export const captionStyle: CSSProperties = {
  fontSize: 13,
  color: colors.textBody,
  marginBottom: 6,
};
