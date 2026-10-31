# LLM evals

Offline scorecards for the models behind the app, so a model change is decided on numbers.
Each use of the model gets its own suite, because they fail differently. Only the meal-plan suite exists so far; receipt and fridge photos need a labelled set first.

## Run

```bash
docker compose run --rm backend python -m evals.run --model gemini/gemini-2.5-flash --model deepseek/deepseek-chat
```

| flag | |
|---|---|
| `--model provider/model` | repeatable, spelled as in `LLM_MODELS`; default is that chain |
| `--repeats N` | answers per case per model (default 3). Models answer differently each time, so one run of a case proves little |
| `--case ID`, `--tag TAG` | a subset (tags: `allergen`, `diet`, `infant`, `fridge`, `avoid`, `shape`, `language`, `combo`) |
| `--concurrency N` | parallel calls per model (default 4). Models run one after another |
| `--rpm N` | start at most N calls a minute per model. A free-tier key refuses bursts (429); about 8 keeps it quiet |
| `--mock` | the mock LLM: checks the harness, not a model |
| `--report FILE...` | run nothing; merge saved results JSONs into one scorecard (models run at different times, side by side) |

A 429 waits the provider's `retryDelay` and retries up to 4 times. A run still refused after that is marked rate-limited and left out of every rate: a quota limit is the key's, not the model's.

Output: a scorecard in the terminal. Every answer and every check are saved in `results/` (git-ignored), for reading what a model actually wrote.

## What is measured (`graders.py`)

- **Safety:** production's own allergen and infant screens, plus an eval-only diet check. Production leaves diets (vegan, halal, kosher, ...) to the prompt; this check is the only place diet compliance gets measured. A safety failure lists the ingredient, so a false positive is visible.
- **Contract:**
  - the requested number of meals;
  - `name_en` on every ingredient of a non-English plan (production rejects a plan without it);
  - the requested language;
  - stock-only plans using only fridge names;
  - the free-text avoid list.
- **Fridge use:** share of urgent items used. A measurement, not a gate.
- **Cost and speed:** seconds, tokens, and EUR where `app/services/llm_cost.py` has a rate for the model.

Each case is graded on the model's FIRST answer. Production rejects and regenerates a plan that fails its screen, which hides how often a model gets it wrong; that rate is the number being compared.

Not measured here: whether the food is good. That needs people; a blind A/B rating page is the next step.

## Rules

- **Cases are synthetic, always.** Suites go to whichever provider is being evaluated, and the privacy policy names only Google for user data. Never paste a real user's request, plan or receipt into a suite.
- Add a case for every failure seen in the wild, rewritten without user data.
- A model goes to users only after it passes this suite: 100% safety clean, and no worse on the rest than the model it replaces.
