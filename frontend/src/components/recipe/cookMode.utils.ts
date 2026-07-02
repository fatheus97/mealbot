// Pulls a duration out of a step string so cook mode can offer a one-tap timer.
// Sums an optional hours token and an optional minutes token so compound forms
// like "1 hour 30 minutes" give 90:00 (not 60:00). Requires an explicit time
// unit (so "bake at 200" won't match) and caps at 6h to reject bogus values.
export function parseDurationSeconds(text: string): number | null {
  const hours = text.match(/(\d+)\s*(?:hours?|hrs?)\b/i);
  const minutes = text.match(/(\d+)\s*(?:minutes?|mins?)\b/i);
  let secs = 0;
  if (hours) secs += parseInt(hours[1], 10) * 3600;
  if (minutes) secs += parseInt(minutes[1], 10) * 60;
  if (!Number.isFinite(secs) || secs <= 0) return null;
  return secs <= 6 * 3600 ? secs : null;
}

export interface StepSegment {
  text: string;
  // Non-null when the segment is a duration mention ("10 minutes") the cook can
  // tap to start a timer; the seconds it should run for.
  seconds: number | null;
}

// Splits a step into plain-text and duration segments so cook mode can render
// the durations inline and make them tappable timers. A duration token is
// "N hour(s) [M minute(s)]" or "N minute(s)".
const DURATION_TOKEN =
  /\b\d+\s*(?:hours?|hrs?)(?:\s+\d+\s*(?:minutes?|mins?))?|\b\d+\s*(?:minutes?|mins?)\b/gi;

export function tokenizeStepTimers(step: string): StepSegment[] {
  const segments: StepSegment[] = [];
  let last = 0;
  // Fresh regex per call — lastIndex is stateful on the shared literal.
  const re = new RegExp(DURATION_TOKEN.source, "gi");
  let m: RegExpExecArray | null;
  while ((m = re.exec(step)) !== null) {
    if (m.index > last) segments.push({ text: step.slice(last, m.index), seconds: null });
    segments.push({ text: m[0], seconds: parseDurationSeconds(m[0]) });
    last = m.index + m[0].length;
  }
  if (last < step.length) segments.push({ text: step.slice(last), seconds: null });
  if (segments.length === 0) segments.push({ text: step, seconds: null });
  return segments;
}
