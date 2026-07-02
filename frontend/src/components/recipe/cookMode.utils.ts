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
