# Frontend Rules

## Theme / colour contrast — CHECK THIS EVERY TIME (recurring bug)
`frontend/src/index.css` is the **stock Vite template**: it is **dark-by-default**
(`background-color:#242424`, light text) and only turns light under
`@media (prefers-color-scheme: light)`. The app has **no designed theme system** —
it stays legible in dark mode purely by leaning on the browser's *adaptive default
text colour*. This has repeatedly caused white-on-white / dark-on-dark bugs in OS
dark mode. So:

- **Never hardcode a light-theme colour that assumes a light background.** Dark
  text (`#111`, `#374151`, …) placed directly on the page background is invisible
  in dark mode; an element with `background:#fff` and **no explicit `color`**
  inherits the light default text → white-on-white in dark mode.
- **Rule of thumb: whenever you set a `background`, set an explicit contrasting
  `color` too.** For a block of content, pick ONE and be consistent: either put it
  on an explicit surface (`background` + explicit dark `color`, e.g. a light card),
  or leave text colour to the adaptive default. The trap is mixing them —
  hardcoded dark text on the adaptive (transparent) page background.
- Inline styles can't use `@media (prefers-color-scheme)` (same reason
  `useIsMobile` exists for responsiveness). To be theme-aware, use a
  self-contained explicit surface, or a `matchMedia`-driven hook.

## Verify BOTH colour schemes before shipping ANY visible UI change (mandatory)
Drive the browser preview and check **dark AND light**:
`resize_window { colorScheme: "dark" }`, then `"light"`. Confirm real contrast —
compare computed `color` vs `background` (via `javascript_tool` / `getComputedStyle`)
or a screenshot. A two-theme check is **not optional** for visible changes; the
white-on-white bug has shipped more than once. (A proper automated visual-regression
setup — Playwright snapshots in dark+light — is the long-term fix; tracked under
ROADMAP "Frontend E2E (U-8)". Until then this manual check is the guardrail.)

## Other conventions
- Responsiveness is JS-driven via `useIsMobile()` (the app is 100% inline
  `style={}`, so CSS `@media` can't reach it). Test mobile with
  `setMobileViewport(true)` and the preview at 375px.
- Typecheck with **`tsc -b`** (not `tsc --noEmit`) — it covers test files and
  matches the Docker build. Every PR includes Vitest tests for new/changed UI.
- Running tooling on the Windows host: `tsc`/`eslint` run via
  `node node_modules/typescript/bin/tsc -b` / `node node_modules/eslint/bin/eslint.js .`
  (pure JS). **Vitest/Vite can't run on the host** (missing win32 native bindings) —
  run them in a `node:26.4.0` container with a cached `node_modules` volume, and
  drive the browser preview via a throwaway Vite container on the compose network
  (`VITE_PROXY_TARGET=http://backend:8000`). Exact commands are in project memory.
