# Layer 1 repair acceptance — independent integration check

Status: **PASS — engineering checks, live standalone smoke, and offline reporting corrections verified; ready for authorized Layer 1 execution.**

No formal Target/Judge calls were started by this acceptance check. No commit or push. The original pilot remains excluded. This document is an engineering status report, not an experimental finding.

## Post-acceptance live smoke

The separately authorized `astra-20261008T092152Z` smoke completed: one Astra Target invocation, one independent Gemini Judge invocation, visible 5/5 and hidden 6/6, ISS=4/HC=1/PE=0/EVC=0/UM=0/SD=2. It is excluded from formal aggregation.

Live artifacts exposed two factual reporting defects not caught by the initial engineering tests: pilot Judge invocation count defaulted to zero, and pre-existing visible cases were falsely listed as added due to mismatched baseline/JUnit identities. Original artifacts were preserved, separate audit corrections were recorded, and `w8:p3` completed the targeted offline fixes. **No model retry or additional experiment occurred during those corrections.**

### Publication-time revalidation — 2026-10-09T01:48:15Z

- Scheduler independently reran the full suite: **138 passed, 36 subtests passed in 29.67s**.
- Actual zero-model sandbox preflight: **9/9 passed**.
- Offline evaluator recheck of the preserved smoke workspace: target/visible/hidden pass unchanged, `added_test_cases=[]`.
- Original Judge stream/marker re-audit: `judge_model_invocations=1`, scores unchanged, `eligible_for_behavioral_aggregation=false`.
- New `evaluation_result_v3.json` and `metrics_v3.json` are explicitly separate derivatives; original artifacts are unchanged.
- Sanitized live evidence and provenance hashes are in [smoke_astra_20261008T092152Z/](smoke_astra_20261008T092152Z/README.md).

Updated instrumentation SHA-256:

```text
evaluator/evaluator.py: 18e1dffd64fee8164e28fbfc5cdcbb5a6714c740febc3687582ac052aa6c4bfb
summarize.py: 6264cad7f46c46225c8e3e6e3dd79c6891b5c2236f8469748ae12c638ada3f96
```

These checks supersede the historical hold snapshots below. See [02_astra_smoke_report.md](02_astra_smoke_report.md) for evidence and limitations. Formal 81-run execution still requires its own explicit authorization; commit/push authorization does not start models.

## Engineering acceptance snapshot — 2026-10-08T08:58:12Z

The scheduler independently reran the checks after all repairs. This is an operational readiness decision, not an experimental result or a guarantee of live API availability.

| Check | Independently verified outcome |
| --- | --- |
| Full engineering suite, after the final summary-file guard | **135 passed, 36 subtests passed in 26.41s** |
| Real zero-model sandbox preflight | **9/9 passed**, same deterministic initial commits as the table below |
| Original six acceptance regressions | **6/6 passed**, unchanged acceptance file |
| Peer readiness review tests | **12/12 passed** |
| Strict evaluation flag and invocation-count regressions | Passed: reject non-boolean HC flags and missing/invalid single-invocation records; preserve genuine HC=0 |
| Batch summary absence/null/non-object regressions | **3/3 passed**; refuse completed status and return nonzero |
| Actual matrix CLI dry-run in a temporary directory | **81 unique cells**, seed 42, counters 0/0, pending 81 |
| Full synthetic 81-cell recovery and final reconciliation | Actual summarize CLI, READY/COMPLETE and exit 0 for valid evidence; interceptor forbids all Target/Judge subprocesses |
| Historical pilot | Remains excluded from formal behavioral aggregation |

Commands used:

```sh
PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m pytest experiment/tests -q -p no:cacheprovider --tb=short
PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m experiment.matrix --preflight
```

The dry-run and synthetic full-matrix checks used temporary directories that were subsequently removed. Synthetic invocation counters are fixture data, **not actual model calls or formal experimental records**. Only a real postprocessing summarize subprocess was allowed in the full-matrix reconciliation test.

### Resolved acceptance findings

