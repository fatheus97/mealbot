// Tab shapes + the aria id helpers, split out of Tabs.tsx so that component
// file only exports a component (react-refresh/only-export-components).

export interface TabDef {
  id: string;
  label: string;
}

/** DOM id for a tab button — pair with `tabPanelId` for aria wiring. */
export function tabButtonId(idBase: string, id: string): string {
  return `${idBase}-tab-${id}`;
}

/** DOM id for the panel a tab controls. */
export function tabPanelId(idBase: string, id: string): string {
  return `${idBase}-panel-${id}`;
}
