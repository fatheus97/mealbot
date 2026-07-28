import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  MAX_TIMER_SECONDS,
  deadlineIn,
  secondsUntil,
} from "../components/recipe/cookMode.utils";

// App-level cooking timers.
//
// These used to be a single `useState` inside CookMode, which made the timer a
// property of the MODAL rather than of the cook: closing the overlay to check
// the fridge destroyed a running countdown, and only one could exist at a time
// even though "pasta boiling while the sauce reduces" is the ordinary case.
// Hoisting the state here is what lets a timer outlive the surface that started
// it and lets several run at once; the floating bubble is just a view of it.
//
// Timers are DEADLINE-based (`endsAt`), never tick-counted — see the wall-clock
// note in cookMode.utils. One shared interval drives every timer rather than one
// interval each, so the cost does not scale with how many are running.

export interface CookTimer {
  id: string;
  /** What the timer is for — shown in the bubble once you've left cook mode. */
  label: string;
  /** Seconds it was started with; kept so the UI can show what was set. */
  total: number;
  /** Derived from `endsAt` while running; the frozen value while paused. */
  remaining: number;
  /** Epoch-ms deadline while running, null while paused or finished. */
  endsAt: number | null;
  running: boolean;
  finished: boolean;
  /**
   * Identifies the surface this timer was started from, so the bubble can be a
   * way BACK into cooking rather than just a readout. Deliberately a KEY and
   * not a callback: a captured callback is a point-in-time closure that keeps
   * looking live after its component unmounts (switching away from the Cook Now
   * tab) or after the meal stops being cookable (marked cooked while the timer
   * runs) — a button that renders as interactive and silently does nothing.
   * The handler is looked up in the live registry at click time instead, so it
   * degrades to plain text exactly when there is genuinely nowhere to go.
   */
  reopenKey?: string;
}

interface CookTimerApi {
  timers: CookTimer[];
  /** Ignores a non-positive or over-cap duration. */
  start: (seconds: number, label: string, reopenKey?: string) => void;
  /** Pause a running timer, or resume a paused one. No-op once finished. */
  toggle: (id: string) => void;
  dismiss: (id: string) => void;
  /**
   * Hide the floating bubble while a surface renders its own timer UI (cook
   * mode does). Returns the release function — call it on unmount. Reference
   * counted, so a StrictMode double-mount cannot leave the bubble stuck.
   */
  suppressBubble: () => () => void;
  bubbleVisible: boolean;
  /**
   * The live way back for `reopenKey`, or undefined when nothing can currently
   * show it. Resolved at call time — see `CookTimer.reopenKey`.
   */
  getReopen: (reopenKey: string | undefined) => (() => void) | undefined;
  /** Registers a surface as the way back for `key`; returns the unregister. */
  registerReopen: (key: string, run: () => void) => () => void;
}

const CookTimerContext = createContext<CookTimerApi | null>(null);

