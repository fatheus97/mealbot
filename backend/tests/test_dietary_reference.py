"""Tests for the dietary reference layer (slice 2).

Covers: fidelity to the enums + docs/dietary-reference.md (completeness, no
fabricated members, every record cited), exact-lookup retrieval, and the Part-3
combination rules.
"""

from app.core.dietary import Allergen, DietType
from app.core.dietary_reference import (
    ALLERGEN_INFO,
    PATTERN_INFO,
    Confidence,
    EvidenceTier,
    WarningLevel,
    resolve_dietary_context,
)

# The DietType members that are app-specific (no reference-doc dietary pattern);
# baby_food carries its own INFANT FOOD MODE prompt rules elsewhere.
_APP_SPECIFIC_DIETS = {
    DietType.BALANCED,
    DietType.HIGH_PROTEIN,
    DietType.LOW_CARB,
    DietType.BABY_FOOD,
}


class TestReferenceCompleteness:
    def test_all_eu14_allergens_encoded(self):
        # Every EU-14 allergen has an entry — the whole enum, nothing missing.
        assert set(ALLERGEN_INFO) == set(Allergen)
        assert len(ALLERGEN_INFO) == 14

    def test_allergen_info_keys_match_records(self):
        for key, info in ALLERGEN_INFO.items():
            assert info.allergen == key
            assert info.label
            assert info.source
            assert info.derivatives  # non-empty derivative set

    def test_every_dietary_pattern_encoded_and_no_app_specific_ones(self):
        expected = set(DietType) - _APP_SPECIFIC_DIETS
        assert set(PATTERN_INFO) == expected
        # The app-specific diets must NOT have reference records.
        for d in _APP_SPECIFIC_DIETS:
            assert d not in PATTERN_INFO

    def test_pattern_info_keys_match_records(self):
        for key, info in PATTERN_INFO.items():
            assert info.diet_type == key
            assert info.label
            assert info.summary
            assert info.source

    def test_confidence_marks_match_doc(self):
        # Spot-check the confidence marks carried over from the doc.
        assert PATTERN_INFO[DietType.VEGAN].confidence == Confidence.VERIFIED
        assert PATTERN_INFO[DietType.GLUTEN_FREE].confidence == Confidence.VERIFIED
        assert PATTERN_INFO[DietType.DASH].confidence == Confidence.VERIFIED
        assert PATTERN_INFO[DietType.LOW_FODMAP].confidence == Confidence.VERIFIED
        # Vegetarian still awaits a vegetarian-specific source (🔶 split).
        assert PATTERN_INFO[DietType.VEGETARIAN].confidence == Confidence.SOURCED
        # Halal/kosher are curated + describe-don't-certify.
        assert PATTERN_INFO[DietType.HALAL].confidence == Confidence.CURATED
        assert PATTERN_INFO[DietType.KOSHER].confidence == Confidence.CURATED

    def test_sulphites_flagged_as_sourced_with_as_consumed_caveat(self):
        info = ALLERGEN_INFO[Allergen.SULPHITES]
        assert info.confidence == Confidence.SOURCED
        assert "as-consumed" in info.note.lower() or "as consumed" in info.note.lower()

    def test_tree_nut_species_expanded(self):
        # The doc's "the 8 species above" must be expanded into concrete terms.
        derived = ALLERGEN_INFO[Allergen.TREE_NUTS].derivatives
        for species in ("almond", "hazelnut", "walnut", "cashew", "pecan",
                        "brazil nut", "pistachio", "macadamia"):
            assert species in derived

    def test_evidence_tiers_are_valid(self):
        for info in PATTERN_INFO.values():
            assert isinstance(info.tier, EvidenceTier)

    def test_vegetarian_carries_lower_than_vegan_caveat(self):
        # The doc's comparative note ("risk is lower than vegan") is preserved.
        assert "lower" in PATTERN_INFO[DietType.VEGETARIAN].note.lower()
        assert "vegan" in PATTERN_INFO[DietType.VEGETARIAN].note.lower()


class TestRetrieval:
    def test_empty_request_returns_empty_context(self):
        ctx = resolve_dietary_context([], [])
        assert ctx.is_empty()
        assert ctx.patterns == ()
        assert ctx.allergens == ()
        assert ctx.warnings == ()

    def test_single_pattern_resolves(self):
        ctx = resolve_dietary_context([DietType.VEGAN], [])
        assert len(ctx.patterns) == 1
        assert ctx.patterns[0].diet_type == DietType.VEGAN
        assert not ctx.is_empty()

    def test_app_specific_diet_is_silently_skipped(self):
        # `balanced` has no reference record — resolve drops it rather than error.
        ctx = resolve_dietary_context([DietType.BALANCED], [])
        assert ctx.patterns == ()
        assert ctx.is_empty()

    def test_declared_order_preserved(self):
        ctx = resolve_dietary_context(
            [DietType.GLUTEN_FREE, DietType.VEGAN], [Allergen.MILK, Allergen.PEANUTS],
        )
        assert [p.diet_type for p in ctx.patterns] == [
            DietType.GLUTEN_FREE, DietType.VEGAN,
        ]
        assert [a.allergen for a in ctx.allergens] == [Allergen.MILK, Allergen.PEANUTS]

    def test_allergen_terms_include_base_and_derivatives(self):
        ctx = resolve_dietary_context([], [Allergen.MILK])
        terms = ctx.allergen_terms()[Allergen.MILK]
        assert "milk" in terms
        assert "whey" in terms
        assert "casein" in terms
        # All lowercase, no duplicates.
        assert list(terms) == [t.lower() for t in terms]
        assert len(terms) == len(set(terms))

    def test_prompt_lines_cover_patterns_allergens_and_warnings(self):
        ctx = resolve_dietary_context(
            [DietType.VEGAN, DietType.LOW_FODMAP], [Allergen.TREE_NUTS],
        )
        blob = "\n".join(ctx.prompt_lines())
        assert "Vegan" in blob
        assert "Tree nuts" in blob
        assert "almond" in blob  # a derivative surfaced for the model
        # vegan + low_fodmap fires a Part-3 warning that must reach the prompt.
        assert "consult_dietitian" in blob


