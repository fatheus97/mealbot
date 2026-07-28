import { createPortal } from "react-dom";
import { useCookTimers } from "../../contexts/CookTimerContext";
import { formatClock } from "./cookMode.utils";
import { useIsMobile } from "../../hooks/useIsMobile";

// The floating bubble: what a running timer looks like once you've left cook
// mode. Hidden while cook mode is open, since that surface shows the same
// timers in its own bar.
//
// Theme: every surface here sets BOTH an explicit background and an explicit
// colour, so it is legible regardless of the OS colour scheme — it never leans
// on the adaptive default text colour it would inherit from the page.
//
// Layout: `position: fixed` is out of flow, so appearing and disappearing
// shifts nothing (the CLS trap the admin bulk-actions bar hit in #268). Anchored
// bottom-LEFT because the cookbook and calendar FABs own the bottom-right
// corner, and capped in width so it can never reach them.

const bubble: React.CSSProperties = {
  background: "#0f172a",
  color: "#e2e8f0",
  border: "1px solid #334155",
  borderRadius: "999px",
  padding: "0.4rem 0.5rem 0.4rem 0.9rem",
  display: "flex",
  alignItems: "center",
  gap: "0.6rem",
  boxShadow: "0 6px 20px rgba(0,0,0,0.35)",
  pointerEvents: "auto",
};

const pillBtn: React.CSSProperties = {
  padding: "0.2rem 0.6rem",
  borderRadius: "999px",
  border: "1px solid #334155",
  background: "#1e293b",
  color: "#e2e8f0",
  cursor: "pointer",
  fontSize: "0.8rem",
  flexShrink: 0,
};

// Wraps the clock + name in a button when there's somewhere to go back to, and
// leaves them as plain text otherwise — rather than rendering a dead button.
function ReopenTarget({
  onReopen,
  label,
  children,
}: {
  onReopen?: () => void;
  label: string;
  children: React.ReactNode;
}) {
  // No `flex: 1` here. A flex-basis of 0 makes this contribute nothing to the
  // bubble's intrinsic width, and since the bubble is a fixed-position element
  // sized by its content, the whole thing collapses to the width of the Pause
  // and ✕ buttons. `minWidth: 0` is still needed so the name can ellipsis.
  const shared: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: "0.6rem",
    minWidth: 0,
  };
  if (!onReopen) return <div style={shared}>{children}</div>;
  return (
    <button
      type="button"
      onClick={onReopen}
      aria-label={`Back to cooking ${label}`}
      title={`Back to cooking ${label}`}
      style={{
        ...shared,
        background: "none",
        border: "none",
        padding: 0,
        margin: 0,
        font: "inherit",
        color: "inherit",
        cursor: "pointer",
        textAlign: "left",
      }}
    >
      {children}
    </button>
  );
}

export function FloatingTimers() {
  const { timers, bubbleVisible, toggle, dismiss } = useCookTimers();
  const isMobile = useIsMobile();

  if (!bubbleVisible) return null;

  return createPortal(
    <div
      style={{
        position: "fixed",
        bottom: "1.5rem",
        left: isMobile ? "0.75rem" : "1.5rem",
        // Never grow into the FAB column on the right.
        maxWidth: `min(22rem, calc(100vw - ${isMobile ? "0.75rem" : "1.5rem"} - 5.5rem))`,
        // Many timers scroll rather than climbing the whole viewport.
        maxHeight: "40vh",
        overflowY: "auto",
        zIndex: 90,
        display: "flex",
        flexDirection: "column",
        gap: "0.5rem",
        pointerEvents: "none",
      }}
    >
      {timers.map((t) => (
        <div key={t.id} style={bubble} role="group" aria-label={`Timer for ${t.label}`}>
          {/* The clock + name are one target that takes you back into cooking,
              landing on the step you left (cook mode restores it from
              localStorage). Falls back to plain text when the surface that
              started the timer didn't supply a way back. Pause and ✕ stay
              separate controls so tapping "resume cooking" can't cancel. */}
          <ReopenTarget onReopen={t.onReopen} label={t.label}>
            <span
              aria-label={`Timer ${formatClock(t.remaining)} remaining`}
              style={{
                fontWeight: 700,
                fontVariantNumeric: "tabular-nums",
                color: t.finished ? "#f87171" : "#22c55e",
                flexShrink: 0,
              }}
            >
              {formatClock(t.remaining)}
            </span>
            <span
              style={{
                fontSize: "0.85rem",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                minWidth: 0,
              }}
              title={t.label}
            >
              {t.finished ? "⏰ Time's up!" : t.label}
            </span>
          </ReopenTarget>
          {!t.finished && (
            <button type="button" style={pillBtn} onClick={() => toggle(t.id)}>
              {t.running ? "Pause" : "Resume"}
            </button>
          )}
          <button
            type="button"
            style={{ ...pillBtn, padding: "0.2rem 0.5rem" }}
            onClick={() => dismiss(t.id)}
            aria-label={`Dismiss timer for ${t.label}`}
          >
            ✕
          </button>
        </div>
      ))}
    </div>,
    document.body,
  );
}
