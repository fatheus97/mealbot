import { useEffect } from "react";
import type { ReactNode } from "react";
import { useIsMobile } from "../hooks/useIsMobile";

interface ModalShellProps {
  /** Dismiss handler — fired on a backdrop click (and on Escape when
   *  {@link ModalShellProps.closeOnEscape} is on). */
  onClose: () => void;
  /** Accessible name for the dialog (screen-reader label on the backdrop). */
  ariaLabel: string;
  /**
   * On phone-sized viewports, fill the whole screen edge-to-edge (no gutter, no
   * rounded corners) instead of floating a centered card. Height is `100dvh`
   * (dynamic viewport) so the mobile browser's URL bar can't clip the bottom.
   * The child is expected to render at `width/height: 100%` (and drop its own
   * border-radius) to fill this. Defaults to true — it's what a modal almost
   * always wants on a phone, and where the app's earlier "big edges on mobile"
   * bug lived.
   */
  mobileFullScreen?: boolean;
  /**
   * Close on Escape. Defaults true. Opt OUT when the modal has bespoke Escape
   * semantics (e.g. the cookbook maps Escape to "spread → index" before close),
   * so ModalShell and the consumer don't both handle the same keypress.
   */
  closeOnEscape?: boolean;
  /**
   * Freeze background scroll while open (save + restore `body.overflow`).
   * Defaults true — a full-screen mobile modal with the page scrolling behind
   * it is a bug. Opt out if the consumer already manages this itself.
   */
  lockBodyScroll?: boolean;
  /** Stacking order of the backdrop. Defaults 1000 (the app's modal layer). */
  zIndex?: number;
  children: ReactNode;
}

/**
 * Shared backdrop + positioning shell for the app's full-screen-capable modals.
 *
 * - **Desktop:** a dimmed backdrop that centers the child; the child sets its
 *   own size (so `min(…, Npx)` widths resolve against the viewport as before).
 * - **Mobile:** edge-to-edge full screen (see {@link ModalShellProps.mobileFullScreen}).
 *
 * **Dismiss:** a click whose target is the backdrop *itself* closes; descendant
 * clicks (`target !== currentTarget`) bubble through harmlessly, so children
 * don't each need to `stopPropagation`. On mobile full-screen there is no
 * exposed backdrop, so dismissal is via the child's own close control — a
 * full-screen page has no "outside" to click, by design.
 *
 * The app is 100% inline-styled (CSS `@media` can't reach inline styles), so the
 * responsive branch is JS-driven via {@link useIsMobile}, like the rest of the app.
 */
export function ModalShell({
  onClose,
  ariaLabel,
  mobileFullScreen = true,
  closeOnEscape = true,
  lockBodyScroll = true,
  zIndex = 1000,
  children,
}: ModalShellProps) {
  const isMobile = useIsMobile();
  const fullScreen = isMobile && mobileFullScreen;

  useEffect(() => {
    if (!closeOnEscape) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeOnEscape, onClose]);

  useEffect(() => {
    if (!lockBodyScroll) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [lockBodyScroll]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={ariaLabel}
      onClick={(e) => {
        // Only a click on the backdrop itself dismisses; clicks on the child
        // (or its descendants) have a different target and are ignored.
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: "fixed",
        // Full-screen uses left/right:0 (not 100vw) to avoid a scrollbar-width
        // horizontal overflow, and 100dvh so mobile browser chrome can't clip it.
        ...(fullScreen
          ? { top: 0, left: 0, right: 0, height: "100dvh" }
          : { inset: 0 }),
        backgroundColor: "rgba(0,0,0,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex,
        padding: fullScreen ? 0 : "1rem",
        boxSizing: "border-box",
      }}
    >
      {children}
    </div>
  );
}
