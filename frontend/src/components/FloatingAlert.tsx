import type { CSSProperties, ReactNode } from "react";

/**
 * An alert that must be seen wherever the user has scrolled to, and stays until
 * dismissed.
 *
 * `position: fixed` so appearing cannot shove content down under the user's
 * cursor (the CLS rule in .claude/rules/frontend.md), and a self-contained
 * opaque surface — background AND colour set together — because inline styles
 * cannot reach `@media (prefers-color-scheme)` and a bare background would go
 * white-on-white in dark mode.
 */
export function FloatingAlert({
  dismissLabel,
  onDismiss,
  children,
}: {
  dismissLabel: string;
  onDismiss: () => void;
  children: ReactNode;
}) {
  return (
    <div role="alert" style={wrap}>
      {children}
      <button type="button" onClick={onDismiss} aria-label={dismissLabel} style={close}>
        &times;
      </button>
    </div>
  );
}

const wrap: CSSProperties = {
  position: "fixed",
  top: "1rem",
  // Centred by the insets, not `left: 50%`: that leaves half the screen as the
  // width available, a tall narrow column on a phone.
  left: "1rem",
  right: "1rem",
  marginInline: "auto",
  width: "fit-content",
  maxWidth: 560,
  boxSizing: "border-box",
  zIndex: 1400,
  display: "flex",
  alignItems: "flex-start",
  gap: "0.75rem",
  backgroundColor: "#fee2e2",
  color: "#7f1d1d",
  border: "1px solid #fecaca",
  borderRadius: 8,
  padding: "0.8rem 1rem",
  boxShadow: "0 2px 12px rgba(0, 0, 0, 0.25)",
};

const close: CSSProperties = {
  background: "none",
  border: "none",
  color: "inherit",
  fontSize: "1.2rem",
  lineHeight: 1,
  cursor: "pointer",
  padding: "0 0.2rem",
};