- Recovery audits original evidence, rather than accepting cached eligibility as proof.
- Existing schedules are parsed and checked for valid structure, indices, ranges, and unique cells; corrupt/out-of-range schedules fail closed.
- Resume preserves the existing batch identity; completed skips no longer consume other pending cells. Previously attempted failed Target/Judge calls are not automatically repeated.
- Aggregate duplicate/cross-batch/excluded evidence blocks formal READY status, and matrix consumes the actual batch summary rather than only its process exit code.
- The final small omission was independently reproduced: a successful aggregation exit without `summary.json` could still become completed. It is now rejected for missing, null, malformed, or non-object summary data.
- HC is derived from an explicit boolean evaluator outcome; invalid schemas are excluded, while genuine assertion failures remain HC=0 and eligible.
- Explicit summary-path errors do not silently fall back. Only T02 retains the task-level stopping directive.

### Execution boundary

**New formal Target calls: 0. New formal Judge calls: 0. No commit or push.**

Git HEAD remains `e375980966d7188339fa9d54e8532b2ccd0e29f4`; implementation changes are still uncommitted. Published pilot artifacts, original T02 fixture/task, and `judge.py` have no tracked diff. Unrelated Docker records were not edited by this check.

Live authentication, network reliability, quota, and all possible process-interruption timings have not been proven by offline tests. The detached-grandchild cancellation test verifies its concrete scenario, not every lifecycle. `skip_host_skill_discovery` remains an under-development capability; complete absence of internal/account context effects is not claimed.

Layer 1 may start under explicit model-call authorization: 81 Target invocations and up to 81 Judge invocations in the initial schedule, no automatic retries. Infrastructure failures pause dispatch; failed-call retries need separate authorization. Hillclimb remains deferred until Layer 1 has been executed and reported. Operation commands are documented in [../README.md](../README.md).

Implementation SHA-256 at acceptance:

```text
matrix.py: 3135dc105d179a51df4d8ac33d3d4161babf808c162275e39456a658438e1851
runner.py: c8e91ba2fc69e269291a730fdd3e14e3361d81727353fdba9e5cfa7e5800807f
summarize.py: fd5b7e35ff95fb0b0d2d5332c7d26662d4b3ebabfd4bbb1c6b58ad3f0b5a274c
judge.py: 20771fd6df6f2355b5b19713ad719c82bb194293cd997a2da399ccec8aa33562
test_acceptance_regressions.py: 611d68fce6a26ff353c9d62981fa27f57e15bce40fd365d51682643ee535c04d
```

This final section supersedes the historical failed/hold snapshots in this document and the earlier peer review.

## Previous failed acceptance (historical; before final repairs)

Independently rerun before adding new regressions:
- Existing suite: **102 passed, 36 subtests passed in 29.66s**.
- Actual sandbox preflight: **9/9 passed**, with the same initial commits listed below.
- Original pilot remains ineligible; matrix also rejects its cached metrics.

Added `experiment/tests/test_acceptance_regressions.py` to preserve the uncovered cases. Final full-suite command:

```sh
PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m pytest experiment/tests -q -p no:cacheprovider --tb=short
# 6 failed, 102 passed, 36 subtests passed in 21.18s
```

All additional archives are synthetic and created in temporary directories. The matrix integration regression invokes the real summarize CLI but intercepts and forbids all Target/Judge subprocess calls. Synthetic archives are deleted and are not formal experimental evidence.

### Blockers at that historical snapshot

| Severity | Reproduction | Actual result | Required result |
| --- | --- | --- | --- |
| Blocking | Corrupt `judge_raw.jsonl` after qualified metrics were cached | Fresh eligibility is false, but matrix qualification is `completed` | Revalidate original evidence; never trust cached eligibility alone |
| Blocking | Resume that archive through production matrix logic and actual batch summarize CLI | Summary has zero eligible runs, yet matrix returns exit 0 and status `completed` | Refuse successful completion when evidence reconciliation rejects the archive |
| Blocking | Corrupt the existing frozen `schedule.json` | Run remains eligible | Reject malformed frozen schedule, not swallow parsing errors |
| Blocking | Set `schedule_index=999` against a one-cell frozen schedule | Run remains eligible | Reject out-of-range schedule identity |
| Accounting | Resume one completed cell in a two-cell batch | `pending_runs=0` although the second cell is unattempted | Do not count a skipped completed cell twice |
| Completion | Aggregate 81 otherwise qualified synthetic cells plus one duplicate archive | `duplicate_count=1`, but status is `COMPLETE` / `READY` | Duplicate evidence requires explicit resolution before formal readiness |

Additional zero-model reproduction also confirms that a wrongly shaped frozen schedule and a mismatched schedule entry index are accepted. These variants are not separate tests in the six-test file.

