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

from pydantic import BaseModel, Field, ValidationError

from app.core.config import LLMProvider, ModelEntry, settings
from app.llm.client import DISCLOSED_PROVIDERS

logger = logging.getLogger(__name__)

#: Models that passed backend/evals: 100% safety clean, and no worse than the
#: production primary on the rest. A model joins in the PR that adds its
#: scorecard; this list, not the env, is the gate. Spelled as in LLM_MODELS.
EVAL_APPROVED: frozenset[str] = frozenset()


class ExperimentArm(BaseModel):
    """One LLM_EXPERIMENT entry: this share of meal generations tries `entry` first."""

    entry: ModelEntry
    percent: float = Field(gt=0, le=100)


def parse_arms(raw: str) -> tuple[list[ExperimentArm], list[str]]:
    """LLM_EXPERIMENT as arms, plus one problem per part it could not use.

    Never raises: an entry it cannot read is skipped and named, so a typo in
    an optional experiment costs that arm, never the app's boot. Percents over
    100 in total turn the whole experiment off, since no reading of them is
    the one that was meant.
    """
    arms: list[ExperimentArm] = []
    problems: list[str] = []
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        spec, eq, percent = item.rpartition("=")
        provider, slash, model = (part.strip() for part in spec.partition("/"))
        try:
            if not (eq and slash and model):
                raise ValueError("expected provider/model=percent")
            arm = ExperimentArm(
                entry=ModelEntry(provider=LLMProvider(provider), model=model), percent=float(percent)
            )
        except (ValueError, ValidationError) as exc:
            reason = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
            problems.append(f"{item!r}: {reason}")
            continue
        if any(a.entry == arm.entry for a in arms):
            problems.append(f"{item!r}: names {arm.entry.label} a second time")
            continue
        arms.append(arm)
    if sum(a.percent for a in arms) > 100:
        problems.append("the percents add up to more than 100, so the experiment is off")
        arms = []
    return arms, problems


def ineligibility(entry: ModelEntry) -> str | None:
    """Why this model may not be an arm, or None if it may."""
    if entry.provider not in DISCLOSED_PROVIDERS:
        return "its provider is not named in the privacy policy (DISCLOSED_PROVIDERS)"
    if entry.label not in EVAL_APPROVED:
        return "it has not passed the offline evals (EVAL_APPROVED)"
    return None


def eligible_arms() -> list[ExperimentArm]:
    arms, _ = parse_arms(settings.llm_experiment)
    return [arm for arm in arms if ineligibility(arm.entry) is None]


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
    arms, problems = parse_arms(settings.llm_experiment)
    for problem in problems:
        logger.error("LLM_EXPERIMENT %s.", problem)
    for arm in arms:
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
