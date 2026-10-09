# Astra engineering-behavior experiment

Layer 1 scope: **9 Core tasks × P0/P1/P2 × 3 independent repetitions = 81 runs**,
each followed by a separate blind Gemini judge. No Hillclimb or Holdout execution.
The original **T02 / P0 / single-run pilot** is retained as historical pipeline
evidence and excluded from formal aggregation. Neither a pilot nor infrastructure
checks establish a stable behavioral preference or training-method causation.

## Roles and versions

- Target: Codex CLI (`gpt-6-astra`, reasoning effort `medium`). The model is
  explicitly pinned from the user's local non-sensitive model configuration.
- Judge: independent `agy --print`, model `gemini-3.8-flash-high`.
- Python 3.12; pytest version pinned in `requirements.txt`.
- Each target invocation uses a fresh Git repository and ephemeral conversation.
- Restrictive filesystem permissions must pass a zero-model-call probe before
  any target invocation. Workspace-write alone is not read isolation.
- Target receives only its assigned condition prompt, task text, and ordinary project.
  Hidden tests, private summaries, other fixtures, history, and run artifacts are excluded.
- Judge input excludes condition labels, target prompt, hidden-test code,
  run metadata, history and other tasks. Its tool calls invalidate its verdict.

## Setup

```sh
uv venv --python python3.12 experiment/.venv
uv pip install --python experiment/.venv/bin/python -r experiment/requirements.txt
experiment/.venv/bin/python -m pytest experiment/tests -q -p no:cacheprovider
```

Test/self-check invocations are not target-model runs. Local `codex sandbox`
probes are permitted, but Target and Judge model calls are forbidden in self-checks.
A target run and a judge call require explicit execution flags.
There is no automatic retry of failed model invocations.

## Evidence

The runner stores the original prompt, final response, full JSONL event trace,
transcript, tracked and untracked diff, changed files and execution metadata
outside the target workspace. Evaluation runs only after the agent exits.
Evaluator tests are clearly separate from tests actually performed by the agent.
Temporary target workspace paths are recorded so evidence can be inspected.

Deterministic measurements record facts: visible/hidden test results, file and
line changes, test edits, and added mechanism candidates. They do not decide
whether a new test or mechanism was necessary. The blind judge assesses ISS,
PE, EVC, UM and SD with evidence, plus under-validation and uncertainty. HC is
computed from hidden tests, not guessed by the judge.

## Boundaries

- T02 includes a known failing null case. Every fixture has explicit baseline
  exit/count expectations and a reference-fix check; T01/T04 targeted baselines
  legitimately pass. Only T02 carries an explicit stopping instruction.
- Extra command count is not EVC. Small diffs and fewer tests are not a reward.
- Infrastructure errors (timeouts, sandbox failures, CLI errors, missing trace)
  are recorded separately from behavior failures; do not turn them into scores.
- Runtime packages and normal CLI infrastructure remain necessary dependencies,
  not task context. Effective sandbox configuration is retained in the run record.
- Use the resulting single-case report only as a pilot, not the 81-run study.

## Pilot commands (diagnostic only; no automatic model retries)

Free preflight, including real baseline test collection and clean Git status:

```sh
experiment/.venv/bin/python -B experiment/runner.py --dry-run
```

Only after a **new** target-run authorization (the existing `run1` is complete):

```sh
RUN="experiment/runs/layer1/P0/T02/<new-authorized-run>"
experiment/.venv/bin/python -B experiment/runner.py --execute --experiment-stage pilot --run-dir "$RUN"
# WORKSPACE is the path printed by the runner / saved in run_metadata.json.
experiment/.venv/bin/python -B -m experiment.evaluator \
  --repo "$WORKSPACE" --artifact "$RUN/evaluation_result.json"
experiment/.venv/bin/python -B experiment/judge.py --execute --run-dir "$RUN" \
  --task experiment/fixtures/core/T02/task.md \
  --summary experiment/evaluator/repository_summary.md \
  --test-results "$RUN/evaluation_result.json" --workspace "$WORKSPACE"
experiment/.venv/bin/python -B -m experiment.summarize --run-dir "$RUN"
```

The pilot exposed pytest ancestor-metadata collection errors and xcrun Git cache
noise. The current runner preflights **actual baseline test collection**, scopes
pytest collection through recorded environment settings, and invokes Git without
its xcrun shim. These fixes were checked without a second target invocation.
Binary artifacts are retained but do not count as source LOC. A condition-blind
native AGY stream audit rejects tool/unknown steps, wrong models and failed results.

See [review/minimal_review.md](review/minimal_review.md), [results/01_pilot_report.md](results/01_pilot_report.md),
and the published evidence archive in [results/pilot_run1/](results/pilot_run1/README.md) (with full unredacted logs preserved locally in git-ignored `runs/layer1/P0/T02/run1/`) for the review and
actual execution result. That published pilot snapshot had **29 passing tests**.
The only completed pilot is excluded from formal behavior aggregation due to
environment interference. See [the current acceptance record](results/00_layer1_repair_acceptance.md)
for the latest engineering checks and release gate.

## Layer 1 matrix operation

Run from the repository root. The first two commands are zero-model checks:

```sh
PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m pytest experiment/tests -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m experiment.matrix --preflight
```

Prepare a fresh, explicitly named batch with no model calls:

```sh
BATCH="<new-layer1-batch-id>"
experiment/.venv/bin/python -B -m experiment.matrix \
  --batch-id "$BATCH" --dry-run --seed 42
```

**Only after explicit authorization for formal model calls**, execute that batch:

```sh
experiment/.venv/bin/python -B -m experiment.matrix \
  --batch-id "$BATCH" --execute --workers 3 --judge-concurrency 1 --timeout 300
```

Initial schedule budget: 81 Target CLI invocations and at most 81 Judge CLI
invocations, with no automatic retries. An agent invocation can contain multiple
backend requests/tool turns; these counts are not token or API-request budgets. Infrastructure errors pause dispatch and return
nonzero; genuine hidden assertion failures remain eligible HC=0 observations.

Resume the same frozen batch, preserving its identity and evidence:

```sh
experiment/.venv/bin/python -B -m experiment.matrix \
  --batch-dir "experiment/runs/layer1/$BATCH" --execute --resume \
  --workers 3 --judge-concurrency 1 --timeout 300
```

Resume skips completed cells, permits unfinished postprocessing after a successful
Target, and refuses to repeat previously attempted failed Target/Judge calls.
Do not delete attempt markers or overwrite a schedule to force a retry. Any retry
requires separate authorization and preservation of the original failed evidence.

Each batch retains `schedule.json`, `progress.json`, append-only `status.jsonl`,
per-run evidence under `<condition>/<task>/runN/`, and final reports under `results/`.
Scores are independent ISS/HC/PE/EVC/UM/SD and under-validation observations, not
an aggregate reward for fewer tests, files, or lines. Report Layer 1 before any
Hillclimb. Successful zero-model checks do not prove live authentication, quota,
or network reliability.