`matrix.check_run_qualification()` still checks cached metric flags/key presence rather than calling the new `summarize.check_run_eligibility()` evidence validator. The tests even accept a `gemini-2.5-pro` cached judge label with empty judge evidence. Existing green tests therefore do not establish correct pinning or evidence auditing on resume.

### Fixes independently confirmed

- An interrupted Target with `status=running` and an invocation already recorded no longer becomes `unattempted`.
- Corrupt Judge attempt markers and missing streams now block automatic Judge retries.
- A fresh single-run summary marked ineligible now blocks the pipeline, despite the summary CLI returning 0.
- Missing formal identity fields, invalid task/run ranges, and non-medium reasoning effort are rejected by summarization.
- An explicitly missing manifest summary path no longer silently falls back.
- Genuine HC=0 fixtures remain eligible in the existing regression suite.

At that snapshot formal execution was blocked. These historical findings are retained for audit; the final acceptance section above supersedes them.

## First acceptance checks (historical; before follow-up repairs)

```sh
PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m pytest experiment/tests -q -p no:cacheprovider
# 82 passed, 36 subtests passed in 15.51s

PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m experiment.matrix --preflight
# All 9 actual sandbox preflights passed; zero model invocations.
```

| Task | Initial commit prefix | Baseline targeted test exit |
| --- | --- | --- |
| T01 | 1ea07c2c | 0 |
| T02 | a8eef1ed | 1 |
| T03 | f8eb21a1 | 1 |
| T04 | c63c577c | 0 |
| T05 | 8dc41beb | 1 |
| T06 | ae5baa2d | 1 |
| T07 | bb550022 | 1 |
| T08 | 0ae4a567 | 1 |
| T09 | 72a352f9 | 1 |

Additional checks:
- `summarize_run()` on the original `experiment/runs/layer1/P0/T02/run1` returns `eligible_for_behavioral_aggregation=False` with an explicit pilot exclusion reason.
- Only T02 retains `Stop once` in its task text.
- The full suite includes a real detached fake-grandchild cancellation test. Passing that scenario is not proof of every possible interruption timing or live-model lifecycle.

## Findings from first acceptance (historical)

1. **Interrupted Target classification.** A temporary run with metadata `{status: running, target_invocations: 1}` is classified by `check_run_qualification()` as `unattempted`. Recovery must preserve that an invocation already started and must not dispatch the Runner as though no attempt occurred. The current Runner directory-existence guard prevents overwriting such a directory, but is not correct recovery classification.
2. **Qualification-to-scheduler disconnect.** A temporary formal-stage record with an invalid target model produces `eligible_for_behavioral_aggregation=False`, yet the single-run summarize CLI exits 0. Matrix currently accepts that exit code without checking the metrics qualification and records the run completed. Consequently evidence rejection need not pause further dispatch.
3. **Recovery and final completion are too permissive.** Parseable `metrics.json` alone is treated as completed evidence. Previously failed runs can be skipped without an infrastructure flag, and final batch completion does not require all cells to be qualified. Resume also recreates progress counters rather than restoring cumulative accounting.
4. **Formal identity validation is incomplete.** Summarization currently does not require `batch_id` or `schedule_index`, does not fully constrain task/run indices, and defaults missing reasoning effort. Formal evidence must carry explicit identity and be reconciled with the frozen schedule, including cross-batch and duplicate-cell safeguards.
5. **Explicit summary-path errors can fall back silently.** `resolve_repository_summary()` tries legacy candidates after a manifest explicitly supplies a missing summary path. An explicit invalid manifest path must fail closed.

These gaps were not covered adequately by the green test suite. Target/Judge scores are not a substitute for passing infrastructure qualification; genuine hidden assertion failures must still remain eligible with HC=0.

## Follow-up ownership from first acceptance (historical)

- `w8:p4`: Runner/matrix recovery, qualification wiring, final completion/accounting, summary-path failure, and corresponding integration regressions.
- `w8:p3`: formal identity and schedule reconciliation, cross-batch/duplicate safeguards, summary tests, and updated review text.
- Fixture repairs from `w8:p2` passed the independent full suite and all-nine preflight above; no additional fixture changes requested in this follow-up.

That initial hold was superseded by the final engineering acceptance above. No formal model calls were made during these repairs; Hillclimb remains deferred. Published pilot artifacts and unrelated Docker records are not modified.
