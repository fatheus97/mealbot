"""Model experiments on real use: a share of meal generations tries another model.

Set by LLM_EXPERIMENT (app/core/config.py); empty = off. Each plan creation or
regeneration rolls once (pick_arm): with each arm's percent it tries that arm's
model first, the normal chain behind it as fallback; otherwise it runs the chain
as configured (the control). Rolling per generation, not per user, means one
person meets several models, so a model's numbers do not hinge on which people
it happened to draw.

Every generated meal records the model that actually wrote it
(PlannedMeal.generated_by), so what people then do with it (keep, star, cook,
edit, regenerate) can be compared per model.

Two gates keep users away from untested or undisclosed models, checked on every
roll and not only at startup:

* EVAL_APPROVED: the model passed the offline suite (backend/evals).
* DISCLOSED_PROVIDERS: the privacy policy names the provider as a recipient.
  The prompt carries allergies and diets (health data, for halal/kosher a
  religious belief), so an arm on another provider would make that policy false.

An arm failing a gate never runs and its share stays with the control; it is
not handed to the other arms, so their exposure is exactly what was configured.
"""

import logging
import random

from app.core.config import ExperimentArm, ModelEntry, settings
from app.llm.client import DISCLOSED_PROVIDERS

logger = logging.getLogger(__name__)

#: Models that passed backend/evals: 100% safety clean, and no worse than the
#: production primary on the rest. A model joins in the PR that adds its
#: scorecard; this list, not the env, is the gate. Spelled as in LLM_MODELS.
EVAL_APPROVED: frozenset[str] = frozenset()


def ineligibility(entry: ModelEntry) -> str | None:
    """Why this model may not be an arm, or None if it may."""
    if entry.provider not in DISCLOSED_PROVIDERS:
        return "its provider is not named in the privacy policy (DISCLOSED_PROVIDERS)"
    if entry.label not in EVAL_APPROVED:
        return "it has not passed the offline evals (EVAL_APPROVED)"
    return None


def eligible_arms() -> list[ExperimentArm]:
    return [arm for arm in settings.experiment_arms if ineligibility(arm.entry) is None]


def pick_arm() -> ModelEntry | None:
    """Roll for one generation: an arm's model to try first, or None for the control."""
    roll = random.uniform(0, 100)
    for arm in eligible_arms():
        roll -= arm.percent
        if roll < 0:
            return arm.entry
    return None


def check_experiment_arms() -> None:
    """Log at startup what LLM_EXPERIMENT will do. Never raises: a bad arm is
    skipped (the control keeps its share), which is no reason to refuse boot."""
    for arm in settings.experiment_arms:
        reason = ineligibility(arm.entry)
        if reason is not None:
            logger.error(
                "LLM_EXPERIMENT arm %s (%g%%) will not run: %s.", arm.entry.label, arm.percent, reason
            )
    running = eligible_arms()
    if running:
        logger.info(
            "LLM experiment on: %s; the rest run LLM_MODELS.",
            ", ".join(f"{arm.entry.label} {arm.percent:g}%" for arm in running),
        )
