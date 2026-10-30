import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { useIsMobile } from "../hooks/useIsMobile";

interface InfoHintProps {
  /** The short explanation revealed in the tooltip. */
  text: string;
  /** Accessible name for the trigger. Defaults to a generic "More information". */
  label?: string;
}

/** Bubble width in px; also the room a right-anchored bubble needs left of the trigger. */
const BUBBLE_WIDTH = 240;
/** Minimum gap kept between the bubble and the viewport edge. */
const EDGE_GAP = 8;

/** Which trigger edge the bubble is pinned to, and how wide it may grow there. */
interface Placement {
  side: "left" | "right";
  maxWidth: number;
}

/**
 * Measured at open time, in the same handler that opens the hint, so the bubble's
 * first paint is already on the right side.
 *
 * Right-anchored (the default) the bubble grows LEFTWARD from the trigger; near the
 * left edge of a narrow screen that put most of it off-screen, cut off and
 * unscrollable. It flips to grow rightward only when the default doesn't fit AND the
 * right side has more room (flipping whenever the default doesn't fit would squeeze it
 * narrower than it needs to be). maxWidth is clamped to the room actually left on the
 * chosen side, so neither side can overflow.
 */
function placeFor(trigger: HTMLElement): Placement {
  const rect = trigger.getBoundingClientRect();
  const roomLeftward = rect.right;
  const roomRightward = window.innerWidth - rect.left;
  const side =
    roomLeftward >= BUBBLE_WIDTH + EDGE_GAP || roomLeftward >= roomRightward ? "right" : "left";
  const room = side === "left" ? roomRightward : roomLeftward;
  return { side, maxWidth: Math.min(window.innerWidth - 2 * EDGE_GAP, room - EDGE_GAP) };
}

/**
 * A small "i"-in-a-circle affordance: hover, keyboard-focus, or tap it to reveal a short
 * explanation. Intended as the app's reusable "explain this" primitive (ROADMAP U-9) —
 * inline hints instead of intrusive intro tours.
 *
 * Deliberately theme-robust and CLS-safe (see .claude/rules/frontend.md):
 *  - The circle AND the bubble carry their OWN explicit surface + colour, so the control
 *    stays legible on any background — a light card OR the app's adaptive dark page —
 *    without leaning on inherited/adaptive text colour (the white-on-white trap).
 *  - The bubble is absolutely positioned (out of document flow), so revealing it never
 *    pushes surrounding content around under the user's cursor.
 *  - Near a screen edge the bubble opens toward the roomier side (see placeFor).
 *
 * Escape CONSUMES the event while the bubble is open, so a hint inside a modal that also
 * closes on Escape (ModalShell, PaywallModal, CookbookModal) dismisses only the hint —
 * one Escape, one dismissal, innermost first. Without this the modal closed too, taking
 * the thing the user was reading the hint ABOUT with it. Same technique and reasoning as
 * ConfirmDialog: capture phase + stopImmediatePropagation, because bubble-vs-capture
 * ordering between two `window` listeners is not well-defined.
 */
export function InfoHint({ text, label = "More information" }: InfoHintProps) {
  // null = closed. One state, so the bubble can never be open without a placement.
  const [placement, setPlacement] = useState<Placement | null>(null);
  const open = placement !== null;
  const close = () => setPlacement(null);
  // Every open path (hover, focus, click/tap) goes through here: same measurement.
  const show = (e: { currentTarget: HTMLElement }) => setPlacement(placeFor(e.currentTarget));
  const rootRef = useRef<HTMLSpanElement>(null);
  const tooltipId = useId();
  const isMobile = useIsMobile();
  // 18px reads as an inline glyph on desktop; on touch, 24px meets the WCAG 2.5.8
  // minimum tap target AND overrides index.css's mobile `button { min-height: 40px }`
  // (which would otherwise stretch a fixed-height-only circle into an 18×40 pill).
  const size = isMobile ? 24 : 18;

  // Dismiss on outside pointer (tap-away) or Escape (keyboard) — only while open, so we
  // don't keep global listeners registered for every idle hint on the page. We listen on
  // `pointerdown`, NOT `mousedown`: on iOS Safari a tap on a non-interactive region emits
  // no synthetic mouse event (and iOS sticky focus can suppress onBlur), so mousedown-only
  // dismissal would leave the bubble stuck open. pointerdown fires for any tap.
  useEffect(() => {
    if (!open) return;
    const onDocPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setPlacement(null);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // Consume it: the hint is the innermost thing on screen, so one Escape
      // should dismiss one layer. An enclosing modal (ModalShell, PaywallModal,
      // CookbookModal) also listens on window, and without this BOTH close —
      // taking away the thing the user opened the hint about. Registered in the
      // capture phase below for the same reason ConfirmDialog is: ordering
      // between two bubble-phase window listeners is not well-defined.
      e.stopImmediatePropagation();
      setPlacement(null);
    };
    document.addEventListener("pointerdown", onDocPointerDown);
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", onDocPointerDown);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [open]);

  return (
    <span ref={rootRef} style={rootStyle}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? tooltipId : undefined}
        onMouseEnter={show}
        onMouseLeave={close}
        onFocus={show}
        onBlur={close}
        // Open (not toggle) on click: on touch, the tap also emits a synthetic
        // mouseenter, so a toggle would net to "closed" and the tap would look dead.
        // Tap-away / Escape / blur handle dismissal instead.
        onClick={(e) => {
          e.stopPropagation();
          show(e);
        }}
        style={{ ...triggerStyle, width: size, height: size, minWidth: size, minHeight: size }}
      >
        <span aria-hidden="true">i</span>
      </button>
      {placement && (
        <span
          role="tooltip"
          id={tooltipId}
          style={{
            ...bubbleStyle,
            ...(placement.side === "left" ? { left: 0 } : { right: 0 }),
            maxWidth: placement.maxWidth,
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}

const rootStyle: CSSProperties = {
  position: "relative",
  display: "inline-flex",
  verticalAlign: "middle",
};

const triggerStyle: CSSProperties = {
  // width/height/minWidth/minHeight are applied per-viewport at the call site (see `size`).
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 0,
  flexShrink: 0,
  borderRadius: "50%",
  border: "1px solid #94a3b8", // defines the circle against a white surface (else too faint)
  background: "#e5e7eb", // explicit light circle — self-contained, not the page bg
  color: "#374151", // dark glyph on the light circle → contrast in light AND dark mode
  fontSize: 12,
  fontWeight: 700,
  fontStyle: "italic",
  fontFamily: "Georgia, 'Times New Roman', serif",
  lineHeight: 1,
  cursor: "pointer",
};

const bubbleStyle: CSSProperties = {
  position: "absolute",
  bottom: "calc(100% + 8px)", // float above the icon so it never covers the trigger
  // left/right and maxWidth are measured per open (see placeFor), never fixed here.
  zIndex: 20,
  width: BUBBLE_WIDTH,
  boxSizing: "border-box", // so maxWidth bounds the painted box, padding included
  padding: "0.5rem 0.625rem",
  borderRadius: 8,
  background: "#1f2937", // self-contained dark surface — legible over any page
  color: "#f9fafb",
  fontSize: 12,
  fontWeight: 400,
  fontStyle: "normal",
  lineHeight: 1.45,
  textAlign: "left",
  boxShadow: "0 6px 20px rgba(0, 0, 0, 0.22)",
  pointerEvents: "none", // purely informational — never intercepts a click
};
