"""Allowed countries for the user profile.

`User.country` is templated into the meal-plan system prompt. Without a
whitelist, free-text input is a prompt-injection vector (see the earlier
<user_content> wrapping that this whitelist supersedes). We also use the
canonical list as the single source of truth that the frontend's country
typeahead fetches on mount, so list drift is impossible.

Aliases: we accept common short forms ("UK", "USA", "Czechia") on input and
normalize them to the canonical spelling stored in the DB.
"""

SUPPORTED_COUNTRIES: frozenset[str] = frozenset({
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola",
    "Antigua and Barbuda", "Argentina", "Armenia", "Australia", "Austria",
    "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados",
    "Belarus", "Belgium", "Belize", "Benin", "Bhutan",
    "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei",
    "Bulgaria", "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia",
    "Cameroon", "Canada", "Central African Republic", "Chad", "Chile",
    "China", "Colombia", "Comoros", "Congo", "Costa Rica",
    "Croatia", "Cuba", "Cyprus", "Czech Republic", "Denmark",
    "Djibouti", "Dominica", "Dominican Republic", "Ecuador", "Egypt",
    "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Eswatini",
    "Ethiopia", "Fiji", "Finland", "France", "Gabon",
    "Gambia", "Georgia", "Germany", "Ghana", "Greece",
    "Grenada", "Guatemala", "Guinea", "Guinea-Bissau", "Guyana",
    "Haiti", "Honduras", "Hungary", "Iceland", "India",
    "Indonesia", "Iran", "Iraq", "Ireland", "Israel",
    "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan",
    "Kenya", "Kiribati", "Kosovo", "Kuwait", "Kyrgyzstan",
    "Laos", "Latvia", "Lebanon", "Lesotho", "Liberia",
    "Libya", "Liechtenstein", "Lithuania", "Luxembourg", "Madagascar",
    "Malawi", "Malaysia", "Maldives", "Mali", "Malta",
    "Marshall Islands", "Mauritania", "Mauritius", "Mexico", "Micronesia",
    "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco",
    "Mozambique", "Myanmar", "Namibia", "Nauru", "Nepal",
    "Netherlands", "New Zealand", "Nicaragua", "Niger", "Nigeria",
    "North Korea", "North Macedonia", "Norway", "Oman", "Pakistan",
    "Palau", "Palestine", "Panama", "Papua New Guinea", "Paraguay",
    "Peru", "Philippines", "Poland", "Portugal", "Qatar",
    "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis", "Saint Lucia",
    "Saint Vincent and the Grenadines", "Samoa", "San Marino",
    "Sao Tome and Principe", "Saudi Arabia",
    "Senegal", "Serbia", "Seychelles", "Sierra Leone", "Singapore",
    "Slovakia", "Slovenia", "Solomon Islands", "Somalia", "South Africa",
    "South Korea", "South Sudan", "Spain", "Sri Lanka", "Sudan",
    "Suriname", "Sweden", "Switzerland", "Syria", "Taiwan",
    "Tajikistan", "Tanzania", "Thailand", "Timor-Leste", "Togo",
    "Tonga", "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan",
    "Tuvalu", "Uganda", "Ukraine", "United Arab Emirates", "United Kingdom",
    "United States", "Uruguay", "Uzbekistan", "Vanuatu", "Vatican City",
    "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe",
})

# Common user-typed spellings and abbreviations mapped to canonical names.
_ALIASES: dict[str, str] = {
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "great britain": "United Kingdom",
    "britain": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "northern ireland": "United Kingdom",
    "usa": "United States",
    "u.s.a.": "United States",
    "u.s.": "United States",
    "united states of america": "United States",
    "america": "United States",
    "czechia": "Czech Republic",
    "holland": "Netherlands",
    "south korea (rok)": "South Korea",
    "korea, south": "South Korea",
    "korea, north": "North Korea",
    "dprk": "North Korea",
    "uae": "United Arab Emirates",
    "myanmar (burma)": "Myanmar",
    "burma": "Myanmar",
    "russian federation": "Russia",
    "macedonia": "North Macedonia",
    "swaziland": "Eswatini",
    "cape verde": "Cabo Verde",
    "east timor": "Timor-Leste",
    "vatican": "Vatican City",
    "holy see": "Vatican City",
}

_LOWER_TO_CANONICAL: dict[str, str] = {s.lower(): s for s in SUPPORTED_COUNTRIES}


def normalize_country(name: str) -> str | None:
    """Return the canonical country name if `name` is recognized, else None.

    Accepts either a canonical name (case-insensitive) or a known alias.
    Empty / whitespace input returns None — callers should treat that as
    "user left the field blank" and store NULL, not as an error.
    """
    key = name.strip().lower()
    if not key:
        return None
    if key in _LOWER_TO_CANONICAL:
        return _LOWER_TO_CANONICAL[key]
    return _ALIASES.get(key)