export function CookTimerProvider({ children }: { children: ReactNode }) {
  const [timers, setTimers] = useState<CookTimer[]>([]);
  const [suppressCount, setSuppressCount] = useState(0);

  const nextIdRef = useRef(0);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const alarmIntervalRef = useRef<number | null>(null);
  // Timers already announced, so a re-render cannot re-fire the notification.
  const notifiedRef = useRef<Set<string>>(new Set());

  const ensureAudio = useCallback((): AudioContext | null => {
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
  }, []);

  const beep = useCallback(() => {
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
      // audio failed — the visual "Time's up" state still shows
    }
  }, []);

  const stopAlarm = useCallback(() => {
    if (alarmIntervalRef.current != null) {
      clearInterval(alarmIntervalRef.current);
      alarmIntervalRef.current = null;
    }
  }, []);

  const startAlarm = useCallback(() => {
    const ctx = ensureAudio();
    if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
    beep();
    if (alarmIntervalRef.current == null) {
      alarmIntervalRef.current = window.setInterval(beep, 900);
    }
  }, [beep, ensureAudio]);

  const notify = useCallback((body: string) => {
    try {
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        new Notification("Cooking timer", { body });
      }
    } catch {
      // notification blocked — non-fatal
    }
  }, []);

  const start = useCallback(
    (seconds: number, label: string, reopenKey?: string) => {
      // Guard here rather than at each call site: this is the only way a timer
      // is ever created, so the cap cannot be bypassed by a new surface.
      if (!(seconds > 0) || seconds > MAX_TIMER_SECONDS) return;
      // Both must happen inside the click gesture that led here: permission
      // prompts and AudioContext creation are gesture-gated.
      try {
        if (typeof Notification !== "undefined" && Notification.permission === "default") {
          Notification.requestPermission().catch(() => {});
        }
      } catch {
        // ignore
      }
      ensureAudio();
      const id = `timer-${nextIdRef.current++}`;
      setTimers((prev) => [
        ...prev,
        {
          id,
          label,
          total: seconds,
          remaining: seconds,
          endsAt: deadlineIn(seconds),
          running: true,
          finished: false,
          reopenKey,
        },
      ]);
    },
    [ensureAudio],
  );

  const toggle = useCallback((id: string) => {
    setTimers((prev) =>
      prev.map((t) => {
        if (t.id !== id || t.finished) return t;
        if (t.running) {
          const left = t.endsAt != null ? secondsUntil(t.endsAt) : t.remaining;
          // The deadline can already have passed in the up-to-1s gap before the
          // next tick would have caught it. Finish it rather than freezing a
          // 0:00 timer that is neither running nor finished — that zombie never
          // rings and never shows "Time's up".
          if (left <= 0) {
            return { ...t, remaining: 0, endsAt: null, running: false, finished: true };
          }
          // Freeze the seconds left; drop the deadline so nothing counts down.
          return { ...t, remaining: left, endsAt: null, running: false };
        }
        // Project a FRESH deadline so paused time is not charged to the timer.
        return { ...t, endsAt: deadlineIn(t.remaining), running: true };
      }),
    );
  }, []);

  const dismiss = useCallback((id: string) => {
    notifiedRef.current.delete(id);
    setTimers((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Live reopen registry, held in STATE rather than a ref: a bubble must stop
  // looking clickable the moment its surface unmounts, which means consumers
  // have to re-render when the set of targets changes.
  const [reopeners, setReopeners] = useState<ReadonlyMap<string, () => void>>(new Map());

  const registerReopen = useCallback((key: string, run: () => void) => {
    setReopeners((prev) => new Map(prev).set(key, run));
    return () => {
      setReopeners((prev) => {
        // Only clear if we're still the owner — a remount can register the same
        // key before the old instance's cleanup runs.
        if (prev.get(key) !== run) return prev;
        const next = new Map(prev);
        next.delete(key);
        return next;
      });
    };
  }, []);

  const getReopen = useCallback(
    (key: string | undefined) => (key ? reopeners.get(key) : undefined),
    [reopeners],
  );

  const suppressBubble = useCallback(() => {
    setSuppressCount((c) => c + 1);
    return () => setSuppressCount((c) => Math.max(0, c - 1));
  }, []);

  // One interval for every timer. It only triggers a re-render — each tick
  // recomputes from the wall clock, so a throttled or fully suspended interval
  // costs display smoothness, never accuracy. The visibilitychange sync corrects
  // the moment the screen comes back instead of waiting for the next tick.
  const anyRunning = timers.some((t) => t.running);
  useEffect(() => {
    if (!anyRunning) return;
    const sync = () => {
      setTimers((prev) => {
        let changed = false;
        const next = prev.map((t) => {
          if (!t.running || t.endsAt == null) return t;
          const left = secondsUntil(t.endsAt);
          if (left <= 0) {
            changed = true;
            return { ...t, remaining: 0, endsAt: null, running: false, finished: true };
          }
          if (left === t.remaining) return t;
          changed = true;
          return { ...t, remaining: left };
        });
        // Returning `prev` unchanged keeps React from re-rendering every second
        // when nothing actually moved (e.g. all timers paused mid-tick).
        return changed ? next : prev;
      });
    };
    sync();
    const id = window.setInterval(sync, 1000);
    const onVis = () => {
      if (document.visibilityState === "visible") sync();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [anyRunning]);

  // The alarm is a property of the SET of timers, not of any one of them: it
  // rings while at least one finished timer is unacknowledged and stops when
  // the last is dismissed.
  const anyFinished = timers.some((t) => t.finished);
  useEffect(() => {
    if (anyFinished) startAlarm();
    else stopAlarm();
  }, [anyFinished, startAlarm, stopAlarm]);

  // Announce each newly-finished timer exactly once.
  useEffect(() => {
    for (const t of timers) {
      if (t.finished && !notifiedRef.current.has(t.id)) {
        notifiedRef.current.add(t.id);
        notify(`Timer finished — ${t.label}`);
      }
    }
  }, [timers, notify]);

  // Teardown: silence the alarm and release the audio context.
  useEffect(() => {
    return () => {
      if (alarmIntervalRef.current != null) clearInterval(alarmIntervalRef.current);
      alarmIntervalRef.current = null;
      audioCtxRef.current?.close().catch(() => {});
      audioCtxRef.current = null;
    };
  }, []);

  const value = useMemo<CookTimerApi>(
    () => ({
      timers,
      start,
      toggle,
      dismiss,
      suppressBubble,
      bubbleVisible: suppressCount === 0 && timers.length > 0,
      getReopen,
      registerReopen,
    }),
    [timers, start, toggle, dismiss, suppressBubble, suppressCount, getReopen, registerReopen],
  );

  return <CookTimerContext.Provider value={value}>{children}</CookTimerContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCookTimers(): CookTimerApi {
  const ctx = useContext(CookTimerContext);
  if (!ctx) {
    // Fail loudly rather than silently dropping timers on the floor — a surface
    // rendered outside the provider would otherwise look fine until you tapped.
    throw new Error("useCookTimers must be used inside a CookTimerProvider");
  }
  return ctx;
}

/**
 * Registers this component as the way back into `key` while it is mounted AND
 * `enabled`. Pass the same guard the surface uses for its own "start cooking"
 * affordance, so the bubble can't route into a meal that is already cooked or
 * a plan that is finished.
 *
 * `run` is read through a ref, so callers may pass an inline arrow without the
 * registration churning (and looping) on every render.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useReopenTarget(key: string, run: () => void, enabled = true): void {
  // Tolerates a missing provider, unlike useCookTimers. Offering a way back is
  // passive: with no provider there are no timers and so nothing that could
  // route here, and a card rendered in isolation shouldn't have to know about
  // cooking timers at all.
  const ctx = useContext(CookTimerContext);
  const registerReopen = ctx?.registerReopen;
  const runRef = useRef(run);
  useEffect(() => {
    runRef.current = run;
  });
  useEffect(() => {
    if (!enabled || !registerReopen) return;
    return registerReopen(key, () => runRef.current());
  }, [key, enabled, registerReopen]);
}

/** Hides the floating bubble for as long as the calling component is mounted. */
// eslint-disable-next-line react-refresh/only-export-components
export function useSuppressTimerBubble(): void {
  const { suppressBubble } = useCookTimers();
  useEffect(() => suppressBubble(), [suppressBubble]);
}
