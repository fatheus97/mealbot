"""Run the meal-plan suite against models and print a scorecard.

    docker compose run --rm backend python -m evals.run \\
        --model gemini/gemini-2.5-flash --model deepseek/deepseek-chat --repeats 3

Each case is sent ONCE per repeat, with production's exact prompt
(``render_day_prompt``) and schema, and the raw answer is graded. Production's
reject-and-retry loop is skipped on purpose: it hides how often a model gets
it wrong, which is what is being measured. Every model runs alone (the chain
is pinned to it), so nothing falls back to another model.

Results (every answer, every check) land in evals/results/ as JSON for human
review, next to the scorecard as Markdown. ``--report`` merges saved runs
into one scorecard, so models run at different times can be compared.
See evals/README.md.
"""

import argparse
import asyncio
import json
import re
import statistics
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from app.core.config import LLMProvider, ModelEntry, settings
from app.llm.client import llm_client
from app.llm.usage import capture_llm_usage
from app.models.plan_models import LlmDayResponse
from app.services.llm_cost import MODEL_COST_RATES, cost_of
from app.services.meal_planner import SYSTEM_PROMPT, render_day_prompt
from evals.graders import SAFETY_CHECKS, Check, grade
from evals.meal_plan_cases import CASES, EvalCase

RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclass
class RunResult:
    model: str
    case_id: str
    repeat: int
    ok: bool
    error: str = ""
    seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_eur: float | None = None
    #: The provider refused for quota (HTTP 429) even after waiting. Not the
    #: model's fault, so left out of every rate in the scorecard.
    rate_limited: bool = False
    checks: list[Check] = field(default_factory=list)
    #: The generated day, for a human to read when a check looks wrong.
    output: dict[str, object] = field(default_factory=dict)


def label(entry: ModelEntry) -> str:
    """"provider/model": the LLM_MODELS spelling, so a scorecard column pastes into config."""
    return f"{entry.provider.value}/{entry.model}"


def parse_model(spec: str) -> ModelEntry:
    provider, _, model = spec.partition("/")
    try:
        return ModelEntry(provider=LLMProvider(provider), model=model.strip() or provider)
    except ValueError as exc:
        names = ", ".join(p.value for p in LLMProvider)
        raise argparse.ArgumentTypeError(f"{spec!r}: expected <provider>/<model>, provider one of {names}") from exc


def has_key(entry: ModelEntry) -> bool:
    keys = {
        LLMProvider.GEMINI: settings.gemini_api_key,
        LLMProvider.OPENAI: settings.openai_api_key,
        LLMProvider.DEEPSEEK: settings.deepseek_api_key,
    }
    return bool(keys[entry.provider])


@contextmanager
def pinned(entry: ModelEntry) -> Iterator[None]:
    """Route every call to this one model, with nothing to fall back to."""
    saved = settings.llm_models
    settings.llm_models = [entry]
    llm_client._demoted_until.clear()  # a demotion earned by another model must not leak in
    try:
        yield
    finally:
        settings.llm_models = saved


class Pacer:
    """Start at most `rpm` calls a minute: free-tier keys refuse bursts (429)."""

    def __init__(self, rpm: float | None) -> None:
        self.interval = 60 / rpm if rpm else 0.0
        self.next_start = 0.0
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            now = time.monotonic()
            if self.next_start > now:
                await asyncio.sleep(self.next_start - now)
            self.next_start = max(now, self.next_start) + self.interval


def _root(exc: BaseException) -> BaseException:
    while (inner := exc.__cause__ or exc.__context__) is not None:
        exc = inner
    return exc


_RETRY_HINT = re.compile(r"retryDelay\W+(\d+)")


def _rate_limit_delay(root: BaseException) -> float | None:
    """Seconds to wait if this is a quota refusal (HTTP 429), else None."""
    status = getattr(root, "code", None) or getattr(root, "status_code", None)
    if status != 429 and "429" not in str(root)[:40]:
        return None
    hint = _RETRY_HINT.search(str(root))
    return float(hint.group(1)) + 1 if hint else 30.0


