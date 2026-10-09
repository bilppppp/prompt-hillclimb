# Layer 1 Readiness Review — Historical Independent Snapshot

Publication note: this Phase 2 snapshot is retained for audit, not current release status. The later fixes, 138 passing tests and 36 subtests, 9/9 sandbox preflights, and reviewed standalone live smoke are documented in [the latest acceptance record](../results/00_layer1_repair_acceptance.md). Formal 81-run execution still requires separate authorization.

**Overall Status at This Snapshot: PROVISIONAL / ON HOLD (Formal Execution Blocked)**
**Snapshot Timestamp**: `2026-10-08T16:15:00+08:00`
**Review Phase**: Phase 2 Independent Re-check Snapshot (Follow-up to Phase 1 Audit)

> [!CAUTION]
> **Formal matrix execution (81 runs) remains on HOLD.**
> Passing zero-model preflights (9/9 sandbox passed), synthetic mock runs, or partial regression suites does **NOT** indicate that the formal experiment has executed or that whole-system readiness is granted.
> Significant progress has been achieved: targeted patches from `w8:p3` and `w8:p4` have resolved the 7 original blocking defects, resulting in `test_readiness_review.py` (12/12) and `test_acceptance_regressions.py` (6/6) passing.
> However, overall formal matrix execution is **NOT yet accepted** because:
> 1. `w8:p4` is still actively aligning legacy mocks across integration tests;
> 2. `w8:p3` has been returned to resolve two specific validation omissions (`hidden_suite_passed=7` integer coercion and unvalidated `target_invocations` defaulting to 1);
> 3. Whole-system end-to-end acceptance must await clean completion of both worker tracks without regression.

---

## 1. Timeline & Snapshot Evolution

```
[Phase 1 Audit (15:39)]  ──>  [Targeted Repairs (15:43-16:11)]  ──>  [Phase 2 Snapshot (16:15)]
• 7 Defect Tests FAILED       • w8:p3 patched schedule/dups          • test_readiness_review: 12/12 PASSED
• 6 Acceptance FAILED         • w8:p4 patched matrix qual/resume     • test_acceptance_regressions: 6/6 PASSED
• Overall: BLOCKED            • Repaired defects verified            • 2 p3 omissions pending in test_summarize
                                                                     • p4 legacy mock alignment ongoing
                                                                     • Overall: PROVISIONAL / ON HOLD
```

### 1.1 Phase 1 vs. Phase 2 Defect Ledger

The historical findings from the Phase 1 audit are preserved below for lineage, alongside their Phase 2 re-test status:

| Defect ID | Component | Owner | Historical Phase 1 Finding | Phase 2 Snapshot Status | Re-check Verification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **DEF-01** | `matrix.py` | `w8:p4` | Matrix qualification blindly trusted cached `metrics.json` over corrupt `judge_raw.jsonl` | **PATCHED** | Calls `summarize.check_run_eligibility()`; corrupt streams reject `completed` status |
| **DEF-02** | `matrix.py` / `summarize.py` | `w8:p4` / `w8:p3` | Batch summary rejection (0 eligible runs) returned exit 0 and reported `completed` | **PATCHED** | Matrix verifies `summary.json`; non-zero exit and non-completed status enforced |
| **DEF-03** | `summarize.py` | `w8:p3` | Gate 9 swallowed `JSONDecodeError` on corrupt frozen `schedule.json` | **PATCHED** | Malformed `schedule.json` fails closed with explicit `exclusion_reason` |
| **DEF-04** | `summarize.py` | `w8:p3` | Out-of-bounds `schedule_index` (e.g. 999) bypassed schedule check without exclusion | **PATCHED** | Bounds check `1 <= schedule_index <= len(sched_items)` fails closed |
| **DEF-05** | `matrix.py` | `w8:p4` | Resuming 1 completed cell in 2-cell batch double-counted skipped runs, zeroing pending | **PATCHED** | Status reconciliation aligns completed vs skipped runs; pending count preserved |
| **DEF-06** | `summarize.py` | `w8:p3` | Duplicate run archives in batch failed to invalidate `COMPLETE` / `READY` status | **PATCHED** | `aggregate_batch()` explicitly requires `duplicate_count == 0` for `READY` |
| **DEF-07** | `matrix.py` | `w8:p4` | Resuming with `--batch-dir` without `--batch-id` generated new timestamp and wiped progress | **PATCHED** | Retains existing `batch_id` from `progress.json` during resume |

