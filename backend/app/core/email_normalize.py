"""Email normalization for anti-abuse uniqueness (NOT for delivery).

Maps an address to a canonical key stored in `User.normalized_email` and used for
uniqueness + all auth/reset lookups — the raw `User.email` is kept verbatim for
delivery, display, and Stripe. Collapses the alias tricks that would otherwise let
one real inbox register many accounts: Gmail dot-insertion and `+tag` subaddressing
(and the same `+tag` on the handful of other providers that officially support it).

Deliberately conservative: dot-stripping is Gmail-only (only Gmail ignores dots),
and `+tag` stripping is limited to a curated allowlist — on a provider that does
NOT do subaddressing, `a+b@x` can be a *different* real mailbox than `a@x`, so
over-normalizing would wrongly merge distinct people.

Unlike its Optional-returning siblings normalize_country/normalize_language, this
always returns a non-empty str: the empty-local guard ensures a pathological input
(e.g. "+tag@gmail.com") never yields an invalid empty local part.
"""

# Providers that officially document "+tag" subaddressing. NOT universal (many
# providers treat "+" as a literal char) and NOT Yahoo (Yahoo uses "-", not "+").
# NEVER add a domain under which the app mints synthetic "+suffix" accounts (e.g.
# trymealbot.com for demo users — see services.demo_user); allowlisting it would
# collapse every such account to one key and break their uniqueness.
_PLUS_TAG_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "proton.me",
        "protonmail.com",
        "fastmail.com",
    }
)

# Only Gmail ignores dots in the local part.
_DOT_STRIP_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def normalize_email(email: str) -> str:
    """Canonical uniqueness key for an (already EmailStr-validated) address.

    Splits on the last '@', lowercases the domain (googlemail.com -> gmail.com),
    lowercases the local part, strips '+tag' for allowlisted providers, strips dots
    for Gmail, and guards against an empty local part. Lowercasing the local part is
    technically RFC-significant but no real provider distinguishes case, and case
    variants are a trivial farming vector.
    """
    local, _, domain = email.strip().rpartition("@")
    if not local:
        # No '@' (shouldn't happen post-EmailStr) — return lowercased as-is.
        return email.strip().lower()
    domain = domain.lower()
    if domain == "googlemail.com":
        domain = "gmail.com"
    elif domain in ("me.com", "mac.com"):
        # Apple: @me.com / @mac.com are aliases of @icloud.com — one reserved,
        # globally-unique username namespace, so same local part = same owner.
        domain = "icloud.com"
    original_local = local.lower()
    local = original_local
    if domain in _PLUS_TAG_DOMAINS:
        local = local.split("+", 1)[0]
    if domain in _DOT_STRIP_DOMAINS:
        local = local.replace(".", "")
    if not local:
        # e.g. "+tag@gmail.com" or ".@gmail.com" — never emit an empty local part.
        local = original_local
    return f"{local}@{domain}"