async def run_one(
    entry: ModelEntry,
    case: EvalCase,
    repeat: int,
    *,
    mock: bool,
    pacer: Pacer | None = None,
    max_waits: int = 4,
) -> RunResult:
    result = RunResult(label(entry), case.id, repeat, ok=False)
    prompt = render_day_prompt(case.request, slot_layout=None, slot_portions=None)
    for attempt in range(max_waits + 1):
        if pacer:
            await pacer.wait()
        started = time.perf_counter()
        try:
            with capture_llm_usage() as calls:
                raw = await llm_client.chat_json(SYSTEM_PROMPT, prompt, LlmDayResponse, mock=mock)
            day = raw.to_planned_day()
            break
        except Exception as exc:  # any failure of the model under test is a result, not a crash
            root = _root(exc)
            delay = _rate_limit_delay(root)
            if delay is not None and attempt < max_waits:
                await asyncio.sleep(delay)
                continue
            # The chain wraps provider errors in a user-facing "AI unavailable";
            # the root cause (402 no balance, 429, a schema miss) is the useful part.
            result.error = f"{type(exc).__name__}: {exc}"[:200]
            if root is not exc:
                result.error += f" <- {type(root).__name__}: {root}"[:300]
            result.rate_limited = delay is not None
            result.seconds = time.perf_counter() - started
            return result
    result.seconds = time.perf_counter() - started
    result.ok = True
    result.prompt_tokens = sum(c.prompt_tokens for c in calls)
    result.completion_tokens = sum(c.completion_tokens for c in calls)
    if (entry.provider.value, entry.model) in MODEL_COST_RATES:
        result.cost_eur = sum(cost_of(c.prompt_tokens, c.total_tokens, c.provider, c.model) for c in calls)
    result.checks = grade(case.request, day.meals)
    result.output = day.model_dump(mode="json")
    return result


async def run_suite(
    entries: Sequence[ModelEntry],
    cases: Sequence[EvalCase],
    *,
    repeats: int,
    concurrency: int,
    mock: bool,
    rpm: float | None = None,
) -> list[RunResult]:
    results: list[RunResult] = []
    for entry in entries:
        if not mock and not has_key(entry):
            print(f"skip {label(entry)}: no API key for {entry.provider.value}")
            continue
        gate = asyncio.Semaphore(concurrency)
        pacer = Pacer(rpm)

        async def bounded(
            case: EvalCase,
            repeat: int,
            entry: ModelEntry = entry,
            gate: asyncio.Semaphore = gate,
            pacer: Pacer = pacer,
        ) -> RunResult:
            async with gate:
                return await run_one(entry, case, repeat, mock=mock, pacer=pacer)

        with pinned(entry):
            done = await asyncio.gather(*(bounded(c, r) for c in cases for r in range(1, repeats + 1)))
        results.extend(done)
        limited = sum(r.rate_limited for r in done)
        note = f", {limited} rate-limited (not graded)" if limited else ""
        print(f"done {label(entry)}: {sum(r.ok for r in done)}/{len(done)} answered{note}")
    return results


def _rate(passed: int, total: int) -> str:
    return f"{passed}/{total} ({100 * passed / total:.0f}%)" if total else "-"