---

## 2. Re-Audit of Positive Safety Mechanisms (Tightened Scope)

In the initial review, certain positive mechanisms were cited without sufficiently qualifying the boundaries of their unit test assertions. This section tightens those claims and clearly distinguishes shallow unit assertions from empirical integration evidence:

### 2.1 CLI Wiring (`test_cli_wiring_command_signatures_match`)
- **What the unit test proves**: Validates only that the Python entry points (`main`) exist in `runner.py`, `evaluator.py`, `judge.py`, `summarize.py`, and `matrix.py`.
- **What it does NOT prove**: It does **not** prove that all CLI argument parser flags, type converters, or subprocess shell invocations match without error during real execution.
- **Empirical Evidence**: Actual CLI parameter compatibility is substantiated separately by `experiment/tests/test_matrix_integration.py` and the zero-model sandbox preflight (`python -m experiment.matrix --preflight`), which exercises real argument parsing across all 9 fixture tasks.

### 2.2 Blind Judge Input Sanitization (`test_blind_judge_sanitizes_paths_and_omits_condition`)
- **What the unit test proves**: Validates that `build_prompt()` combined with a test-level `mock_blind()` helper correctly formats the schema prompt, injects `<private-path>`, and excludes condition tags.
- **What it does NOT prove**: It does **not** prove that `judge.main()` at runtime will catch every conceivable leaking path in arbitrary trace logs or command outputs under live execution.
- **Empirical Evidence**: Runtime blindness depends on `judge.py`'s internal `blind()` replacement function and the structural exclusion of condition parameters from the Judge CLI interface.

