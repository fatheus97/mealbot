"""Curated, source-cited reference layer for dietary restrictions & allergens.

Slice 2 of the evidence-grounded dietary differentiator. Encodes
``docs/dietary-reference.md`` (v1.1) as structured data **keyed on the slice-1
enums** (``app.core.dietary``): the EU-14 allergen derivative sets ("products
thereof"), the Part-2 dietary-pattern definitions, and the Part-3 combination
rules — plus ``resolve_dietary_context()``, which returns the slice relevant to a
given request's declared restrictions.

CONSUMED BY LATER SLICES — not wired into generation yet:
  - the prompt redesign (slice 3) feeds ``DietaryContext.prompt_lines()`` to the
    LLM as authoritative context ("nut-free" = the verified species set +
    derivatives, not the model's guess);
  - the deterministic allergen screen (slice 4) scans generated ingredient names
    against ``DietaryContext.allergen_terms()``, rejecting → regenerating on a hit.
Nothing calls ``resolve_dietary_context()`` in the generation path today.

RETRIEVAL IS EXACT KEYED LOOKUP, deliberately not vector RAG: the key is a closed
enum set (14 allergens, the ``DietType`` patterns), so a dict lookup is correct —
embedding a closed enum to similarity-search a value the user already named would
be misapplied machinery. The pgvector RAG stack (``recipe_retriever.py``) stays
for open-ended retrieval (cookbook meals) where fuzzy matching actually fits.
This matches ``docs/dietary-reference.md`` "How to use": feed "the user's declared
restrictions + their derivative lists" as context.

⚠️ NOT medical or legal advice. Confidence is marked per record (see
``Confidence``): the allergen LIST and its regulatory scope are VERIFIED, but the
derivative/alias cells are largely CURATED — the law requires "products thereof"
be excluded but does not enumerate them, so each derivative list must be
re-checked against a labelling authority before it is presented as a guarantee.
Marketing stays transparency, never a "safe"/"free-from"/"clinically approved"
guarantee (``docs/dietary-reference.md`` Part 4). Halal/kosher: the app biases
toward compliance, it does NOT certify.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.dietary import Allergen, DietType


class Confidence(StrEnum):
    """How well-supported a reference claim is (docs/dietary-reference.md legend)."""

    VERIFIED = "verified"  # ✅ adversarially-verified or direct primary-source quote
    SOURCED = "sourced"    # 🔶 sourced / split vote — re-check before a public claim
    CURATED = "curated"    # ✍️ domain knowledge added to be usable; source before shipping


class EvidenceTier(StrEnum):
    """Standing of a dietary pattern (docs/dietary-reference.md Part 2)."""

    MEDICALLY_INDICATED = "medically_indicated"
    STRONG_EVIDENCE = "strong_evidence"
    LIFESTYLE = "lifestyle"
    RELIGIOUS = "religious"


class WarningLevel(StrEnum):
    """Escalation for a stacked-restriction combination (docs Part 3):
    ``silent → warning → consult a dietitian`` as count/severity rises, plus a
    hard ``contradiction`` for an impossible request (a pattern requiring a food
    another restriction forbids)."""

    NOTE = "note"                       # workable; proceed with a light note
    WARNING = "warning"                 # possible but restrictive
    CONSULT_DIETITIAN = "consult_dietitian"
    CONTRADICTION = "contradiction"     # impossible as stated (e.g. pescatarian + fish allergy)


@dataclass(frozen=True)
class AllergenInfo:
    """One EU-14 allergen: the alias/derivative set to ALSO exclude ("products
    thereof") plus regulatory scope. ``derivatives`` are lowercase terms the
    screen (slice 4) matches against ingredient names; CURATED unless the
    ``confidence`` says otherwise."""

    allergen: Allergen
    label: str
    in_us_big9: bool
    derivatives: tuple[str, ...]
    confidence: Confidence
    source: str
    note: str = ""


@dataclass(frozen=True)
class PatternInfo:
    """One dietary pattern (docs Part 2): its definition (excludes/requires,
    rendered into prompt context), evidence tier, key nutrient risks, and
    citation. ``requires`` names allergen categories the pattern structurally
    depends on — used to detect contradictions with a declared allergy."""

    diet_type: DietType
    label: str
    tier: EvidenceTier
    summary: str
    nutrient_risks: tuple[str, ...]
    confidence: Confidence
    source: str
    note: str = ""
    requires: tuple[Allergen, ...] = ()


@dataclass(frozen=True)
class CombinationWarning:
    """A Part-3 verdict about a specific combination of declared restrictions."""

    level: WarningLevel
    message: str
    source: str = ""


# --- Shared citation strings (docs/dietary-reference.md Part 1 & sources) ---
_ANNEX_II = (
    "EU FIC Reg. (EU) No 1169/2011 Annex II (legislation.gov.uk); "
    "derivatives ✍️ curated — docs/dietary-reference.md Part 1"
)


# The 14 major allergens (EU FIC Annex II). The allergen list + regulatory scope
# are ✅ verified; the per-allergen derivative terms are ✍️ curated to make the
# table screen-usable (the law requires "products thereof" be excluded but does
# not enumerate them). "the 8 tree-nut species" / "spelt→wheat" references from
# the doc are expanded into concrete terms here.
ALLERGEN_INFO: dict[Allergen, AllergenInfo] = {
    Allergen.CEREALS_WITH_GLUTEN: AllergenInfo(
        allergen=Allergen.CEREALS_WITH_GLUTEN,
        label="Cereals containing gluten",
        in_us_big9=True,  # US covers wheat only
        derivatives=(
            "gluten", "wheat", "spelt", "khorasan", "kamut", "durum", "rye",
            "barley", "oats", "triticale", "semolina", "farro", "einkorn",
            "bulgur", "couscous", "seitan", "malt", "malt extract",
            "brewer's yeast", "modified starch", "soy sauce",
        ),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
        note="Closed cereal list; spelt/khorasan/durum are declared as 'wheat'.",
    ),
    Allergen.CRUSTACEANS: AllergenInfo(
        allergen=Allergen.CRUSTACEANS,
        label="Crustaceans",
        in_us_big9=True,
        derivatives=(
            "crustacean", "shrimp", "prawn", "crab", "lobster", "crayfish",
            "krill", "shellfish stock", "surimi",
        ),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
    ),
    Allergen.EGGS: AllergenInfo(
        allergen=Allergen.EGGS,
        label="Eggs",
        in_us_big9=True,
        derivatives=(
            "egg", "albumin", "albumen", "globulin", "livetin", "lysozyme",
            "ovalbumin", "ovo", "mayonnaise", "meringue", "egg wash",
        ),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
    ),
    Allergen.FISH: AllergenInfo(
        allergen=Allergen.FISH,
        label="Fish",
        in_us_big9=True,
        derivatives=(
            "fish", "anchovy", "worcestershire", "caesar dressing", "fish sauce",
            "fish stock", "surimi", "isinglass", "fish gelatine",
        ),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
    ),
    Allergen.PEANUTS: AllergenInfo(
        allergen=Allergen.PEANUTS,
        label="Peanuts",
        in_us_big9=True,
        derivatives=(
            "peanut", "groundnut", "arachis", "arachis oil", "peanut flour",
            "peanut butter", "satay",
        ),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
    ),
    Allergen.SOYBEANS: AllergenInfo(
        allergen=Allergen.SOYBEANS,
        label="Soybeans",
        in_us_big9=True,
        derivatives=(
            "soy", "soya", "soybean", "edamame", "tofu", "tempeh", "miso",
            "natto", "soy sauce", "tamari", "soya flour", "tvp", "soy lecithin",
        ),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
    ),
    Allergen.MILK: AllergenInfo(
        allergen=Allergen.MILK,
        label="Milk (incl. lactose)",
        in_us_big9=True,
        derivatives=(
            "milk", "whey", "casein", "caseinate", "lactose", "curds", "ghee",
            "butter", "buttermilk", "cream", "yoghurt", "yogurt",
            "milk chocolate",
        ),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
    ),
    Allergen.TREE_NUTS: AllergenInfo(
        allergen=Allergen.TREE_NUTS,
        label="Tree nuts",
        in_us_big9=True,
        # The EU tree-nut category is a CLOSED list of 8 botanical species,
        # expanded here from the doc's "the 8 species above".
        derivatives=(
            "almond", "hazelnut", "walnut", "cashew", "pecan", "brazil nut",
            "pistachio", "macadamia", "nut oil", "marzipan", "praline",
            "nut butter", "pesto", "gianduja",
        ),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
        note="Closed set of 8 species; US covers additional species.",
    ),
    Allergen.CELERY: AllergenInfo(
        allergen=Allergen.CELERY,
        label="Celery",
        in_us_big9=False,
        derivatives=("celery", "celeriac", "celery seed", "celery salt"),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
    ),
    Allergen.MUSTARD: AllergenInfo(
        allergen=Allergen.MUSTARD,
        label="Mustard",
        in_us_big9=False,
        derivatives=("mustard", "mustard seed", "mustard flour", "mustard oil"),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
    ),
    Allergen.SESAME: AllergenInfo(
        allergen=Allergen.SESAME,
        label="Sesame",
        in_us_big9=True,  # US since 2023 (FASTER Act)
        derivatives=(
            "sesame", "tahini", "hummus", "halva", "gomashio", "sesame oil",
        ),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
    ),
    Allergen.SULPHITES: AllergenInfo(
        allergen=Allergen.SULPHITES,
        label="Sulphur dioxide / sulphites",
        in_us_big9=False,
        derivatives=(
            "sulphite", "sulfite", "sulphur dioxide", "sulfur dioxide",
            "e220", "e221", "e222", "e223", "e224", "e225", "e226", "e227",
            "e228",
            # The doc's five named high-sulphite foods to flag conservatively.
            "dried fruit", "wine", "juice", "vinegar", "processed potato",
        ),
        confidence=Confidence.SOURCED,
        source=_ANNEX_II,
        note=(
            "Declarable only >10 mg/kg SO₂ AS-CONSUMED — a threshold the app "
            "cannot measure, so flag known high-sulphite ingredients "
            "conservatively rather than applying the threshold (2-1 split vote)."
        ),
    ),
    Allergen.LUPIN: AllergenInfo(
        allergen=Allergen.LUPIN,
        label="Lupin",
        in_us_big9=False,
        derivatives=("lupin", "lupine", "lupin flour", "lupin seed"),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
    ),
    Allergen.MOLLUSCS: AllergenInfo(
        allergen=Allergen.MOLLUSCS,
        label="Molluscs",
        in_us_big9=False,
        derivatives=(
            "mollusc", "mussel", "clam", "oyster", "squid", "calamari",
            "octopus", "snail", "scallop", "oyster sauce",
        ),
        confidence=Confidence.CURATED,
        source=_ANNEX_II,
    ),
}


# The dietary patterns (docs Part 2). Keyed on the DietType members that ARE
# recognised dietary patterns — the app-specific DietType values (balanced /
# high_protein / low_carb / baby_food) have no reference-doc rule and are
# intentionally absent (baby_food carries its own INFANT FOOD MODE prompt rules).
PATTERN_INFO: dict[DietType, PatternInfo] = {
    DietType.GLUTEN_FREE: PatternInfo(
        diet_type=DietType.GLUTEN_FREE,
        label="Gluten-free",
        tier=EvidenceTier.MEDICALLY_INDICATED,
        summary=(
            "Excludes all gluten cereals (wheat/rye/barley/oats + derivatives). "
            "The primary treatment for coeliac disease (autoimmune) — not a "
            "lifestyle choice. NB: 'gluten-free' is the only legally-defined "
            "free-from claim."
        ),
        nutrient_risks=("fibre", "iron", "folate", "B vitamins"),
        confidence=Confidence.VERIFIED,
        source="NICE QS134 — https://www.nice.org.uk/guidance/qs134",
    ),
    DietType.DAIRY_FREE: PatternInfo(
        diet_type=DietType.DAIRY_FREE,
        label="Lactose-free / dairy-free",
        tier=EvidenceTier.MEDICALLY_INDICATED,
        summary=(
            "Excludes milk and its derivatives. Distinguish lactose "
            "INTOLERANCE (dose-tolerant; lactose-reduced often OK) from a milk "
            "ALLERGY (the Part-1 allergen — strict exclusion of all milk "
            "derivatives)."
        ),
        nutrient_risks=("calcium", "vitamin D", "B12", "iodine"),
        confidence=Confidence.CURATED,
        source="docs/dietary-reference.md Part 2 (well-established)",
    ),
    DietType.LOW_FODMAP: PatternInfo(
        diet_type=DietType.LOW_FODMAP,
        label="Low-FODMAP",
        tier=EvidenceTier.MEDICALLY_INDICATED,
        summary=(
            "A 3-phase clinician-supervised protocol (elimination → "
            "reintroduction → personalisation), NOT a permanent diet. Must be "
            "surfaced as temporary and dietitian-guided, never a standing "
            "preference."
        ),
        nutrient_risks=("adequacy risk if prolonged",),
        confidence=Confidence.VERIFIED,
        source="Monash — https://www.monashfodmap.com/blog/3-phases-low-fodmap-diet/",
    ),
    DietType.DIABETIC: PatternInfo(
        diet_type=DietType.DIABETIC,
        label="Diabetic / low-GI",
        tier=EvidenceTier.MEDICALLY_INDICATED,
        summary=(
            "Prioritise low-glycaemic-index carbs and controlled "
            "portions/timing; a management approach, not a fixed exclusion list."
        ),
        nutrient_risks=(),
        confidence=Confidence.CURATED,
        source="docs/dietary-reference.md Part 2",
    ),
    DietType.DASH: PatternInfo(
        diet_type=DietType.DASH,
        label="DASH",
        tier=EvidenceTier.STRONG_EVIDENCE,
        summary=(
            "Dietary Approaches to Stop Hypertension: emphasises vegetables, "
            "fruit, whole grains, low-fat dairy, fish/poultry/beans/nuts, "
            "vegetable oils; limits sodium (2,300 mg/day; 1,500 mg lower "
            "target), saturated fat, sugary drinks and sweets."
        ),
        nutrient_risks=(),
        confidence=Confidence.VERIFIED,
        source="NHLBI — https://www.nhlbi.nih.gov/health/dash-eating-plan",
    ),
    DietType.MEDITERRANEAN: PatternInfo(
        diet_type=DietType.MEDITERRANEAN,
        label="Mediterranean",
        tier=EvidenceTier.STRONG_EVIDENCE,
        summary=(
            "Emphasises vegetables, fruit, legumes, whole grains, olive oil, "
            "fish/seafood, nuts; moderate poultry/dairy/eggs; limited red meat "
            "and sweets. A pattern, not a strict exclusion list."
        ),
        nutrient_risks=(),
        confidence=Confidence.CURATED,
        source="docs/dietary-reference.md Part 2 (strong evidence base)",
    ),
    DietType.VEGETARIAN: PatternInfo(
        diet_type=DietType.VEGETARIAN,
        label="Vegetarian",
        tier=EvidenceTier.LIFESTYLE,
        summary=(
            "Excludes meat, poultry, fish/seafood; includes dairy and/or eggs "
            "(lacto-/ovo- variants)."
        ),
        nutrient_risks=("B12", "iron", "zinc", "omega-3"),
        confidence=Confidence.SOURCED,
        source=(
            "Academy of Nutrition & Dietetics — awaits a vegetarian-specific "
            "source (the vegan NHS page doesn't cover it)"
        ),
        note=(
            "Lower deficiency risk than vegan — lacto-/ovo- variants get B12 "
            "from dairy/eggs."
        ),
    ),
    DietType.VEGAN: PatternInfo(
        diet_type=DietType.VEGAN,
        label="Vegan",
        tier=EvidenceTier.LIFESTYLE,
        summary=(
            "Excludes ALL animal products (meat, fish, dairy, eggs, often "
            "honey)."
        ),
        nutrient_risks=(
            "B12 (fortified/supplement required)", "iron", "calcium",
            "vitamin D", "iodine", "omega-3", "selenium",
        ),
        confidence=Confidence.VERIFIED,
        source="NHS — https://www.nhs.uk/live-well/eat-well/how-to-eat-a-balanced-diet/the-vegan-diet/",
    ),
    DietType.PESCATARIAN: PatternInfo(
        diet_type=DietType.PESCATARIAN,
        label="Pescatarian",
        tier=EvidenceTier.LIFESTYLE,
        summary="Vegetarian plus fish/seafood; no meat or poultry.",
        nutrient_risks=(),
        confidence=Confidence.CURATED,
        source="docs/dietary-reference.md Part 2",
        # Structurally depends on fish/seafood for its protein basis — declaring
        # ALL of these as allergies contradicts the pattern (Part 3).
        requires=(Allergen.FISH, Allergen.CRUSTACEANS, Allergen.MOLLUSCS),
    ),
    DietType.PALEO: PatternInfo(
        diet_type=DietType.PALEO,
        label="Paleo",
        tier=EvidenceTier.LIFESTYLE,
        summary=(
            "Excludes grains, legumes, dairy, refined sugar and most processed "
            "foods; emphasises meat, fish, eggs, vegetables, fruit, nuts."
        ),
        nutrient_risks=("calcium", "vitamin D", "fibre"),
        confidence=Confidence.CURATED,
        source="docs/dietary-reference.md Part 2 (weaker evidence base)",
    ),
    DietType.KETO: PatternInfo(
        diet_type=DietType.KETO,
        label="Ketogenic",
        tier=EvidenceTier.MEDICALLY_INDICATED,
        summary=(
            "Very-low-carb, high-fat. Originally a medical epilepsy therapy; "
            "also used for weight/metabolic goals — medical supervision advised "
            "for therapeutic use."
        ),
        nutrient_risks=("fibre", "some micronutrients"),
        confidence=Confidence.CURATED,
        source="docs/dietary-reference.md Part 2",
    ),
    DietType.HALAL: PatternInfo(
        diet_type=DietType.HALAL,
        label="Halal",
        tier=EvidenceTier.RELIGIOUS,
        summary=(
            "Excludes pork and derivatives, alcohol, non-halal-slaughtered "
            "meat, and certain additives (some gelatine/rennet). The app biases "
            "toward compliance; it does NOT certify."
        ),
        nutrient_risks=(),
        confidence=Confidence.CURATED,
        source="docs/dietary-reference.md Part 2 (describe, do not certify)",
    ),
    DietType.KOSHER: PatternInfo(
        diet_type=DietType.KOSHER,
        label="Kosher",
        tier=EvidenceTier.RELIGIOUS,
        summary=(
            "Excludes pork and shellfish; no meat+dairy together; requires "
            "kosher-certified sourcing/preparation. The app biases toward "
            "compliance; it does NOT certify."
        ),
        nutrient_risks=(),
        confidence=Confidence.CURATED,
        source="docs/dietary-reference.md Part 2 (describe, do not certify)",
    ),
}


# Allergen categories whose exclusion strips a vegan diet's MAIN plant-protein
# sources — used for the "vegan + multiple allergen exclusions" deficiency rule.
_VEGAN_PROTEIN_ALLERGENS = frozenset(
    {Allergen.SOYBEANS, Allergen.TREE_NUTS, Allergen.PEANUTS, Allergen.CEREALS_WITH_GLUTEN}
)

# Above this many stacked restrictions, escalate to a dietitian suggestion
# regardless of the specific mix (Part 3 general escalation rule).
_STACK_ESCALATION_THRESHOLD = 4


def _detect_combinations(
    diet_types: frozenset[DietType], allergens: frozenset[Allergen],
) -> list[CombinationWarning]:
    """Encode docs/dietary-reference.md Part 3: detect contradictions and
    high-risk stacks. Order is stable (most-severe concern first per pair)."""
    warnings: list[CombinationWarning] = []

    _MONASH_VEGAN = (
        "Monash — https://www.monashfodmap.com/blog/following-low-fodmap-and-vegan-diet/"
    )
    _PART3 = "docs/dietary-reference.md Part 3 (reasoned)"

    # Contradiction: a pattern requiring a food the user is allergic to. Only a
    # contradiction when EVERY food the pattern depends on is excluded (a fish
    # allergy alone still leaves a pescatarian crustaceans/molluscs).
    for pat in (PATTERN_INFO[d] for d in diet_types if d in PATTERN_INFO):
        if pat.requires and set(pat.requires).issubset(allergens):
            warnings.append(
                CombinationWarning(
                    WarningLevel.CONTRADICTION,
                    f"{pat.label} depends on {', '.join(a.value for a in pat.requires)}, "
                    f"but those are all declared as allergies — this request "
                    f"cannot be satisfied as stated.",
                    source=_PART3,
                )
            )
        elif pat.requires and allergens.intersection(pat.requires):
            excluded = ", ".join(a.value for a in sorted(allergens.intersection(pat.requires)))
            warnings.append(
                CombinationWarning(
                    WarningLevel.WARNING,
                    f"{pat.label} leans on {excluded}, which is declared as an "
                    f"allergy — the remaining safe options are narrow.",
                    source=_PART3,
                )
            )

    # Pattern-vs-pattern contradiction: veganism forbids ALL animal products,
    # including the fish/seafood pescatarianism structurally requires. Same "a
    # pattern requiring a food another forbids" structure as the pescatarian +
    # fish-allergy row, applied between two declared patterns (Part 3's stated
    # goal is to catch impossible combos before generation, not only the one
    # allergen-vs-pattern example the table happens to spell out).
    if DietType.VEGAN in diet_types and DietType.PESCATARIAN in diet_types:
        warnings.append(
            CombinationWarning(
                WarningLevel.CONTRADICTION,
                "Vegan excludes all animal products, but pescatarian requires "
                "fish/seafood — these cannot both hold; the request is impossible "
                "as stated.",
                source=_PART3,
            )
        )

    if DietType.VEGAN in diet_types and DietType.LOW_FODMAP in diet_types:
        warnings.append(
            CombinationWarning(
                WarningLevel.CONSULT_DIETITIAN,
                "Vegan + low-FODMAP is possible but very restrictive: most vegan "
                "protein staples (legumes) are high-FODMAP. Bias to safe proteins "
                "(tofu, tempeh, quinoa, some nuts/seeds; rinsed canned pulses in "
                "small serves) and suggest a dietitian.",
                source=_MONASH_VEGAN,
            )
        )
    if DietType.VEGAN in diet_types and DietType.KETO in diet_types:
        warnings.append(
            CombinationWarning(
                WarningLevel.CONSULT_DIETITIAN,
                "Vegan + ketogenic is extremely constrained (very small food "
                "space: oils, nuts/seeds, tofu). Warn it will be hard/monotonous "
                "and suggest a dietitian.",
                source=_PART3,
            )
        )
    if DietType.VEGAN in diet_types and len(allergens & _VEGAN_PROTEIN_ALLERGENS) >= 2:
        warnings.append(
            CombinationWarning(
                WarningLevel.CONSULT_DIETITIAN,
                "Vegan plus multiple allergen exclusions removes the main "
                "plant-protein sources at once — protein/B12/iron/calcium gaps "
                "compound. Suggest fortification/supplementation and a dietitian.",
                source=_PART3,
            )
        )
    if DietType.VEGAN in diet_types and DietType.GLUTEN_FREE in diet_types:
        warnings.append(
            CombinationWarning(
                WarningLevel.NOTE,
                "Gluten-free + vegan is workable with naturally-GF grains (rice, "
                "quinoa, buckwheat, certified oats). Watch fibre/iron/B12.",
                source=_PART3,
            )
        )
    if DietType.KETO in diet_types and (
        DietType.MEDITERRANEAN in diet_types or DietType.DASH in diet_types
    ):
        warnings.append(
            CombinationWarning(
                WarningLevel.WARNING,
                "Keto partially conflicts with DASH/Mediterranean, which include "
                "whole grains, fruit and legumes that keto restricts — surface "
                "the tension and pick the user's priority.",
                source=_PART3,
            )
        )

    # General escalation: many stacked restrictions raise nutrient-gap risk.
    if len(diet_types) + len(allergens) >= _STACK_ESCALATION_THRESHOLD and not any(
        w.level in (WarningLevel.CONSULT_DIETITIAN, WarningLevel.CONTRADICTION)
        for w in warnings
    ):
        warnings.append(
            CombinationWarning(
                WarningLevel.CONSULT_DIETITIAN,
                "Several restrictions are stacked, which raises the nutrient-gap "
                "risk — consider consulting a dietitian.",
                source="docs/dietary-reference.md Part 3 (general escalation)",
            )
        )

    return warnings


@dataclass(frozen=True)
class DietaryContext:
    """The reference slice relevant to one request's declared restrictions —
    the retrieve half of retrieve-then-augment. Empty when nothing keyed matched.

    ``patterns``/``allergens`` are in the order the caller declared them (unknown
    values silently dropped — e.g. the app-specific ``balanced`` diet_type)."""

    patterns: tuple[PatternInfo, ...]
    allergens: tuple[AllergenInfo, ...]
    warnings: tuple[CombinationWarning, ...]

    def is_empty(self) -> bool:
        return not (self.patterns or self.allergens or self.warnings)

    def allergen_terms(self) -> dict[Allergen, tuple[str, ...]]:
        """For the deterministic screen (slice 4): each declared allergen mapped
        to the lowercase terms to scan generated ingredient names against — its
        own name plus its derivatives, de-duplicated, order preserved."""
        out: dict[Allergen, tuple[str, ...]] = {}
        for info in self.allergens:
            terms: list[str] = [info.allergen.value.replace("_", " ")]
            for term in info.derivatives:
                if term not in terms:
                    terms.append(term)
            out[info.allergen] = tuple(terms)
        return out

    def prompt_lines(self) -> list[str]:
        """For the prompt redesign (slice 3): authoritative context lines the LLM
        should treat as HARD constraints. Deliberately plain strings — these are
        curated, enum-validated reference data (not free-text user input), so the
        prompt slice renders them un-fenced under a "hard constraints" header.

        Allergens get the strongest framing: the prompt is only the first line of
        defence — the deterministic screen (slice 4) is the guarantee — so the
        instruction must be unambiguous about excluding derivatives too."""
        lines: list[str] = []
        for pat in self.patterns:
            lines.append(f"Diet — {pat.label}: {pat.summary}")
        for info in self.allergens:
            derived = ", ".join(info.derivatives)
            lines.append(
                f"ALLERGEN to EXCLUDE — {info.label}: the plan must contain NO "
                f"ingredient that is, contains, or is derived from this. Exclude "
                f"all of these and their synonyms: {derived}."
            )
        for warn in self.warnings:
            lines.append(f"Combination note ({warn.level.value}): {warn.message}")
        return lines


def resolve_dietary_context(
    diet_types: list[DietType], allergens: list[Allergen],
) -> DietaryContext:
    """Retrieve the reference slice for a request's declared restrictions —
    exact keyed lookup, no fuzzy match. Unknown/unmapped members (e.g. the
    app-specific ``balanced`` diet) are silently skipped; combination warnings
    are computed from the full declared set.

    Consumed by the prompt (slice 3) and screen (slice 4); nothing calls this in
    the generation path yet.
    """
    patterns = tuple(PATTERN_INFO[d] for d in diet_types if d in PATTERN_INFO)
    allergen_infos = tuple(ALLERGEN_INFO[a] for a in allergens if a in ALLERGEN_INFO)
    warnings = tuple(_detect_combinations(frozenset(diet_types), frozenset(allergens)))
    return DietaryContext(patterns=patterns, allergens=allergen_infos, warnings=warnings)
