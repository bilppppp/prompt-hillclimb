---
name: prompt-hillclimb
description: Evaluate and iteratively improve a reusable text prompt using train, validation, and final evaluation cases.
---

# Prompt Hillclimb Skill

Use this skill when you need to evaluate and systematically optimize a reusable text-in / text-out prompt based on empirical evaluation data rather than manual guessing.

## When to Use
- Optimizing long-lived instructional prompts (tutor, analyst, assistant, writing prompts).
- Validating whether a proposed prompt revision genuinely improves performance across diverse cases.
- Measuring prompt baseline stability and evaluation noise before rolling out changes.
- Comparing empirical before/after metrics on a held-out final evaluation split.

## When NOT to Use
- Tasks requiring multi-file repository edits, code execution, or tool use evaluation.
- Evaluating system slot / AGENTS.md injection or runtime plugin triggers.
- Prompt optimization without pre-existing or human-curated eval cases (do not hallucinate unverified evals).

## Step-by-Step Workflow

> **Path Resolution Note**: When executing this skill from an arbitrary user working directory (`cwd`), invoke `hillclimb.py` using its absolute path within this skill directory (e.g., `python3 /Users/gravity/Desktop/AI/prompt-hillclimb/hillclimb.py ...`). The resulting `.hillclimb/` output directory will be created inside the caller's active working directory.

1. **Verify Inputs**:
   - Ensure target prompt file exists (e.g., `prompt.md`).
   - Ensure an evaluation dataset exists in JSONL format with `train`, `val`, and `final` splits.
   - If evaluation cases do not exist, work with the user to curate realistic cases first. Never invent arbitrary evals and declare an improvement without validation.

2. **Run Dry-Run**:
   Check configuration, executable discovery, split distribution, and call estimates:
   ```bash
   python3 /Users/gravity/Desktop/AI/prompt-hillclimb/hillclimb.py \
     --target path/to/prompt.md \
     --eval path/to/evals.jsonl \
     --runner codex \
     --rounds 1 \
     --dry-run
   ```

3. **Check Baseline Noise (Recommended)**:
   For sensitive tasks, assess natural model variance:
   ```bash
   python3 /Users/gravity/Desktop/AI/prompt-hillclimb/hillclimb.py \
     --target path/to/prompt.md \
     --eval path/to/evals.jsonl \
     --runner codex \
     --measure-noise
   ```
   It is recommended to set `--min-gain` equal to or greater than the observed validation delta as an empirical heuristic to reduce accepting random fluctuations (note that this is a practical recommendation rather than a statistical guarantee against stochastic variance).

4. **Execute Optimization**:
   ```bash
   python3 /Users/gravity/Desktop/AI/prompt-hillclimb/hillclimb.py \
     --target path/to/prompt.md \
     --eval path/to/evals.jsonl \
     --runner codex \
     --rounds 3 \
     --min-gain 3.0
   ```

5. **Review and Report Results**:
   - Inspect `.hillclimb/<timestamp>/summary.md`.
   - Report baseline performance (train/val), per-round candidate changes and KEEP / REVERT decisions, and final held-out score to the user.
   - Inspect `.hillclimb/<timestamp>/best-prompt.md`.
   - **Important**: Do not automatically overwrite the user's original prompt file. Present the best prompt and summary for user review.

## Quota & Cost Notice
> [!WARNING]
> Running `hillclimb.py` launches nested `codex exec` or `pi` CLI subprocesses. Each target call, grader call, and optimizer call invokes the underlying model and consumes account/subscription quotas. Always verify estimated model calls via `--dry-run` before execution.