### 2.3 Process Tree Cancellation (`test_process_tree_cancellation_traverses_exact_hierarchy`)
- **What the unit test proves**: Validates only that `get_all_descendant_pids({my_pid})` returns a `set` and does not include `my_pid`. This is a shallow smoke check and does **not** prove that detached grandchildren are killed or that unrelated processes are spared.
- **Empirical Integration Evidence**: The actual empirical proof of detached process termination is established by [`test_matrix_integration.py:test_fake_grandchild_setsid_cleaned_up_without_remnants`](file:///Users/gravity/Desktop/AI/prompt-hillclimb/experiment/tests/test_matrix_integration.py#L51). In that test:
  1. A parent process spawns a child that spawns a detached grandchild process with `start_new_session=True` (`setsid`);
  2. The grandchild PID is recorded into `target.pid`;
  3. `get_all_descendant_pids()` and `kill_proc_tree()` are executed;
  4. The test explicitly verifies that the detached grandchild is terminated (`os.kill(grandchild_pid, 0)` raises `ProcessLookupError`) without leaving zombie or orphan processes.

### 2.4 True Assert HC=0 vs. Infrastructure Evaluation Error: CONFIRMED
- **Evaluator Classification**:
  - Exit code 0: All tests pass.
  - Exit code 1: Assertion failure (`assertion_failure=True`, `is_evaluation_error=False`).
  - Exit codes 2–5, 124, 255: Infrastructure error (`is_evaluation_error=True`).
- **Summarization Invariant**:
  - A genuine test assertion failure results in `HC=0` and `has_evaluation_error=False`. The run remains **eligible for behavioral aggregation**.
  - Infrastructure crashes set `HC=None` and disqualify the run from behavioral metrics.

---

## 3. Pending Omissions Returned to `w8:p3`

During follow-up audit of `experiment/summarize.py`, two specific validation omissions were identified and returned to `w8:p3` for remediation. Both currently fail in `experiment/tests/test_summarize.py`:

### 3.1 Omission A: `hidden_suite_passed = 7` Integer Coercion to `HC = 1`
- **Location**: `experiment/summarize.py:408-414`
- **Mechanism**:
  ```python
  if "hidden_suite_passed" not in eval_summary or not isinstance(eval_summary["hidden_suite_passed"], (bool, int)):
      result["exclusion_reason"] = f"Evaluation summary in {eval_file} missing boolean 'hidden_suite_passed'"
      return result

  result["HC"] = int(bool(eval_summary["hidden_suite_passed"]))
  ```
- **Vulnerability**: Because Python `bool` inherits from `int`, `isinstance(7, (bool, int))` is `True`. Furthermore, `bool(7)` evaluates to `True`, which `int(True)` converts to `1`. Consequently, an arbitrary integer count (e.g. `7` tests passed) is coerced into a suite-level pass (`HC=1`), violating the strict boolean schema requirement.
- **Failing Regression**: `TestSummarize.test_evaluation_hidden_suite_passed_requires_exact_bool` fails with `AssertionError: True is not false`.
- **Required Fix**: Enforce exact boolean type: `if type(eval_summary.get("hidden_suite_passed")) is not bool: ...`

### 3.2 Omission B: Missing `target_invocations` Silently Defaults to 1 and Remains Eligible
- **Location**: `experiment/summarize.py:100`
- **Mechanism**:
  ```python
  "target_invocations": metadata.get("target_invocations", 1),
  ```
- **Vulnerability**: If `run_metadata.json` lacks an explicit `target_invocations` entry, `summarize.py` silently guesses `1`. Furthermore, Gate validation in `summarize_run()` does not verify that `target_invocations` was explicitly provided, is an integer, and equals exactly `1` for formal completed runs. Runs with missing invocation counters erroneously remain eligible for formal aggregation.
- **Failing Regression**: `TestSummarize.test_formal_completed_run_requires_exact_target_invocations_one` fails with `AssertionError: True is not false`.
- **Required Fix**: Add a dedicated validation Gate in `summarize_run()` requiring `target_invocations` in `metadata`, verifying `type(inv) is int and inv == 1`, and failing closed if missing or invalid.

---

## 4. Current Test Suite Status (Read-Only Verification)

```sh
# 1. Independent Readiness Review Suite (12 tests)
PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m pytest experiment/tests/test_readiness_review.py -q -p no:cacheprovider
# Output: 12 passed in 0.28s

# 2. Independent Acceptance Regressions (6 tests)
PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m pytest experiment/tests/test_acceptance_regressions.py -q -p no:cacheprovider
# Output: 6 passed in 0.19s

# 3. Sandbox Preflight (Zero Model Invocations)
PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m experiment.matrix --preflight
# Output: ALL 9 PREFLIGHT CHECKS PASSED (Zero Model Invocations)

# 4. Summarize Unit Suite (Reflecting p3's pending items)
PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m pytest experiment/tests/test_summarize.py -q -p no:cacheprovider
# Output: 2 failed, 37 passed in 0.38s (Failing on the 2 known p3 omissions above)
```

---

## 5. Re-Review & Release Criteria

Formal 81-run matrix execution remains on hold until the following final conditions are satisfied:
1. **`w8:p3` completes the 2 omissions**: `test_summarize.py` passes 39/39 cleanly (including strict `hidden_suite_passed` boolean enforcement and explicit `target_invocations == 1` validation).
2. **`w8:p4` completes legacy mock alignment**: All matrix and integration tests pass without mock regressions.
3. **Full regression suite passes cleanly**:
   ```sh
   PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
     -m pytest experiment/tests -q -p no:cacheprovider
   ```
4. **Independent Final Sign-off**: Independent verification confirms that no further blocking defects remain prior to dispatching real model calls.
