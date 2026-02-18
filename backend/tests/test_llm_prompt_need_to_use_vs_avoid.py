from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import pytest
from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app


# --------------------------------------------------------------------------------------
# Safety switch: do NOT run real LLM tests unless explicitly enabled.
# --------------------------------------------------------------------------------------
RUN_LLM_TESTS = settings.run_llm_tests
LLM_MOCK = settings.llm_mock

if not RUN_LLM_TESTS or LLM_MOCK:
    pytest.skip(
        "Skipping real-LLM prompt tests. Set RUN_LLM_TESTS=1 and LLM_MOCK=false to enable.",
        allow_module_level=True,
    )

# Delay between requests to reduce rate-limit / overload issues.
REQUEST_DELAY_S = float(os.getenv("LLM_TEST_DELAY_S", "1.5"))

# Cache responses to avoid repeatedly paying for 50 LLM calls on every run.
CACHE_DIR = Path(__file__).parent / "llm_snapshots" / "need_to_use_vs_avoid"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OVERWRITE_CACHE = os.getenv("LLM_TEST_OVERWRITE", "0") == "1"


# --------------------------------------------------------------------------------------
# Synonyms + hyponyms expansion
# The idea: validator searches the response for avoid_term + expansions.
# This is NOT "perfect semantics" — it is intentionally a pragmatic dictionary-based check.
# --------------------------------------------------------------------------------------
AVOID_ALIASES: Dict[str, str] = {
    "legumes": "legume",
    "pulses": "legume",
    "beans": "legume",
    "fishes": "fish",
    "seafood": "seafood",
    "shell fishes": "shellfish",
    "tree nuts": "nut",
    "nuts": "nut",
    "eggs": "egg",
}

AVOID_EXPANSIONS: Dict[str, Set[str]] = {
    # Category term -> terms to search in response
    "fish": {
        "fish",
        "carp", "salmon", "tuna", "cod", "sardine", "sardines", "anchovy", "anchovies",
        "tilapia", "mackerel", "trout",
        "fish sauce",
    },
    "shellfish": {
        "shellfish",
        "shrimp", "prawn", "crab", "lobster", "mussel", "mussels", "oyster", "oysters", "clam", "clams",
    },
    "seafood": {
        "seafood",
        # include fish + shellfish terms
        "fish",
        "carp", "salmon", "tuna", "cod", "sardine", "sardines", "anchovy", "anchovies",
        "shrimp", "prawn", "crab", "lobster", "mussel", "mussels", "oyster", "oysters", "clam", "clams",
    },
    "legume": {
        "legume", "legumes",
        "lentil", "lentils",
        "chickpea", "chickpeas",
        "bean", "beans",
        "black bean", "black beans",
        "kidney bean", "kidney beans",
        "pea", "peas",
        "soybean", "soybeans",
        "peanut", "peanuts",
        "edamame",
        "hummus",
    },
    "soy": {
        "soy", "soya",
        "tofu", "tempeh", "edamame",
        "soy sauce", "miso", "miso paste",
    },
    "dairy": {
        "dairy",
        "milk",
        "cheese", "cheddar", "mozzarella", "parmesan",
        "yogurt", "yoghurt",
        "butter", "cream",
    },
    "gluten": {
        "gluten",
        "wheat", "wheat flour", "flour",
        "barley", "rye",
        "bread", "breadcrumbs",
        "pasta", "noodles",
        "couscous",
        "seitan",
    },
    "nut": {
        "nut", "nuts",
        "almond", "almonds",
        "cashew", "cashews",
        "walnut", "walnuts",
        "hazelnut", "hazelnuts",
        "peanut", "peanuts",
        "peanut butter",
    },
    "egg": {
        "egg", "eggs",
    },
    "pork": {
        "pork",
        "bacon", "ham", "sausage", "prosciutto",
    },
    "sesame": {
        "sesame",
        "sesame oil",
        "tahini",
    },
}


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _canonical_avoid(term: str) -> str:
    t = _norm(term)
    return AVOID_ALIASES.get(t, t)


def _terms_for_avoid(avoid_term: str) -> Set[str]:
    canon = _canonical_avoid(avoid_term)
    terms = set(AVOID_EXPANSIONS.get(canon, set()))
    # Always include the raw + canonical term too (so we search the explicit avoid word).
    terms.add(_norm(avoid_term))
    terms.add(canon)
    # Remove empty strings
    return {t for t in terms if t}


def _text_contains_term(text: str, term: str) -> bool:
    """
    Word-ish boundary match.
    Works for single and multi-word terms.
    """
    t = _norm(term)
    if not t:
        return False
    # Regex boundary at ends; for multiword this still works reasonably.
    pattern = r"\b" + re.escape(t) + r"\b"
    return re.search(pattern, text) is not None


def _find_hits_in_response(response_json: dict, avoid_term: str) -> List[str]:
    """
    Search full response text for avoid_term + synonyms/hyponyms.
    This follows your idea: "search the avoid word and its synonyms/hyponyms in the response".
    """
    response_text = json.dumps(response_json, ensure_ascii=False).lower()
    hits: List[str] = []
    for term in sorted(_terms_for_avoid(avoid_term)):
        if _text_contains_term(response_text, term):
            hits.append(term)
    return hits


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _norm(s)).strip("_")


