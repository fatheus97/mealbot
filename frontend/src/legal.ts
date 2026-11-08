/**
 * Version of the explicit-consent sentence shown next to the diet/allergy
 * checkbox (`healthConsent.label` in i18n). The server records consent only
 * against its own HEALTH_CONSENT_VERSION (backend/app/core/legal.py) and
 * answers 409 to any other value, so the two must move together: change the
 * sentence in a way that matters (a new recipient or purpose) and bump both.
 * The CI "legal version" job fails when they differ.
 */
export const HEALTH_CONSENT_VERSION = "2026-11-08";
