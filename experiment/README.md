# Astra engineering-behavior experiment: minimal pilot

Scope: **T02 / P0 / one independent target run**, followed by a separate blind
Gemini judge. No hillclimb, no candidate generator, no expanded task suite.
A single pilot checks the measurement pipeline; it cannot establish a stable
behavioral preference or draw conclusions about training methods.

## Roles and versions

- Target: Codex CLI (`gpt-6-astra`, reasoning effort `medium`). The model is
  explicitly pinned from the user's local non-sensitive model configuration.
- Judge: independent `agy --print`, model `gemini-3.8-flash-high`.
- Python 3.12; pytest version pinned in `requirements.txt`.
- Each target invocation uses a fresh Git repository and ephemeral conversation.
- Restrictive filesystem permissions must pass a zero-model-call probe before
  any target invocation. Workspace-write alone is not read isolation.
- Target receives only P0 plus task text and the small ordinary project.
- Judge input excludes condition labels, target prompt, hidden-test code,
  run metadata, history and other tasks. Its tool calls invalidate its verdict.

## Setup

```sh
uv venv --python python3.12 experiment/.venv
uv pip install --python experiment/.venv/bin/python -r experiment/requirements.txt
experiment/.venv/bin/python -m pytest experiment/tests -q -p no:cacheprovider
```

Test/self-check invocations are not target-model runs. They must not execute
Codex or Gemini. A target run and a judge call require explicit execution flags.
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

- Initial fixture tests include a known failing null case. Hidden tests must
  also fail before a real fix, then pass after the smallest reference fix.
- Extra command count is not EVC. Small diffs and fewer tests are not a reward.
- Infrastructure errors (timeouts, sandbox failures, CLI errors, missing trace)
  are recorded separately from behavior failures; do not turn them into scores.
- Runtime packages and normal CLI infrastructure remain necessary dependencies,
  not task context. Effective sandbox configuration is retained in the run record.
- Use the resulting single-case report only as a pilot, not the 81-run study.

## Commands (no automatic model retries)

Free preflight, including real baseline test collection and clean Git status:

```sh
experiment/.venv/bin/python -B experiment/runner.py --dry-run
```

Only after a **new** target-run authorization (the existing `run1` is complete):

```sh
RUN="experiment/runs/layer1/P0/T02/<new-authorized-run>"
experiment/.venv/bin/python -B experiment/runner.py --execute --run-dir "$RUN"
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
actual execution result. Current tests: **29 passed**. The only completed pilot
is explicitly excluded from formal behavior aggregation due to environment interference.
