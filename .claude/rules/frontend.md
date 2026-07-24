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

## Layout stability / CLS — don't shift content under the user's cursor (recurring bug)
Conditionally rendering a block **in document flow** (`{cond && <Bar/>}` for a
selection bar, banner, toast, spinner, inline error) pushes everything below it down
the moment it mounts — the classic **Cumulative Layout Shift (CLS)**. This shipped
on the admin bulk-actions bar (#268): selecting a row jumped the whole user table
down, so the control the user was reaching for slid out from under the cursor. The
app is 100% inline styles with lots of `{cond && …}` rendering, so the trap is
everywhere. So:

- **Anything that toggles on/off over existing content** (selection bars, toasts,
  "N selected" banners, inline validation) must **not** land in flow above content
  the user is about to click. Either float it — `position: fixed`/`absolute` is out
  of flow and shifts nothing (what #268 switched to) — or **reserve the space** up
  front (an always-present fixed-height container whose contents swap).
- **Images / async embeds:** give an explicit `width`/`height` (or an aspect-ratio
  box) so they don't reflow when they load.

### The three Core Web Vitals (what Search Console grades)
A moving/janky page is a real UX defect, not just a metric. **CLS** (above) is the
one that keeps biting at the component level; the other two are more architectural —
worth knowing, rarely a per-change item:
- **LCP (Largest Contentful Paint)** — render speed of the biggest above-the-fold
  element. A bundle-size / image-weight / server-response concern; watch it when
  adding a heavy dep or a large hero image.
- **INP (Interaction to Next Paint)** — input responsiveness (replaced FID in 2024).
  Don't do heavy synchronous work in a click/keydown handler — same "never block the
  event loop" spirit as the backend. react-query already runs fetches asynchronously,
  so data loading doesn't stall interactions; the risk is your own sync work.

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
