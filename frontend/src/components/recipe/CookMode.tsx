import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { PlannedMeal } from "../../types";
import { mealTypeLabel } from "../../constants/mealTypes";
import { parseDurationSeconds } from "./cookMode.utils";

interface Props {
  meal: PlannedMeal;
  // localStorage key so the current step survives a mid-cook reload. Pass a
  // stable key per meal, e.g. `cookmode:${planId}:${day}:${meal}`.
  storageKey: string;
  onDone: () => void; // "Done": mark cooked (parent decides). Clears saved step.
  onClose: () => void; // "Close": leave without finishing; saved step stays.
  doneLabel?: string;
  donePending?: boolean;
}

function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
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

type Timer = { remaining: number; total: number; running: boolean; finished: boolean };

export function CookMode({
  meal,
  storageKey,
  onDone,
  onClose,
  doneLabel = "Done cooking",
  donePending = false,
}: Props) {
  const total = meal.steps.length;
  const [current, setCurrent] = useState<number>(() => Math.min(readStep(storageKey), Math.max(0, total - 1)));
  const [showIngredients, setShowIngredients] = useState(false);
  const [timer, setTimer] = useState<Timer | null>(null);
  const [manualMin, setManualMin] = useState("");

  const audioCtxRef = useRef<AudioContext | null>(null);
  const alarmIntervalRef = useRef<number | null>(null);

  const ensureAudio = (): AudioContext | null => {
    if (audioCtxRef.current) return audioCtxRef.current;
    const Ctx =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return null;
    try {
      audioCtxRef.current = new Ctx();
    } catch {
      return null;
    }
    return audioCtxRef.current;
  };

  const beep = () => {
    const ctx = audioCtxRef.current;
    if (!ctx) return;
    try {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880;
      osc.connect(gain);
      gain.connect(ctx.destination);
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.3, ctx.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.25);
      osc.start();
      osc.stop(ctx.currentTime + 0.26);
    } catch {
      // audio failed — the visual "Time's up" banner still shows
    }
  };

  const stopAlarm = () => {
    if (alarmIntervalRef.current != null) {
      clearInterval(alarmIntervalRef.current);
      alarmIntervalRef.current = null;
    }
  };

  const startAlarm = () => {
    const ctx = ensureAudio();
    if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
    beep();
    if (alarmIntervalRef.current == null) {
      alarmIntervalRef.current = window.setInterval(beep, 900);
    }
  };

  const notify = (body: string) => {
    try {
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        new Notification("Cooking timer", { body });
      }
    } catch {
      // notification blocked — non-fatal
    }
  };

  const requestNotify = () => {
    try {
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        Notification.requestPermission().catch(() => {});
      }
    } catch {
      // ignore
    }
  };

  // Countdown: one interval while running; re-armed on pause/resume.
  useEffect(() => {
    if (!timer?.running) return;
    const id = window.setInterval(() => {
      setTimer((t) => {
        if (!t || !t.running) return t;
        if (t.remaining <= 1) return { ...t, remaining: 0, running: false, finished: true };
        return { ...t, remaining: t.remaining - 1 };
      });
    }, 1000);
    return () => clearInterval(id);
  }, [timer?.running]);

  // Fire the alarm + notification exactly once when a timer finishes.
  useEffect(() => {
    if (timer?.finished) {
      startAlarm();
      notify(`Timer finished — ${meal.name}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timer?.finished]);

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
          // The browser auto-releases the lock when the tab hides; drop our
          // ref so the next visibilitychange re-acquires instead of the guard
          // above short-circuiting.
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

  // Teardown: stop any alarm and close the audio context on unmount.
  useEffect(() => {
    return () => {
      stopAlarm();
      audioCtxRef.current?.close().catch(() => {});
    };
  }, []);

  const goTo = (step: number) => {
    const clamped = Math.max(0, Math.min(total - 1, step));
    setCurrent(clamped);
    writeStep(storageKey, clamped);
  };

  const startTimer = (seconds: number) => {
    // Same lower + upper bound as auto-detected durations, so a fat-fingered
    // manual entry can't spawn a multi-day timer.
    if (!(seconds > 0) || seconds > 6 * 3600) return;
    requestNotify();
    ensureAudio(); // create inside the click gesture so playback is allowed later
    setTimer({ remaining: seconds, total: seconds, running: true, finished: false });
  };

  const dismissTimer = () => {
    stopAlarm();
    setTimer(null);
  };

  const handleDone = () => {
    // Storage is cleared by the parent AFTER the cook mutation succeeds, so a
    // failed cook keeps this overlay + its saved progress intact for a retry.
    stopAlarm();
    onDone();
  };

  const step = meal.steps[current] ?? "";
  const detected = parseDurationSeconds(step);
  const isLast = current >= total - 1;
  const manualSeconds = Math.round(Number(manualMin) * 60);

  const chipBtn: React.CSSProperties = {
    padding: "0.4rem 0.9rem",
    borderRadius: "999px",
    border: "1px solid #334155",
    background: "#1e293b",
    color: "#e2e8f0",
    cursor: "pointer",
    fontSize: "0.9rem",
  };

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
        flexDirection: "column",
        padding: "1rem",
        boxSizing: "border-box",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.05em", color: "#94a3b8" }}>
            {mealTypeLabel(meal.meal_type, meal.meal_type_label)}
          </div>
          <div style={{ fontSize: "1.15rem", fontWeight: 700 }}>{meal.name}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span aria-label={`Step ${current + 1} of ${total}`} style={{ fontSize: "0.9rem", color: "#cbd5e1" }}>
            Step {current + 1} of {total}
          </span>
          <button type="button" onClick={() => setShowIngredients((v) => !v)} style={chipBtn}>
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

      {/* Current step */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center", gap: "1.5rem", overflowY: "auto" }}>
        <p style={{ fontSize: "1.6rem", lineHeight: 1.4, maxWidth: "32rem", margin: 0 }}>{step}</p>

        {/* Timer */}
        {timer ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.5rem" }}>
            <div
              aria-label={`Timer ${formatClock(timer.remaining)} remaining`}
              style={{ fontSize: "2.5rem", fontWeight: 700, fontVariantNumeric: "tabular-nums", color: timer.finished ? "#f87171" : "#22c55e" }}
            >
              {formatClock(timer.remaining)}
            </div>
            {timer.finished ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.5rem" }}>
                <strong role="alert" style={{ color: "#f87171", fontSize: "1.1rem" }}>⏰ Time's up!</strong>
                <button type="button" onClick={dismissTimer} style={{ ...chipBtn, background: "#f87171", color: "#0b1220", borderColor: "#f87171" }}>
                  Dismiss
                </button>
              </div>
            ) : (
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button type="button" onClick={() => setTimer((t) => (t ? { ...t, running: !t.running } : t))} style={chipBtn}>
                  {timer.running ? "Pause" : "Resume"}
                </button>
                <button type="button" onClick={dismissTimer} style={chipBtn}>
                  Cancel
                </button>
              </div>
            )}
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.6rem" }}>
            {detected != null && (
              <button
                type="button"
                onClick={() => startTimer(detected)}
                style={{ ...chipBtn, background: "#16a34a", color: "#fff", borderColor: "#16a34a", fontWeight: 600 }}
              >
                ⏱ Start {formatClock(detected)} timer
              </button>
            )}
            <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
              <input
                type="number"
                min={1}
                value={manualMin}
                onChange={(e) => setManualMin(e.target.value)}
                placeholder="min"
                aria-label="Custom timer minutes"
                style={{ width: "4.5rem", padding: "0.35rem", borderRadius: "6px", border: "1px solid #334155", background: "#0f172a", color: "#e2e8f0" }}
              />
              <button
                type="button"
                onClick={() => startTimer(manualSeconds)}
                disabled={!(manualSeconds > 0) || manualSeconds > 6 * 3600}
                style={{ ...chipBtn, opacity: manualSeconds > 0 && manualSeconds <= 6 * 3600 ? 1 : 0.5 }}
              >
                Set timer
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Footer nav */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem", marginTop: "1rem" }}>
        <button
          type="button"
          onClick={() => goTo(current - 1)}
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
            onClick={() => goTo(current + 1)}
            style={{ padding: "0.6rem 1.6rem", borderRadius: "8px", border: "none", background: "#2563eb", color: "#fff", fontWeight: 700, fontSize: "1rem", cursor: "pointer" }}
          >
            Next ›
          </button>
        )}
      </div>

      {/* Ingredients slide-in */}
      {showIngredients && (
        <div
          style={{ position: "absolute", top: 0, right: 0, bottom: 0, width: "min(20rem, 85vw)", background: "#0f172a", borderLeft: "1px solid #1e293b", padding: "1rem", overflowY: "auto", boxShadow: "-8px 0 24px rgba(0,0,0,0.4)" }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
            <strong>Ingredients</strong>
            <button type="button" onClick={() => setShowIngredients(false)} aria-label="Hide ingredients" style={chipBtn}>✕</button>
          </div>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {meal.ingredients.map((ing, i) => (
              <li key={i} style={{ padding: "0.3rem 0", borderBottom: "1px solid #1e293b", fontSize: "0.95rem" }}>
                {ing.is_spice ? <em>{ing.name}</em> : <span>{ing.name} — {Math.round(ing.quantity_grams)}g</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>,
    document.body,
  );
}