class TestCombinationRules:
    def test_pescatarian_plus_all_seafood_allergies_is_contradiction(self):
        ctx = resolve_dietary_context(
            [DietType.PESCATARIAN],
            [Allergen.FISH, Allergen.CRUSTACEANS, Allergen.MOLLUSCS],
        )
        levels = [w.level for w in ctx.warnings]
        assert WarningLevel.CONTRADICTION in levels
        # The general stacked-escalation must NOT also fire on top of a contradiction.
        assert levels.count(WarningLevel.CONSULT_DIETITIAN) == 0

    def test_pescatarian_plus_fish_only_is_warning_not_contradiction(self):
        # A fish allergy alone still leaves crustaceans/molluscs — restrictive,
        # not impossible.
        ctx = resolve_dietary_context([DietType.PESCATARIAN], [Allergen.FISH])
        levels = [w.level for w in ctx.warnings]
        assert WarningLevel.WARNING in levels
        assert WarningLevel.CONTRADICTION not in levels

    def test_vegan_pescatarian_is_contradiction(self):
        # Vegan forbids the fish/seafood pescatarian requires — impossible combo,
        # must be caught pre-generation (Part 3's stated goal).
        ctx = resolve_dietary_context([DietType.VEGAN, DietType.PESCATARIAN], [])
        levels = [w.level for w in ctx.warnings]
        assert WarningLevel.CONTRADICTION in levels
        # The contradiction suppresses the general stacked-escalation.
        assert levels.count(WarningLevel.CONSULT_DIETITIAN) == 0

    def test_vegan_low_fodmap_suggests_dietitian(self):
        ctx = resolve_dietary_context([DietType.VEGAN, DietType.LOW_FODMAP], [])
        assert any(w.level == WarningLevel.CONSULT_DIETITIAN for w in ctx.warnings)
        assert any("low-fodmap" in w.message.lower() for w in ctx.warnings)

    def test_vegan_keto_extremely_constrained(self):
        ctx = resolve_dietary_context([DietType.VEGAN, DietType.KETO], [])
        assert any(w.level == WarningLevel.CONSULT_DIETITIAN for w in ctx.warnings)

    def test_vegan_plus_two_protein_allergens_flags_deficiency(self):
        ctx = resolve_dietary_context(
            [DietType.VEGAN], [Allergen.SOYBEANS, Allergen.TREE_NUTS],
        )
        assert any(
            w.level == WarningLevel.CONSULT_DIETITIAN and "plant-protein" in w.message
            for w in ctx.warnings
        )

    def test_vegan_plus_one_protein_allergen_does_not_flag_deficiency(self):
        ctx = resolve_dietary_context([DietType.VEGAN], [Allergen.SOYBEANS])
        assert not any("plant-protein" in w.message for w in ctx.warnings)

    def test_gluten_free_vegan_is_a_light_note(self):
        ctx = resolve_dietary_context([DietType.GLUTEN_FREE, DietType.VEGAN], [])
        assert any(w.level == WarningLevel.NOTE for w in ctx.warnings)

    def test_keto_plus_dash_surfaces_tension(self):
        ctx = resolve_dietary_context([DietType.KETO, DietType.DASH], [])
        assert any(w.level == WarningLevel.WARNING for w in ctx.warnings)

    def test_keto_plus_mediterranean_surfaces_tension(self):
        ctx = resolve_dietary_context([DietType.KETO, DietType.MEDITERRANEAN], [])
        assert any(w.level == WarningLevel.WARNING for w in ctx.warnings)

    def test_stacked_restrictions_escalate_to_dietitian(self):
        # Four benign restrictions with no specific rule → general escalation.
        ctx = resolve_dietary_context(
            [DietType.MEDITERRANEAN, DietType.PALEO],
            [Allergen.EGGS, Allergen.CELERY],
        )
        assert any(w.level == WarningLevel.CONSULT_DIETITIAN for w in ctx.warnings)

    def test_general_escalation_not_double_counted(self):
        # vegan + low_fodmap already escalates to a dietitian; adding a 2-item
        # stack past the threshold must not append a SECOND consult warning.
        ctx = resolve_dietary_context(
            [DietType.VEGAN, DietType.LOW_FODMAP],
            [Allergen.MILK, Allergen.EGGS],
        )
        consults = [w for w in ctx.warnings if w.level == WarningLevel.CONSULT_DIETITIAN]
        assert len(consults) == 1

    def test_benign_single_restriction_has_no_warnings(self):
        ctx = resolve_dietary_context([DietType.MEDITERRANEAN], [])
        assert ctx.warnings == ()

    def test_every_warning_is_cited(self):
        ctx = resolve_dietary_context(
            [DietType.VEGAN, DietType.LOW_FODMAP], [Allergen.SOYBEANS, Allergen.TREE_NUTS],
        )
        assert ctx.warnings  # this combo produces warnings
        for w in ctx.warnings:
            assert w.source
