import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { PlannedMeal } from "../../types";
import { mealTypeLabel } from "../../constants/mealTypes";
import { formatClock, tokenizeStepTimers } from "./cookMode.utils";
import { useCookTimers, useSuppressTimerBubble } from "../../contexts/CookTimerContext";
import { useIsMobile } from "../../hooks/useIsMobile";

interface Props {
  meal: PlannedMeal;
  // localStorage key so the current step survives a mid-cook reload. Pass a
  // stable key per meal, e.g. `cookmode:${planId}:${day}:${meal}`.
  storageKey: string;
  onDone: () => void; // "Done": mark cooked (parent decides + clears storage on success).
  onClose: () => void; // "Close": leave without finishing; saved step stays.
  doneLabel?: string;
  donePending?: boolean;
  doneError?: string | null; // shown inside the overlay when a cook attempt fails
}

function readStep(key: string): number {
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const p = JSON.parse(raw) as { step?: unknown };
      if (typeof p.step === "number" && p.step >= 0) return p.step;
    }
  } catch {
    // corrupt/unavailable — start at step 0
  }
  return 0;
}

function writeStep(key: string, step: number): void {
  try {
    localStorage.setItem(key, JSON.stringify({ step }));
  } catch {
    // storage unavailable — nav still works in memory this session
  }
}

interface WakeSentinel {
  release: () => Promise<void>;
  addEventListener?: (type: "release", listener: () => void) => void;
}

interface WakeLockLike {
  wakeLock?: { request(type: "screen"): Promise<WakeSentinel> };
}

const chipBtn: React.CSSProperties = {
  padding: "0.4rem 0.9rem",
  borderRadius: "999px",
  border: "1px solid #334155",
  background: "#1e293b",
  color: "#e2e8f0",
  cursor: "pointer",
  fontSize: "0.9rem",
};

// A duration mention rendered inline in the step, tappable to start its timer.
const inlineTimer: React.CSSProperties = {
  background: "rgba(34,197,94,0.15)",
  color: "#4ade80",
  border: "1px solid rgba(34,197,94,0.5)",
  borderRadius: "6px",
  padding: "0 0.35rem",
  margin: "0 0.15rem",
  cursor: "pointer",
  fontSize: "inherit",
  fontFamily: "inherit",
  fontWeight: 700,
};

