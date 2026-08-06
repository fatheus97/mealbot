"""The version of the published legal documents a user's consent is recorded against.

Recording "they accepted" without recording WHAT they accepted is close to
worthless: the Terms say (§11) that continuing to use Mealbot after a change
means accepting it, so the documents will change, and a bare timestamp cannot
answer "which text did this person agree to?" once they have.

The value is the "Last updated" date printed on ``frontend/terms.html`` and
``frontend/privacy.html``, which is what a user actually sees. A test asserts
all three agree — the failure mode this guards against is editing a legal
document and forgetting the constant, which would silently file new consents
under the old version and make every stored record a lie.

Both documents share one version deliberately. They are presented together, at
one checkbox, in one act of consent; versioning them separately would imply the
user could have accepted one and not the other, which is not what the UI offers.
"""

#: Keep in sync with the "Last updated" line in frontend/terms.html and
#: frontend/privacy.html — pinned by tests/test_legal_version.py.
TERMS_VERSION = "2026-08-06"
