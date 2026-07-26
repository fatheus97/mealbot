// Duration parsing for cook mode's tap-a-time-to-start-a-timer affordance.
//
// Recipe steps are written by the LLM in the user's `language` preference (33
// entries in the backend whitelist), so an English-only matcher makes the whole
// feature INVISIBLE to every non-English user. That is exactly what shipped:
// "5 minut" (Czech) never matched /minutes?|mins?/\b because `\b` cannot sit
// between "min" and "ut" — the boundary requires a non-word character there.
//
// Two consequences shape this module:
//
//  1. Boundaries must be Unicode-aware. JS `\b` is defined over [A-Za-z0-9_],
//     so it is simply wrong at the edge of "minut", "часов" or "分钟". We use a
//     `(?![\p{L}\p{N}])` lookahead instead. Deliberately a lookAHEAD, never a
//     lookbehind: lookbehind only reached Safari in 16.4, and an unsupported
//     construct here throws a SyntaxError at module-import time, which would
//     take down cook mode entirely on an older phone. A leading `\b` is fine —
//     the token starts with an ASCII digit, which is precisely where `\b` works.
//
//  2. Matching is language-AGNOSTIC — every language's vocabulary is live at
//     once rather than selected from the user's current preference. Plans are
//     frozen into `response_json` at generation time while `language` stays
//     mutable, so keying the parser on the live preference would silently kill
//     timers on every plan generated before the user last changed it.
//
// The failure modes are asymmetric, which sets the bar for adding a word: a
// MISSING word degrades to the status quo (no button; the manual-minutes box
// still works), while a WRONG word starts a bogus timer on something that was
// never a duration. So only well-established time units go in the tables, and
// single ambiguous letters ("s" for seconds, "t" for Norwegian timer) stay out.
// Every entry must be letters and combining marks only (Devanagari and Thai
// entries are \p{M} sequences over their base letters) — enforced by a test,
// and relied on below to skip regex-escaping the alternation.

// --- Time-unit vocabulary -------------------------------------------------
// Grouped by language so the tables stay reviewable. Inflected forms are listed
// explicitly rather than stemmed: Slavic cases ("hodina/hodiny/hodin/hodinu")
// do not share a safe prefix with anything a stem match wouldn't over-reach on.

const HOUR_WORDS: readonly string[] = [
  "hour", "hours", "hr", "hrs", "h",                       // English
  "hora", "horas",                                          // Spanish / Portuguese
  "heure", "heures",                                        // French
  "stunde", "stunden", "std",                               // German
  "ora", "ore",                                             // Italian / Romanian
  "uur", "uren",                                            // Dutch
  "timme", "timmar", "tim",                                 // Swedish
  "time", "timer",                                          // Norwegian / Danish
  "tunti", "tuntia",                                        // Finnish
  "godzina", "godziny", "godzin", "godz",                   // Polish
  "hodina", "hodiny", "hodin", "hodinu", "hod",             // Czech
  "hodín", "hodinách",                                      // Slovak
  "óra", "órát", "óráig",                                   // Hungarian
  "oră",                                                    // Romanian
  "sat", "sata", "sati",                                    // Croatian / Serbian
  "ura", "ure", "uri", "ur",                                // Slovenian
  "ώρα", "ώρες",                                            // Greek
  "saat",                                                   // Turkish
  "час", "часа", "часов", "часове",                         // Russian / Bulgarian
  "година", "години", "годин",                              // Ukrainian
  "時間",                                                    // Japanese
  "시간",                                                    // Korean
  "小时", "小時",                                            // Chinese (simp. / trad.)
  "ساعة", "ساعات",                                          // Arabic
  "שעה", "שעות",                                            // Hebrew
  "घंटा", "घंटे",                                              // Hindi
  "ชั่วโมง",                                                  // Thai
  "giờ",                                                    // Vietnamese
  "jam",                                                    // Indonesian
];

