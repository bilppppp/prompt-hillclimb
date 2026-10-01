# Smoke Test v2 Summary Report

- **Role**: agy3 (独立测试执行者)
- **Base Git HEAD**: `2d3ce17e01833677351226d99eacb189e2bdc746`
- **Dirty Product Files (5 files)**:
  - `README.md`
  - `SKILL.md`
  - `hillclimb.py`
  - `install.md`
  - `tests/test_core.py`
- **Associated Run Directory**: `.hillclimb/20261001-122743`

## Precise Commands & Exit Codes

1. **Unittest**:
   `python3 -m unittest -q > .hillclimb/codex-root-smoke-v2-20261001-122717/unittest.log 2>&1`
   - Exit code: `0` (57 tests passed)
2. **Dry-Run Preflight**:
   `python3 hillclimb.py --target .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/target-prompt.md --eval .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/evals.jsonl --runner pi --rounds 1 --limit 1 --repeats 1 --dry-run > .hillclimb/codex-root-smoke-v2-20261001-122717/dryrun.log 2>&1`
   - Exit code: `0` (Budget upper bound: 16)
3. **Real Smoke Run**:
   `python3 -u hillclimb.py --target .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/target-prompt.md --eval .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/evals.jsonl --runner pi --rounds 1 --limit 1 --repeats 1 > .hillclimb/codex-root-smoke-v2-20261001-122717/smoke.log 2>&1`
   - Return code: `0`

## Results & Path Breakdown

- **Baseline**: Train: 100.0%, Val: 100.0%
- **Preflight 3 Facts**:
  1. Noise delta: 0.0 (Warning: False)
  2. Headroom warning: True (train 100.0 & val 100.0 >= 95%)
  3. Grader disagreement: 0/3 (0.0%, Warning: False)
  - Preflight status: PASSED
- **Rounds**: Configured: 1, Executed: 0, Stop reason: `NO_TRAIN_FAILURE_SIGNAL`
- **Final Blind Comparison**: Original == Best (shared); Original: 66.7%, Best: 66.7%, Delta: 0.0
- **Invocations (Actual Path Calculation)**: **9 calls** (Baseline: 4, Preflight: 3, Rounds: 0, Final: 2) vs Budget Upper Bound 16
- **Candidate / Stall / Middleware Artifacts**:
  - Candidate files: None (no candidate created due to early stop before Round 1)
  - Stall analysis files: None (did not stall)
  - New middleware: None (no ungenerated middleware fabricated)
- **Snapshot Byte-by-Byte Verification**:
  - Target prompt (`/Users/gravity/.codex/AGENTS.md`) == `inputs/target-prompt.md` (Identical: True)
  - Evals (`.hillclimb/codex-root-smoke-inputs/evals.jsonl`) == `inputs/evals.jsonl` (Identical: True)
  - All 5 tested source files + `tests/__init__.py` == `tested-source/` (Identical: True)
