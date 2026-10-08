# Minimal Experiment Independent Read-Only Review

- **Status**: Pre-Execution Review Complete; pilot exposed additional environment/protocol issues (see §5)
- **Target Run Authorization**: Single T02/P0 Codex Run (`gpt-6-astra`, reasoning effort `medium`)
- **Evaluation Mechanism**: Deterministic Hidden Correctness (HC) + Blind Gemini 3.8 Flash (`gemini-3.8-flash-high`) Judge, Hillclimb Disabled
- **Reviewer Role**: Independent Read-Only Reviewer (Zero Model Calls, Zero Credential Probing, No Git Commits, No External Symlinks)

---

## 1. Executive Summary & Verdict

| Component | Status | Verdict | Summary |
| :--- | :--- | :--- | :--- |
| **`runner.py`** | **Reviewed** | **PASS** | Kernel filesystem sandbox profile verified; hard read denial probe passed on hidden tests, host AGENTS, project README, and sentinel; pure Python runtime isolation; zero model calls in preflight. |
| **`judge.py`** | **Reviewed** | **PASS** | Stream-json recursive tool-call rejection audit (`test_judge.py` 5/5 pass); condition-blind; path blinded; single execution marker. |
| **`fixtures/T02`** | **Reviewed** | **PASS** | `kvparser` baseline bug (NoneType in `clean_value`), manifest SHA256 hashes recorded, hidden tests physically separated. |
| **`evaluator`** | **Reviewed** | **PASS (Post-Run)** | Evaluator engine ready for post-run deterministic measurement (HC 6/6 evaluation, diff metrics, execution error separation). |

**Blocker Assessment**: **NO BLOCKERS.** The runner architecture satisfies all isolation, tool-disablement, and fresh-session mandates. The dispatcher may proceed with the authorized single target run (`--execute`).

---

## 2. In-Depth Runner Review (`experiment/runner.py`)

### 2.1 Filesystem Sandbox & Probe Verification
- **Seatbelt Profile Formulation**:
  ```python
  fs = {
      "/": "read",
      "/Users": "deny",
      "/private/tmp": "deny",
      "/private/var/folders": "deny",
      str(ROOT.parent): "deny",
      str(artifacts): "deny",
      str(dependency.resolve()): "read",
      str(repo.resolve()): "write"
  }
  ```
  Applies `permissions.astra_pilot.filesystem` table to Codex child tool processes via `-c default_permissions="astra_pilot"`.
- **Preflight Probe Evidence (`run_metadata.json`)**:
  - `write_ok`: `true` (can write to test repo)
  - `pytest`: `"9.1.1"` (runtime dependency imports correctly)
  - `denied`:
    - `/private/tmp/.../private-sentinel.txt`: **`true`**
    - `.../experiment/evaluator/hidden_tests/test_parser_hidden.py`: **`true`**
    - `.../experiment/README.md`: **`true`**
    - `~/.codex/AGENTS.md`: **`true`**
  - **Verdict**: Hard read isolation is actively kernel-enforced. The agent shell cannot access hidden tests, the host experiment root, or host global agent config files.

### 2.2 Pure-Python Runtime Isolation (`prepare_runtime`)
- Solves CPython venv realpath discovery issues under Seatbelt without widening host directory read access.
- Copies pinned `site-packages` into `workspace.parent / "runtime" / "site-packages"`.
- Generates pure shell launchers (`python`, `python3`, `pytest`) exporting explicit `PYTHONPATH` and delegating to the system interpreter.

### 2.3 Strict Command Construction & Disablement
- Command flags:
  - `--no-daemon`, `-a never`
  - `--ephemeral`, `--ignore-user-config`, `--ignore-rules`
  - `-c project_doc_max_bytes=0`, `-c model_reasoning_effort="medium"`, `-c web_search="disabled"`
  - `--enable skip_host_skill_discovery`
  - Explicitly disabled features (9 items): `shell_snapshot`, `plugins`, `hooks`, `apps`, `multi_agent`, `browser_use`, `browser_use_external`, `computer_use`, `memories`.
  - Pinned model: `-m gpt-6-astra`.

### 2.4 Diff Completeness & Error Separation
- `collect_diff()` captures both Git tracked modifications (`git diff`) and untracked newly created files (`git diff --no-index /dev/null <file>`).
- Infrastructure crashes (timeouts, exit != 0, missing turn) are flagged as `execution_error` in metadata and preserved separately from behavioral evaluations.
- Event stream saved to `tool_trace.jsonl`; stderr to `codex_stderr.txt`.

---

## 3. Evaluator & Judge Post-Run Readiness

1. **HC (Hidden Correctness)**:
   - Post-run evaluator will run `test_parser_hidden.py` (6 test cases).
   - Expected post-fix result for a correct implementation: 6/6 passed (HC = 1).
2. **Blind Judge (`judge.py`)**:
   - Reads blinded evidence (prompt, diff, evaluator test summary, tool trace, final response) without condition labels or target prompt.
   - Enforces stream-json tool-event rejection.
   - Single invocation marker prevents auto-retry.

---

## 4. Pre-Execution Review Conclusion
The reviewer reported no blockers based on the preflight evidence available at that time.
This was a review opinion, not proof that all CLI and test-collection paths worked.

## 5. Dispatcher Post-Pilot Addendum

The single authorized run completed. The pilot exposed gaps missed by the initial
review: pytest import success did not prove collection worked under the sandbox;
AGY native streams use `event` / `step_type`, not only `type`; print flags and
print-timeout units needed correction; xcrun created an incidental binary cache.

Corrections are now implemented and checked without a second Codex run:

- Preflight actually collects the pristine targeted test and requires its known
  AttributeError failure, not a permission/collection error.
- Recorded pytest collection environment settings and direct Git launchers avoid
  parent metadata failures and xcrun cache noise.
- Native AGY streams reject unknown/tool steps, wrong models and unsuccessful
  results. The saved successful judge stream was re-audited without another call.
- Binary changes remain recorded but are excluded from source LOC.
- Current tests: **29 passed**; corrected preflight passed with zero model calls.

Read denial is demonstrated at the tool/kernel boundary. Account-level preferences
and all internal CLI context effects are not proven absent; the experimental
skip-host-skill-discovery warning remains in the original trace.

This pilot is explicitly excluded from formal behavioral aggregation. See
`experiment/results/01_pilot_report.md` for results and limitations.
