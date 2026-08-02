"""TERMS_VERSION's own shape.

Deliberately does NOT try to read frontend/terms.html. The backend container
mounts only ./backend, so a test that reads the legal pages from here SKIPS —
in CI as well as locally — and a guard that skips is not a guard. The
cross-boundary check ("the constant matches the date printed on the published
pages") lives in the `legal version` CI job, which runs against a full checkout
where both files actually exist. The frontend suite pins the two pages to each
other.
"""
from datetime import date

from app.core.legal import TERMS_VERSION


def test_version_is_an_iso_date() -> None:
    # Stored in the DB next to the consent timestamp and read by humans during
    # a dispute. ISO keeps it unambiguous and sortable; a free-form value like
    # "July 2026" would defeat both.
    date.fromisoformat(TERMS_VERSION)


def test_version_is_not_in_the_future() -> None:
    # A version dated after today means the constant was bumped ahead of
    # publishing the text — consents would be recorded against a document
    # nobody can read yet.
    assert date.fromisoformat(TERMS_VERSION) <= date.today()
