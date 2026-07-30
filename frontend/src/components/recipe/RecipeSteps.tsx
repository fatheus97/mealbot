import { useMemo } from "react";
import { tokenizeStepTimers } from "./cookMode.utils";
import { useOptionalCookTimerActions } from "../../contexts/CookTimerContext";

interface Props {
  steps: string[];
  // Enables tappable durations, and names the timer in the floating bubble
  // (normally the meal name). Omit to render plain text — the previous
  // behaviour, and the right one where a timer would make no sense.
  timerLabel?: string;
  // Cook-mode storage key, so the bubble can offer a way back into cooking.
  // Omit where there is no cook mode for this recipe (the cookbook): the timer
  // still runs, the bubble just isn't a link.
  reopenKey?: string;
}

// A duration inside a plain step list, tappable to start a timer.
//
// Deliberately NOT cook mode's green chip. That chip lives on cook mode's own
// pinned dark surface; this list renders on several different backgrounds — the
// planner's light card, the cookbook's parchment, the adaptive page — and
// `#4ade80` is about 1.7:1 on white. Inheriting the surrounding text colour is
// legible on every one of them by construction, which is the same reason
// DietarySelector's unselected chips use `color: inherit`. The dashed underline
// carries the affordance instead of colour.
const inlineTimer: React.CSSProperties = {
  background: "none",
  border: "none",
  borderBottom: "1px dashed currentColor",
  padding: 0,
  font: "inherit",
  color: "inherit",
  cursor: "pointer",
};

export function RecipeSteps({ steps, timerLabel, reopenKey }: Props) {
  // Actions-only: this must not re-render once a second while a timer counts
  // down, or every step in every open recipe re-tokenizes on every tick.
  const actions = useOptionalCookTimerActions();
  const enabled = actions != null && timerLabel != null;

  // Tokenizing compiles a large multi-language alternation, so don't redo it for
  // every step on unrelated re-renders (a plan card re-renders on any plan
  // state change).
  const tokenized = useMemo(
    () => (enabled ? steps.map((s) => tokenizeStepTimers(s)) : null),
    [steps, enabled],
  );

  return (
    <ol style={{ marginTop: "0.25rem", paddingLeft: "1.25rem" }}>
      {steps.map((step, i) => (
        <li key={i} style={{ marginBottom: "0.4rem", lineHeight: 1.45 }}>
          {tokenized
            ? tokenized[i].map((seg, j) => {
                const secs = seg.seconds;
                return secs != null ? (
                  <button
                    key={j}
                    type="button"
                    style={inlineTimer}
                    title={`Start a ${seg.text} timer`}
                    onClick={() => actions?.start(secs, timerLabel!, reopenKey)}
                  >
                    {seg.text}
                  </button>
                ) : (
                  <span key={j}>{seg.text}</span>
                );
              })
            : step}
        </li>
      ))}
    </ol>
  );
}