export function CookMode({
  meal,
  storageKey,
  onDone,
  onClose,
  doneLabel = "Done cooking",
  donePending = false,
  doneError = null,
}: Props) {
  const isMobile = useIsMobile();
  const total = meal.steps.length;
  const [current, setCurrent] = useState<number>(() => Math.min(readStep(storageKey), Math.max(0, total - 1)));
  const [showIngredients, setShowIngredients] = useState(false);
  const [manualMin, setManualMin] = useState("");

  // Timers live at app level, so one started here survives closing this overlay
  // to check the fridge — and several can run at once. While cook mode is open
  // the floating bubble stays hidden, since the bar below shows the same list.
  const { timers, start, toggle, dismiss } = useCookTimers();
  useSuppressTimerBubble();

  // Keyboard: ← / → move between steps (ignored while typing in a field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const delta = e.key === "ArrowRight" ? 1 : -1;
      setCurrent((c) => {
        const next = Math.max(0, Math.min(total - 1, c + delta));
        writeStep(storageKey, next);
        return next;
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [total, storageKey]);

  // Keep the screen awake while cooking; re-acquire when the tab returns to
  // foreground (the lock is auto-released on hide).
  useEffect(() => {
    let sentinel: WakeSentinel | null = null;
    let pending = false;
    let cancelled = false;
    const request = () => {
      // Skip if a request is already in flight or a lock is held — otherwise a
      // rapid hide/show can spawn a second sentinel that leaks the first.
      if (pending || sentinel || cancelled) return;
      const nav = navigator as unknown as WakeLockLike;
      if (!nav.wakeLock?.request) return;
      pending = true;
      nav.wakeLock
        .request("screen")
        .then((s) => {
          pending = false;
          if (cancelled) {
            s.release().catch(() => {});
            return;
          }
          sentinel = s;
          // The browser auto-releases the lock when the tab hides; drop our ref
          // so the next visibilitychange re-acquires instead of short-circuiting.
          s.addEventListener?.("release", () => {
            if (sentinel === s) sentinel = null;
          });
        })
        .catch(() => {
          pending = false;
        });
    };
    request();
    const onVis = () => {
      if (document.visibilityState === "visible") request();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVis);
      sentinel?.release().catch(() => {});
    };
  }, []);

  const move = (delta: number) => {
    setCurrent((c) => {
      const next = Math.max(0, Math.min(total - 1, c + delta));
      writeStep(storageKey, next);
      return next;
    });
  };

  // Touch swipe to page between steps (mobile), alongside the Back/Next buttons
  // and the ← → keys. Swipe left → next step, swipe right → previous step.
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const onStepTouchStart = (e: React.TouchEvent<HTMLDivElement>) => {
    const t = e.changedTouches[0];
    touchStartRef.current = { x: t.clientX, y: t.clientY };
  };
  const onStepTouchEnd = (e: React.TouchEvent<HTMLDivElement>) => {
    const start = touchStartRef.current;
    touchStartRef.current = null;
    if (!start) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - start.x;
    const dy = t.clientY - start.y;
    // Only a decisive HORIZONTAL swipe navigates — ignore taps (e.g. timer
    // chips) and vertical scrolls of a long step.
    if (Math.abs(dx) < 50 || Math.abs(dx) <= Math.abs(dy)) return;
    move(dx < 0 ? 1 : -1);
  };
  // If the OS cancels the gesture mid-swipe (incoming call, notification), drop
  // the start point so a later touchend can't act on a stale position.
  const onStepTouchCancel = () => {
    touchStartRef.current = null;
  };

  // Tapping a duration ADDS a timer rather than replacing the running one —
  // "pasta on, now start the sauce" is the ordinary case. The bound and the
  // alarm both live in the store, which is the only place a timer is created.
  const startTimer = (seconds: number) => start(seconds, meal.name);

  const handleDone = () => {
    // Storage is cleared by the parent AFTER the cook mutation succeeds, so a
    // failed cook keeps this overlay + its saved progress intact for a retry.
    onDone();
  };

  const step = meal.steps[current] ?? "";
  // Tokenizing compiles a large multi-language alternation, and this component
  // re-renders once a second while a timer counts down. The step text only
  // changes on navigation, so memoize on it rather than redoing the work 60x
  // a minute for an identical result.
  const stepSegments = useMemo(() => tokenizeStepTimers(step), [step]);
  const isLast = current >= total - 1;
  const manualSeconds = Math.round(Number(manualMin) * 60);
  const manualOk = manualSeconds > 0 && manualSeconds <= 6 * 3600;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Cooking ${meal.name}`}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "#0b1220",
        color: "#f8fafc",
        display: "flex",
        // Tap-through wizard: display text isn't selectable, so tapping a step
        // or title doesn't show an I-beam cursor / selection caret (which read
        // as "you can type here"). Buttons/input set their own cursor; the
        // timer input opts back into selection below.
        userSelect: "none",
        WebkitUserSelect: "none",
        cursor: "default",
      }}
    >
      {/* Main column — shrinks when the ingredients panel opens (no overlap). */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", padding: "1rem", boxSizing: "border-box" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.05em", color: "#94a3b8" }}>
              {mealTypeLabel(meal.meal_type, meal.meal_type_label)}
            </div>
            <div style={{ fontSize: "1.15rem", fontWeight: 700 }}>{meal.name}</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span aria-label={`Step ${current + 1} of ${total}`} style={{ fontSize: "0.9rem", color: "#cbd5e1" }}>
              Step {current + 1} of {total}
            </span>
            <button
              type="button"
              onClick={() => setShowIngredients((v) => !v)}
              aria-pressed={showIngredients}
              style={{ ...chipBtn, borderColor: showIngredients ? "#22c55e" : "#334155" }}
            >
              Ingredients
            </button>
            <button type="button" onClick={onClose} aria-label="Close cooking mode" style={{ ...chipBtn, borderColor: "#475569" }}>
              ✕
            </button>
          </div>
        </div>

        {/* Progress bar */}
        <div style={{ height: "4px", background: "#1e293b", borderRadius: "2px", margin: "0.75rem 0 1rem" }}>
          <div style={{ height: "100%", width: `${Math.min(100, ((current + 1) / Math.max(1, total)) * 100)}%`, background: "#22c55e", borderRadius: "2px", transition: "width 0.2s" }} />
        </div>

        {/* Current step (durations are tappable timers). Swipe left/right here
            pages between steps on touch devices. */}
        <div
          onTouchStart={onStepTouchStart}
          onTouchEnd={onStepTouchEnd}
          onTouchCancel={onStepTouchCancel}
          style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center", overflowY: "auto" }}
        >
          <p style={{ fontSize: "1.6rem", lineHeight: 1.5, maxWidth: "40rem", margin: 0 }}>
            {stepSegments.map((seg, i) => {
              const secs = seg.seconds;
              return secs != null ? (
                <button key={i} type="button" onClick={() => startTimer(secs)} title="Start a timer" style={inlineTimer}>
                  {seg.text}
                </button>
              ) : (
                <span key={i}>{seg.text}</span>
              );
            })}
          </p>
        </div>

        {/* Timer bar (bottom). Every running timer is listed — a second one is
            added, never swapped in, so "pasta on, now the sauce" works. The
            manual row stays available underneath instead of being replaced by
            the first timer, since that was the only way to add another. */}
        <div style={{ minHeight: "3rem", display: "flex", flexDirection: "column", alignItems: "center", gap: "0.5rem", margin: "0.5rem 0" }}>
          {/* Many timers scroll rather than squeezing the step text above. */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.4rem", maxHeight: "30vh", overflowY: "auto", width: "100%" }}>
            {timers.map((t) => (
              <div key={t.id} style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "0.6rem", flexWrap: "wrap" }}>
                <span
                  aria-label={`Timer ${formatClock(t.remaining)} remaining`}
                  style={{ fontSize: timers.length > 1 ? "1.3rem" : "1.9rem", fontWeight: 700, fontVariantNumeric: "tabular-nums", color: t.finished ? "#f87171" : "#22c55e" }}
                >
                  {formatClock(t.remaining)}
                </span>
                {/* Name the timer whenever it isn't this meal's. Timers are
                    app-level and outlive the overlay, so cooking A, closing with
                    a timer running, then opening B would otherwise show A's
                    countdown here unlabelled next to a bare "Cancel". */}
                {t.label !== meal.name && (
                  <span style={{ fontSize: "0.85rem", color: "#94a3b8", maxWidth: "12rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {t.label}
                  </span>
                )}
                {t.finished ? (
                  <>
                    <strong style={{ color: "#f87171" }}>⏰ Time's up!</strong>
                    <button type="button" onClick={() => dismiss(t.id)} style={{ ...chipBtn, background: "#f87171", color: "#0b1220", borderColor: "#f87171" }}>
                      Dismiss
                    </button>
                  </>
                ) : (
                  <>
                    <button type="button" onClick={() => toggle(t.id)} style={chipBtn}>
                      {t.running ? "Pause" : "Resume"}
                    </button>
                    <button type="button" onClick={() => dismiss(t.id)} style={chipBtn}>
                      Cancel
                    </button>
                  </>
                )}
              </div>
            ))}
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "0.6rem", flexWrap: "wrap" }}>
            <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>
              {timers.length > 0 ? "Add another:" : "Tap a time in the step, or set one:"}
            </span>
            <input
              type="number"
              min={1}
              value={manualMin}
              onChange={(e) => setManualMin(e.target.value)}
              placeholder="min"
              aria-label="Custom timer minutes"
              style={{ width: "4.5rem", padding: "0.35rem", borderRadius: "6px", border: "1px solid #334155", background: "#0f172a", color: "#e2e8f0", userSelect: "text", WebkitUserSelect: "text" }}
            />
            <button
              type="button"
              onClick={() => startTimer(manualSeconds)}
              disabled={!manualOk}
              style={{ ...chipBtn, opacity: manualOk ? 1 : 0.5 }}
            >
              Set timer
            </button>
          </div>
        </div>

        {doneError && (
          <div role="alert" style={{ color: "#f87171", textAlign: "center", fontSize: "0.9rem", marginBottom: "0.4rem" }}>
            {doneError}
          </div>
        )}

        {/* Footer nav */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem" }}>
          <button
            type="button"
            onClick={() => move(-1)}
            disabled={current === 0}
            style={{ ...chipBtn, opacity: current === 0 ? 0.4 : 1 }}
          >
            ‹ Back
          </button>
          {isLast ? (
            <button
              type="button"
              onClick={handleDone}
              disabled={donePending}
              style={{ padding: "0.6rem 1.6rem", borderRadius: "8px", border: "none", background: "#16a34a", color: "#fff", fontWeight: 700, fontSize: "1rem", cursor: donePending ? "not-allowed" : "pointer" }}
            >
              {donePending ? "Saving…" : doneLabel}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => move(1)}
              style={{ padding: "0.6rem 1.6rem", borderRadius: "8px", border: "none", background: "#2563eb", color: "#fff", fontWeight: 700, fontSize: "1rem", cursor: "pointer" }}
            >
              Next ›
            </button>
          )}
        </div>
      </div>

      {/* Ingredients panel. Desktop: a flex sibling that narrows the main column.
          Mobile: a full-screen overlay (40vw would leave the step text too
          cramped on a phone), toggled on/off over the steps. */}
      {showIngredients && (
        <aside
          style={
            isMobile
              ? { position: "absolute", inset: 0, zIndex: 10, background: "#0f172a", padding: "1rem", overflowY: "auto", boxSizing: "border-box" }
              : { width: "min(20rem, 40vw)", flexShrink: 0, background: "#0f172a", borderLeft: "1px solid #1e293b", padding: "1rem", overflowY: "auto", boxSizing: "border-box" }
          }
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
            <strong>Ingredients</strong>
            <button type="button" onClick={() => setShowIngredients(false)} aria-label="Hide ingredients" style={chipBtn}>
              ✕
            </button>
          </div>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {meal.ingredients.map((ing, i) => (
              <li key={i} style={{ padding: "0.3rem 0", borderBottom: "1px solid #1e293b", fontSize: "0.95rem" }}>
                {ing.is_spice ? <em>{ing.name}</em> : <span>{ing.name} — {Math.round(ing.quantity_grams)}g</span>}
              </li>
            ))}
          </ul>
        </aside>
      )}
    </div>,
    document.body,
  );
}