# 50 conflict scenarios (need_to_use ingredient that is inside the avoid category)
SCENARIOS: List[Tuple[str, str]] = [
    ("lentil", "legume"),
    ("lentils", "legume"),
    ("chickpeas", "legume"),
    ("black beans", "legume"),
    ("kidney beans", "legume"),
    ("peas", "legume"),
    ("peanut", "legume"),
    ("tofu", "soy"),
    ("tempeh", "soy"),
    ("edamame", "soy"),
    ("miso paste", "soy"),
    ("soy sauce", "soy"),
    ("milk", "dairy"),
    ("cheddar cheese", "dairy"),
    ("mozzarella", "dairy"),
    ("yogurt", "dairy"),
    ("butter", "dairy"),
    ("cream", "dairy"),
    ("carp", "fish"),
    ("salmon", "fish"),
    ("tuna", "fish"),
    ("cod", "fish"),
    ("sardines", "fish"),
    ("anchovies", "fish"),
    ("shrimp", "shellfish"),
    ("prawn", "shellfish"),
    ("crab", "shellfish"),
    ("lobster", "shellfish"),
    ("mussels", "shellfish"),
    ("oysters", "shellfish"),
    ("bread", "gluten"),
    ("pasta", "gluten"),
    ("wheat flour", "gluten"),
    ("barley", "gluten"),
    ("rye bread", "gluten"),
    ("couscous", "gluten"),
    ("seitan", "gluten"),
    ("breadcrumbs", "gluten"),
    ("almonds", "nut"),
    ("cashews", "nut"),
    ("walnuts", "nut"),
    ("hazelnuts", "nut"),
    ("peanut butter", "nut"),
    ("egg", "egg"),
    ("eggs", "egg"),
    ("bacon", "pork"),
    ("ham", "pork"),
    ("sausage", "pork"),
    ("sesame oil", "sesame"),
    ("tahini", "sesame"),
]


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


def test_llm_prompt_need_to_use_vs_avoid_consistency(client: TestClient) -> None:
    """
    Sequentially calls the real LLM via backend planning endpoint and validates:
    The response must not contain avoid_term nor its synonyms/hyponyms.
    """
    # Create or login a user (matches frontend behavior) :contentReference[oaicite:2]{index=2}
    email = os.getenv("LLM_TEST_EMAIL", "llm_prompt_tests@example.com")
    r = client.post("/api/users/", params={"email": email})
    assert r.status_code == 200, r.text
    user_id = int(r.json())

    failures: List[str] = []

    for idx, (need_to_use_item, avoid_term) in enumerate(SCENARIOS, start=1):
        # Prepare fridge: include a couple of safe staples so the model has alternatives.
        fridge = [
            {"name": need_to_use_item, "quantity_grams": 200, "need_to_use": True},
            {"name": "rice", "quantity_grams": 600, "need_to_use": False},
            {"name": "spinach", "quantity_grams": 200, "need_to_use": False},
        ]

        # Ensure backend fridge state is set
        rf = client.put(f"/api/users/{user_id}/fridge", json=fridge)
        if rf.status_code != 200:
            failures.append(
                f"[{idx}] PUT fridge failed ({need_to_use_item=} {avoid_term=}): "
                f"{rf.status_code} {rf.text}"
            )
            continue

        request_body = {
            "ingredients": fridge,
            "taste_preferences": [],
            "avoid_ingredients": [avoid_term],
            "diet_type": None,
            "meals_per_day": 1,
            "people_count": 1,
            "past_meals": [],
        }

        cache_path = CACHE_DIR / f"{idx:02d}__{_slug(need_to_use_item)}__avoid_{_slug(avoid_term)}.json"

        if cache_path.exists() and not OVERWRITE_CACHE:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            response_json = cached["response"]
        else:
            # Call plan endpoint (matches frontend behavior) :contentReference[oaicite:3]{index=3}
            rp = client.post(f"/api/users/{user_id}/plan?days=1", json=request_body)

            if rp.status_code != 200:
                failures.append(
                    f"[{idx}] PLAN failed ({need_to_use_item=} {avoid_term=}): "
                    f"{rp.status_code} {rp.text}"
                )
                # Back off a bit to avoid hammering when errors happen
                time.sleep(max(REQUEST_DELAY_S, 2.0))
                continue

            response_json = rp.json()

            cache_path.write_text(
                json.dumps(
                    {"scenario": {"need_to_use": need_to_use_item, "avoid": avoid_term},
                     "request": request_body,
                     "response": response_json},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            time.sleep(REQUEST_DELAY_S)

        # Validator: search avoid_term + synonyms/hyponyms in full response JSON
        hits = _find_hits_in_response(response_json, avoid_term)
        if hits:
            failures.append(
                f"[{idx}] VIOLATION: avoid='{avoid_term}' need_to_use='{need_to_use_item}' "
                f"-> found terms in response: {hits}. Snapshot: {cache_path.name}"
            )

    assert not failures, "LLM prompt consistency violations:\n" + "\n".join(failures)
