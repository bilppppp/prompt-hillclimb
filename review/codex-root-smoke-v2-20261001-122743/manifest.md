# Manifest: Codex Root Smoke v2 Test Run

- **Timestamp**: 20261001-122717
- **Role**: agy3 (Independent Test Executor)
- **Local Git HEAD**: `2d3ce17e01833677351226d99eacb189e2bdc746`
- **Dirty Product Files (5 files)**:
  - `README.md`
  - `SKILL.md`
  - `hillclimb.py`
  - `install.md`
  - `tests/test_core.py`
- **Associated Hillclimb Run Directory**: `.hillclimb/20261001-122743`

---

## 1. Exact Commands Executed

### 1.1 Unittest
```bash
python3 -m unittest -q > .hillclimb/codex-root-smoke-v2-20261001-122717/unittest.log 2>&1
```
- **Exit Code**: 0 (57 tests passed)

### 1.2 Dry-Run Preflight
```bash
python3 hillclimb.py \
  --target .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/target-prompt.md \
  --eval .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/evals.jsonl \
  --runner pi \
  --rounds 1 \
  --limit 1 \
  --repeats 1 \
  --dry-run > .hillclimb/codex-root-smoke-v2-20261001-122717/dryrun.log 2>&1
```
- **Exit Code**: 0
- **Call Budget Estimate**: up to 16 calls

### 1.3 Real Smoke Execution
```bash
python3 -u hillclimb.py \
  --target .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/target-prompt.md \
  --eval .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/evals.jsonl \
  --runner pi \
  --rounds 1 \
  --limit 1 \
  --repeats 1 > .hillclimb/codex-root-smoke-v2-20261001-122717/smoke.log 2>&1
```
- **Return Code**: 0

---

## 2. Byte-by-Byte Verification

All snapshots have been verified byte-for-byte against their originals:
- Target prompt: `/Users/gravity/.codex/AGENTS.md` == `.hillclimb/codex-root-smoke-v2-20261001-122717/inputs/target-prompt.md` (SHA256: `a7352eacf14396cda4e31df05ca23ba880bf4c8f8c686946d5bea38db2f9a0d4`, Identical: True)
- Evals dataset: `.hillclimb/codex-root-smoke-inputs/evals.jsonl` == `.hillclimb/codex-root-smoke-v2-20261001-122717/inputs/evals.jsonl` (SHA256: `5edea036fb603b68451179d4ccba4b8455af3bd8f2e493086e8180bdd200572a`, Identical: True)
- Source files in `tested-source/`:
  - `hillclimb.py` == `tested-source/hillclimb.py` (Identical: True)
  - `README.md` == `tested-source/README.md` (Identical: True)
  - `SKILL.md` == `tested-source/SKILL.md` (Identical: True)
  - `install.md` == `tested-source/install.md` (Identical: True)
  - `tests/test_core.py` == `tested-source/tests/test_core.py` (Identical: True)
  - `tests/__init__.py` == `tested-source/tests/__init__.py` (Identical: True)

---

## 3. Execution Results Summary

- **Execution Backend**: `pi` CLI (v0.99.1)
- **Baseline**:
  - Train: 100.0%
  - Val: 100.0%
- **Preflight Facts**:
  1. **Noise**: Observed val variation: 0.0 (delta: 0.0, warning: false)
  2. **Headroom**: Headroom warning: True (`baseline train 100.0 and val 100.0 both >= 95%`)
  3. **Grader Stability**: Grader disagreement: 0/3 (0.0%, warning: false)
  - Status: PASSED
- **Rounds**:
  - Rounds configured: 1
  - Rounds executed: 0
  - Stop reason: `NO_TRAIN_FAILURE_SIGNAL` (Baseline train had 100% pass rate, no failure cases to drive optimizer)
- **Candidate & Classification Files**:
  - Candidate files: None (no candidate prompt generated due to early stop before Round 1)
  - Stall classification files: None (no stall triggered)
- **Final Blind Comparison**:
  - Status: Completed (Original == Best)
  - Original: 66.7%
  - Best: 66.7% (shared with Original)
  - Delta: 0.0 (no accepted prompt change)
- **Invocations Count**:
  - Upper-bound estimate budget: 16 calls
  - Actual executed invocations: **9 calls** (calculated from exact execution trace; not guessed):
    - Baseline: 4 calls (1 train target + 1 train grader + 1 val target + 1 val grader)
    - Preflight: 3 calls (1 repeat-val target + 1 repeat-val grader + 1 train grader stability check on 3 criteria)
    - Rounds: 0 calls (stopped before Round 1; optimizer not called)
    - Final: 2 calls (shared run: 1 final target + 1 final grader)