def scorecard(results: Sequence[RunResult]) -> str:
    models = list(dict.fromkeys(r.model for r in results))
    check_names = list(dict.fromkeys(c.name for r in results for c in r.checks if c.score is None))
    rows: list[tuple[str, list[str]]] = []

    def row(name: str, cell: Callable[[list[RunResult]], str]) -> None:
        # A quota refusal says nothing about the model: it is in no rate.
        graded = [r for r in results if not r.rate_limited]
        rows.append((name, [cell([r for r in graded if r.model == m]) for m in models]))

    row("answered", lambda rs: _rate(sum(r.ok for r in rs), len(rs)))
    row("**safety clean** (allergens, infant, diet)", lambda rs: _rate(
        sum(all(c.passed for c in r.checks if c.name in SAFETY_CHECKS) for r in rs
            if r.ok and any(c.name in SAFETY_CHECKS for c in r.checks)),
        sum(1 for r in rs if r.ok and any(c.name in SAFETY_CHECKS for c in r.checks))))
    def pass_rate(name: str) -> Callable[[list[RunResult]], str]:
        return lambda rs: _rate(sum(c.passed for r in rs for c in r.checks if c.name == name),
                                sum(1 for r in rs for c in r.checks if c.name == name))

    for name in check_names:
        row(name, pass_rate(name))
    row("urgent fridge items used", lambda rs: (
        f"{100 * statistics.mean(s):.0f}%" if (s := [c.score for r in rs for c in r.checks
                                                     if c.score is not None]) else "-"))
    row("seconds p50 / p95", lambda rs: (
        f"{statistics.median(t):.1f} / {sorted(t)[max(0, round(0.95 * len(t)) - 1)]:.1f}"
        if (t := [r.seconds for r in rs if r.ok]) else "-"))
    row("tokens in / out (mean)", lambda rs: (
        f"{statistics.mean(r.prompt_tokens for r in ok):.0f} / {statistics.mean(r.completion_tokens for r in ok):.0f}"
        if (ok := [r for r in rs if r.ok]) else "-"))
    row("EUR per day (mean)", lambda rs: (
        f"{statistics.mean(c):.5f}" if (c := [r.cost_eur for r in rs if r.cost_eur is not None])
        else "no rate in llm_cost.py"))

    lines = ["| | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
    lines += [f"| {name} | " + " | ".join(cells) + " |" for name, cells in rows]
    failures = [f"- `{r.model}` **{r.case_id}** #{r.repeat} {c.name}: {c.detail}"
                for r in results for c in r.checks if c.name in SAFETY_CHECKS and not c.passed]
    errors = [f"- `{r.model}` **{r.case_id}** #{r.repeat}: {r.error}" for r in results
              if not r.ok and not r.rate_limited]
    limited = sorted({r.model for r in results if r.rate_limited})
    if limited:
        count = sum(r.rate_limited for r in results)
        lines += ["", f"_{count} run(s) refused for quota (429) and left out of every rate: {', '.join(limited)}._"]
    if failures:
        lines += ["", "### Safety failures", *failures]
    if errors:
        lines += ["", "### Errors", *errors]
    return "\n".join(lines)


def select(case_ids: Sequence[str], tags: Sequence[str]) -> list[EvalCase]:
    chosen = [c for c in CASES if (not case_ids or c.id in case_ids) and (not tags or set(tags) & set(c.tags))]
    unknown = set(case_ids) - {c.id for c in CASES}
    if unknown:
        raise SystemExit(f"unknown case id(s): {', '.join(sorted(unknown))}")
    return chosen


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="append", type=parse_model, default=[],
                        help="<provider>/<model>, repeatable (default: the configured LLM_MODELS chain)")
    parser.add_argument("--repeats", type=int, default=3, help="answers per case per model (default 3)")
    parser.add_argument("--case", action="append", default=[], help="only this case id (repeatable)")
    parser.add_argument("--tag", action="append", default=[], help="only cases with this tag (repeatable)")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel calls per model (default 4)")
    parser.add_argument("--rpm", type=float, default=None,
                        help="start at most this many calls a minute (free-tier keys: about 8)")
    parser.add_argument("--mock", action="store_true", help="use the mock LLM: tests the harness, not a model")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR, help="where results go (default evals/results)")
    parser.add_argument("--report", type=Path, nargs="+", metavar="RESULTS_JSON",
                        help="run nothing: merge these saved results into one scorecard")
    args = parser.parse_args(argv)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    args.out.mkdir(parents=True, exist_ok=True)
    if args.report:
        results = [r for path in args.report for r in load_results(path)]
    else:
        entries: list[ModelEntry] = args.model or list(settings.model_chain)
        cases = select(args.case, args.tag)
        print(f"{len(cases)} cases x {args.repeats} repeats x {len(entries)} models")
        results = asyncio.run(run_suite(entries, cases, repeats=args.repeats, concurrency=args.concurrency,
                                        mock=args.mock, rpm=args.rpm))
        (args.out / f"meal_plan-{stamp}.json").write_text(
            json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=1), encoding="utf-8")
    card = scorecard(results)
    print(card)
    (args.out / f"meal_plan-{stamp}.md").write_text(card + "\n", encoding="utf-8")
    print(f"\nscorecard: {args.out / f'meal_plan-{stamp}.md'}")


_RESULTS = TypeAdapter(list[RunResult])


def load_results(path: Path) -> list[RunResult]:
    """A results JSON written by a run, back into RunResults (checks included)."""
    return _RESULTS.validate_json(path.read_bytes())


if __name__ == "__main__":
    main()