const MINUTE_WORDS: readonly string[] = [
  "minute", "minutes", "min", "mins",                       // English / French
  "minuto", "minutos", "minuti",                            // Spanish / Portuguese / Italian
  "minuten",                                                // German / Dutch
  "minuut",                                                 // Dutch
  "minut", "minuta", "minuty", "minutu", "minuter",         // Czech / Polish / Nordic / BCS
  "minutt", "minutter",                                     // Norwegian / Danish
  "minúta", "minúty", "minút",                              // Slovak
  "minuutti", "minuuttia",                                  // Finnish
  "perc", "percig", "percet",                               // Hungarian
  "mn", "dk", "dakika",                                     // French abbr. / Turkish
  "λεπτό", "λεπτά",                                         // Greek
  "минута", "минуты", "минут", "минути",                    // Russian / Bulgarian
  "хвилина", "хвилини", "хвилин",                           // Ukrainian
  "分鐘", "分钟", "分間", "分",                                // Chinese / Japanese
  "분",                                                      // Korean
  "دقيقة", "دقائق",                                          // Arabic
  "דקה", "דקות",                                            // Hebrew
  "मिनट",                                                    // Hindi
  "นาที",                                                    // Thai
  "phút",                                                   // Vietnamese
  "menit",                                                  // Indonesian
];

const SECOND_WORDS: readonly string[] = [
  "second", "seconds", "sec", "secs",                       // English
  "segundo", "segundos",                                    // Spanish / Portuguese
  "seconde", "secondes", "seconden",                        // French / Dutch
  "sekunde", "sekunden",                                    // German
  "secondo", "secondi",                                     // Italian
  "sekund", "sekunda", "sekundy", "sekunder", "sekundi",    // Nordic / Slavic
  "sekúnd",                                                 // Slovak
  "sekunti", "sekuntia",                                    // Finnish
  "vteřin", "vteřiny",                                      // Czech (alt.)
  "másodperc",                                              // Hungarian
  "secundă", "secunde",                                     // Romanian
  "saniye", "sn",                                           // Turkish
  "δευτερόλεπτο", "δευτερόλεπτα",                           // Greek
  "секунда", "секунды", "секунд", "секунди",                // Russian / Bulgarian / Ukrainian
  "秒間", "秒",                                              // Japanese / Chinese
  "초",                                                      // Korean
  "ثانية", "ثوان",                                           // Arabic
  "שניה", "שניות",                                          // Hebrew
  "सेकंड",                                                    // Hindi
  "วินาที",                                                   // Thai
  "giây",                                                   // Vietnamese
  "detik",                                                  // Indonesian
];

// Exported for the table-hygiene test (every entry letters-only, no duplicates
// across units — a word in two tables would be summed twice by the parser).
export const TIME_WORD_TABLES = {
  hour: HOUR_WORDS,
  minute: MINUTE_WORDS,
  second: SECOND_WORDS,
} as const;

// --- Pattern construction -------------------------------------------------

// Longest-first so "分钟" wins over "分" and "minutes" over "min"; a regex
// alternation is first-match, not longest-match, so ordering is load-bearing.
function alternation(words: readonly string[]): string {
  return [...words].sort((a, b) => b.length - a.length).join("|");
}

// Integer or decimal, accepting the comma separator most of Europe writes
// ("1,5 hodiny"). `\s*` covers the NBSP that Czech/French typography puts
// between a number and its unit — JS `\s` includes U+00A0.
const NUMBER = String.raw`\d+(?:[.,]\d+)?`;
const NOT_LETTER = String.raw`(?![\p{L}\p{N}])`;

// Scripts that do not delimit words with spaces — CJK, kana, Hangul, Thai.
// These cannot carry the trailing guard: the character after the unit in
// "5分間煮る" or "5분간" is *always* a letter, so guarding would reject every
// CJK/Thai duration outright. They are safe unguarded — an ideographic time
// unit immediately after a digit is unambiguous. Space-delimited scripts keep
// the guard, which is what stops "5 minutová pauza" arming a 5-minute timer.
const UNSPACED_SCRIPT =
  /[぀-ヿ㐀-䶿一-鿿가-힯฀-๿]/;

