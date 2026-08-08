import type { TranslationKey } from "../i18n";

/**
 * The first unmet password rule, as the key of a COMPLETE sentence.
 *
 * Mirrors the backend — `validate_password_complexity` plus the Field's length
 * bounds (min 8 / max 128) — as an inline hint only; the server is the real
 * gate. The max check spares a >128-char paste an inaccurate "needs a
 * digit"-style 422, since length-too-long is not a complexity failure.
 *
 * ─── Why a key and not a fragment ──────────────────────────────────────────
 * This returned "a digit" for the caller to splice into `Password needs
 * {problem}.`, which cannot be translated: Czech puts the noun in the
 * accusative after "obsahovat" and inflects it per noun, so the carrier
 * sentence has no single correct translation. Whole sentences also let the
 * length rules read naturally ("nejvýše 128 znaků") instead of calquing
 * "to be 128 characters or fewer".
 *
 * ─── Why it lives here ─────────────────────────────────────────────────────
 * It existed TWICE, byte-identical, in ResetPasswordModal and
 * InviteRegisterModal — so the two password forms in the app could drift from
 * each other and from the backend independently. One copy, two call sites.
 */
export function passwordProblem(pw: string): TranslationKey | null {
  if (pw.length < 8) return "auth.error.passwordTooShort";
  if (pw.length > 128) return "auth.password.tooLong";
  if (!/[A-Z]/.test(pw)) return "auth.password.needsUpper";
  if (!/[a-z]/.test(pw)) return "auth.password.needsLower";
  if (!/\d/.test(pw)) return "auth.password.needsDigit";
  return null;
}