function unitPattern(words: readonly string[]): string {
  const spaced = words.filter((w) => !UNSPACED_SCRIPT.test(w));
  const unspaced = words.filter((w) => UNSPACED_SCRIPT.test(w));
  const branches: string[] = [];
  if (spaced.length > 0) branches.push(`(?:${alternation(spaced)})${NOT_LETTER}`);
  if (unspaced.length > 0) branches.push(`(?:${alternation(unspaced)})`);
  return String.raw`\b(${NUMBER})\s*(?:${branches.join("|")})`;
}

const HOUR_PART = unitPattern(HOUR_WORDS);
const MINUTE_PART = unitPattern(MINUTE_WORDS);
const SECOND_PART = unitPattern(SECOND_WORDS);

// A whole duration mention. Compound forms bind greedily so "1 hodinu 30 minut"
// is ONE tappable token worth 90 minutes rather than two competing ones. `\s*`
// (not `\s+`) between the parts because CJK writes them unspaced ("1時間30分").
const DURATION_TOKEN =
  `(?:${HOUR_PART})(?:\\s*(?:${MINUTE_PART}))?` +
  `|(?:${MINUTE_PART})(?:\\s*(?:${SECOND_PART}))?` +
  `|(?:${SECOND_PART})`;

const HOUR_RE = new RegExp(HOUR_PART, "iu");
const MINUTE_RE = new RegExp(MINUTE_PART, "iu");
const SECOND_RE = new RegExp(SECOND_PART, "iu");

// Longest plausible hands-on cooking timer. Anything above is a misparse (a
// marinade "for 24 hours", an oven temperature that happened to collide) and a
// button that silently arms a multi-hour countdown is worse than no button.
const MAX_TIMER_SECONDS = 6 * 3600;

function firstValue(re: RegExp, text: string): number {
  const m = re.exec(text);
  if (!m) return 0;
  // Normalize the European decimal comma before parsing.
  const n = parseFloat(m[1].replace(",", "."));
  return Number.isFinite(n) ? n : 0;
}

// Pulls a duration out of a step string so cook mode can offer a one-tap timer.
// Sums the hour, minute and second components so compound forms like
// "1 hour 30 minutes" give 90:00 (not 60:00). Requires an explicit time unit
// (so "bake at 200" won't match) and caps at 6h to reject bogus values.
export function parseDurationSeconds(text: string): number | null {
  const secs =
    firstValue(HOUR_RE, text) * 3600 +
    firstValue(MINUTE_RE, text) * 60 +
    firstValue(SECOND_RE, text);
  if (!Number.isFinite(secs) || secs <= 0) return null;
  // Round: "1,5 minuty" is 90s, but a fractional second would desync the
  // 1-second countdown from the label it started from.
  return secs <= MAX_TIMER_SECONDS ? Math.round(secs) : null;
}

export interface StepSegment {
  text: string;
  // Non-null when the segment is a duration mention ("10 minutes") the cook can
  // tap to start a timer; the seconds it should run for.
  seconds: number | null;
}

// Splits a step into plain-text and duration segments so cook mode can render
// the durations inline and make them tappable timers.
export function tokenizeStepTimers(step: string): StepSegment[] {
  const segments: StepSegment[] = [];
  let last = 0;
  // Fresh regex per call — lastIndex is stateful, so a shared instance would
  // resume mid-string on the next step.
  const re = new RegExp(DURATION_TOKEN, "giu");
  let m: RegExpExecArray | null;
  while ((m = re.exec(step)) !== null) {
    // A zero-length match cannot happen (every branch requires a digit), but an
    // unguarded exec loop over a `g` regex is one edit away from spinning.
    if (m[0].length === 0) break;
    if (m.index > last) segments.push({ text: step.slice(last, m.index), seconds: null });
    segments.push({ text: m[0], seconds: parseDurationSeconds(m[0]) });
    last = m.index + m[0].length;
  }
  if (last < step.length) segments.push({ text: step.slice(last), seconds: null });
  if (segments.length === 0) segments.push({ text: step, seconds: null });
  return segments;
}
