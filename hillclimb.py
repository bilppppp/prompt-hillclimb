#!/usr/bin/env python3
"""Prompt Hillclimb MVP

Automated text-in / text-out prompt optimizer with train/val/final evaluation splits,
process isolation, and rejection-based hillclimbing.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class HillclimbError(Exception):
    """Base exception for hillclimb errors."""


class EvalFormatError(HillclimbError):
    """Raised when eval dataset format or schema is invalid."""


class GraderParseError(HillclimbError):
    """Raised when grader output cannot be parsed strictly."""


class OptimizerMarkerError(HillclimbError):
    """Raised when optimizer candidate prompt markers are missing or malformed."""


class CandidateValidationError(HillclimbError):
    """Raised when candidate prompt fails static validation."""


class SubprocessExecutionError(HillclimbError):
    """Raised when target, grader, or optimizer process fails."""


@dataclass
class EvalCase:
    id: str
    split: str  # 'train' | 'val' | 'final'
    input: str
    criteria: list[str]


@dataclass
class CriterionResult:
    index: int
    status: str  # 'PASS' | 'FAIL'
    reason: str = ""

    def to_dict(self) -> dict:
        return {"index": self.index, "status": self.status, "reason": self.reason}


@dataclass
class CaseExecutionResult:
    id: str
    repeat: int
    input: str = ""
    response: str = ""
    criteria: list[CriterionResult] = field(default_factory=list)
    error: dict | None = None

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "repeat": self.repeat,
            "input": self.input,
        }
        if self.response:
            data["response"] = self.response
        if self.criteria:
            data["criteria"] = [c.to_dict() for c in self.criteria]
        if self.error is not None:
            data["error"] = self.error
        return data


def load_eval_cases(eval_path: str, limit: int | None = None) -> list[EvalCase]:
    """Parse and validate eval cases from a JSONL file."""
    if not os.path.isfile(eval_path):
        raise EvalFormatError(f"Eval file not found: {eval_path}")

    cases: list[EvalCase] = []
    seen_ids: set[str] = set()

    with open(eval_path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvalFormatError(f"Line {line_no} in {eval_path} is invalid JSON: {exc}") from exc

            if not isinstance(item, dict):
                raise EvalFormatError(f"Line {line_no} in {eval_path} must be a JSON object")

            for required_field in ("id", "split", "input", "criteria"):
                if required_field not in item:
                    raise EvalFormatError(
                        f"Line {line_no} in {eval_path} missing required field: '{required_field}'"
                    )

            case_id = str(item["id"]).strip()
            if not case_id:
                raise EvalFormatError(f"Line {line_no} in {eval_path} has empty 'id'")
            if case_id in seen_ids:
                raise EvalFormatError(f"Duplicate case id '{case_id}' at line {line_no}")
            seen_ids.add(case_id)

            split = str(item["split"]).strip()
            if split not in ("train", "val", "final"):
                raise EvalFormatError(
                    f"Line {line_no} has invalid split '{split}'. Must be train, val, or final"
                )

            case_input = str(item["input"]).strip()
            if not case_input:
                raise EvalFormatError(f"Line {line_no} has empty 'input'")

            raw_criteria = item["criteria"]
            if not isinstance(raw_criteria, list) or len(raw_criteria) == 0:
                raise EvalFormatError(
                    f"Line {line_no} 'criteria' must be a non-empty array of strings"
                )

            criteria: list[str] = []
            for c_idx, crit in enumerate(raw_criteria):
                if not isinstance(crit, str) or not crit.strip():
                    raise EvalFormatError(
                        f"Line {line_no} criterion {c_idx} must be a non-empty string"
                    )
                criteria.append(crit.strip())

            cases.append(EvalCase(id=case_id, split=split, input=case_input, criteria=criteria))

    if not cases:
        raise EvalFormatError(f"Eval file {eval_path} contains no valid cases")

    splits_present = {c.split for c in cases}
    for required_split in ("train", "val", "final"):
        if required_split not in splits_present:
            raise EvalFormatError(f"Eval dataset missing required split '{required_split}'")

    if limit is not None and limit > 0:
        limited_cases: list[EvalCase] = []
        for split_name in ("train", "val", "final"):
            split_items = [c for c in cases if c.split == split_name]
            limited_cases.extend(split_items[:limit])
        cases = limited_cases

    return cases


def filter_by_split(cases: list[EvalCase], split: str) -> list[EvalCase]:
    return [c for c in cases if c.split == split]


def check_runner_executable(runner: str) -> str:
    """Check that runner CLI executable is available in PATH."""
    path = shutil.which(runner)
    if not path:
        raise RuntimeError(f"{runner} executable not found")
    return path


def token_in_text(token: str, text: str) -> bool:
    """Check if token exists as an isolated flag token in CLI help text."""
    pattern = r"(?:^|[\s,])" + re.escape(token) + r"(?:[\s=,:]|$)"
    return bool(re.search(pattern, text))


def verify_runner_cli_flags(runner: str) -> None:
    """Inspect CLI help output to verify that all required isolation flags exist."""
    runner_path = check_runner_executable(runner)
    if runner == "codex":
        try:
            res = subprocess.run(
                [runner_path, "exec", "--help"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to execute '{runner} exec --help': {exc}") from exc

        if res.returncode != 0:
            raise RuntimeError(f"'{runner} exec --help' exited with code {res.returncode}: {res.stderr}")

        help_output = res.stdout + res.stderr
        required_flags = [
            "-C",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "-s",
            "-o",
            "--color",
        ]
        missing = [f for f in required_flags if not token_in_text(f, help_output)]
        if missing:
            raise RuntimeError(f"Codex CLI help is missing required flags: {missing}")

    elif runner == "pi":
        try:
            res = subprocess.run(
                [runner_path, "--help"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to execute '{runner} --help': {exc}") from exc

        if res.returncode != 0:
            raise RuntimeError(f"'{runner} --help' exited with code {res.returncode}: {res.stderr}")

        help_output = res.stdout + res.stderr
        required_flags = [
            "-p",
            "--no-tools",
            "--no-skills",
            "--no-context-files",
            "--no-extensions",
            "--no-session",
            "--no-prompt-templates",
            "--no-themes",
            "--no-approve",
        ]
        missing = [f for f in required_flags if not token_in_text(f, help_output)]
        if missing:
            raise RuntimeError(f"Pi CLI help is missing required flags: {missing}")


def verify_hillclimb_writable(base_dir: str = ".hillclimb") -> None:
    """Test that .hillclimb is genuinely writable by writing and deleting a temporary probe file."""
    os.makedirs(base_dir, exist_ok=True)
    probe_name = f".write_test_{os.getpid()}_{int(datetime.datetime.now().timestamp() * 1000)}"
    probe_path = os.path.join(base_dir, probe_name)
    try:
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write("probe")
    except Exception as exc:
        raise RuntimeError(f"Directory '{base_dir}' is not writable: {exc}") from exc
    finally:
        if os.path.exists(probe_path):
            try:
                os.remove(probe_path)
            except OSError:
                pass


def validate_run_parameters(
    target_prompt: str,
    rounds: int,
    repeats: int,
    min_gain: float,
    max_growth: float,
    limit: int | None,
) -> None:
    """Validate all runtime parameters strictly."""
    if not target_prompt.strip():
        raise ValueError("Target prompt cannot be empty or whitespace only")
    if repeats < 1:
        raise ValueError(f"--repeats must be an integer >= 1 (got {repeats})")
    if rounds < 0:
        raise ValueError(f"--rounds must be an integer >= 0 (got {rounds})")
    if limit is not None and limit < 1:
        raise ValueError(f"--limit must be an integer >= 1 (got {limit})")
    if not math.isfinite(min_gain) or min_gain < 0.0:
        raise ValueError(f"--min-gain must be a finite float >= 0.0 (got {min_gain})")
    if not math.isfinite(max_growth) or max_growth <= 0.0:
        raise ValueError(f"--max-growth must be a finite float > 0.0 (got {max_growth})")


def check_global_context_contamination(runner: str) -> list[str]:
    """Check for global instruction files and document CLI isolation boundaries."""
    warnings: list[str] = []
    if runner == "codex":
        codex_home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
        agents_path = os.path.join(codex_home, "AGENTS.md")
        skills_path = os.path.join(codex_home, "skills")
        if os.path.isfile(agents_path):
            warnings.append(
                f"Global instructions detected at {agents_path}. "
                "codex exec cannot completely disable global instructions and may contaminate evaluations."
            )
        if os.path.isdir(skills_path):
            warnings.append(
                f"Global skills detected at {skills_path}. "
                "Codex -s read-only restricts file writes, but does NOT disable reading files or tools."
            )
    elif runner == "pi":
        pi_dir = os.environ.get("PI_CODING_AGENT_DIR", os.path.expanduser("~/.pi/agent"))
        system_md = os.path.join(pi_dir, "SYSTEM.md")
        append_system_md = os.path.join(pi_dir, "APPEND_SYSTEM.md")
        if os.path.isfile(system_md):
            warnings.append(
                f"Global system prompt detected at {system_md}. "
                "Pi's --no-context-files does not disable SYSTEM.md and may contaminate evaluations."
            )
        if os.path.isfile(append_system_md):
            warnings.append(
                f"Global append system prompt detected at {append_system_md}. "
                "Pi's --no-context-files does not disable APPEND_SYSTEM.md and may contaminate evaluations."
            )
    return warnings


def estimate_model_calls(
    train_count: int, val_count: int, final_count: int, rounds: int, repeats: int
) -> dict[str, int]:
    """Estimate total model invocation counts for the hillclimb run."""
    baseline_calls = (train_count + val_count) * repeats * 2
    round_calls = 1 + (train_count + val_count) * repeats * 2
    final_calls = final_count * repeats * 2
    total_calls = baseline_calls + (rounds * round_calls) + final_calls

    return {
        "baseline": baseline_calls,
        "round_calls": round_calls,
        "rounds": rounds,
        "rounds_total": rounds * round_calls,
        "final": final_calls,
        "total": total_calls,
    }


def estimate_noise_calls(train_count: int, val_count: int, repeats: int) -> dict[str, int]:
    """Estimate model invocation counts for noise measurement (2 baseline runs only)."""
    per_run = (train_count + val_count) * repeats * 2
    total = per_run * 2
    return {"per_run": per_run, "total": total}


def format_call_estimate(estimates: dict[str, int]) -> str:
    lines = [
        "Estimated model calls:",
        f"  Baseline: {estimates['baseline']}",
    ]
    for r in range(1, estimates["rounds"] + 1):
        lines.append(f"  Round {r}: {estimates['round_calls']}")
    lines.append(f"  Final: {estimates['final']}")
    lines.append(f"  Total: ~{estimates['total']}")
    return "\n".join(lines)


def create_unique_run_dir(base_dir: str = ".hillclimb", prefix: str = "") -> str:
    """Create a timestamped directory without overwriting within the same second."""
    os.makedirs(base_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dir_name = f"{timestamp}{prefix}"
    target_path = os.path.join(base_dir, dir_name)
    if not os.path.exists(target_path):
        os.makedirs(target_path)
        return target_path

    counter = 1
    while True:
        target_path = os.path.join(base_dir, f"{dir_name}_{counter}")
        if not os.path.exists(target_path):
            os.makedirs(target_path)
            return target_path
        counter += 1


def run_agent(runner: str, prompt: str, timeout: int = 300) -> str:
    """Execute model via CLI inside a brand new empty TemporaryDirectory."""
    runner_path = check_runner_executable(runner)

    with tempfile.TemporaryDirectory() as temp_dir:
        if runner == "codex":
            output_file = os.path.join(temp_dir, "last_message.txt")
            cmd = [
                runner_path,
                "exec",
                "-C",
                temp_dir,
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "-s",
                "read-only",
                "--color",
                "never",
                "-o",
                output_file,
                "-",
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    cwd=temp_dir,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise SubprocessExecutionError(f"Codex execution timed out after {timeout}s") from exc

            if proc.returncode != 0:
                err_msg = proc.stderr.strip() or f"Process exited with code {proc.returncode}"
                raise SubprocessExecutionError(f"Codex execution failed: {err_msg}")

            if not os.path.isfile(output_file):
                raise SubprocessExecutionError(
                    f"Codex last message output file was not created: {output_file}"
                )

            with open(output_file, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                raise SubprocessExecutionError("Codex produced empty or whitespace-only output")

            return content

        elif runner == "pi":
            cmd = [
                runner_path,
                "-p",
                "--no-tools",
                "--no-skills",
                "--no-context-files",
                "--no-extensions",
                "--no-session",
                "--no-prompt-templates",
                "--no-themes",
                "--no-approve",
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    cwd=temp_dir,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise SubprocessExecutionError(f"Pi execution timed out after {timeout}s") from exc

            if proc.returncode != 0:
                err_msg = proc.stderr.strip() or f"Process exited with code {proc.returncode}"
                raise SubprocessExecutionError(f"Pi execution failed: {err_msg}")

            content = proc.stdout
            if not content.strip():
                raise SubprocessExecutionError("Pi produced empty or whitespace-only output")

            return content

        else:
            raise ValueError(f"Unsupported runner: {runner}")


def build_target_prompt(candidate_prompt: str, case_input: str) -> str:
    return (
        "直接根据下面提供的文本回答。\n"
        "不要读取本地文件。\n"
        "不要搜索目录。\n"
        "不要使用任何工具。\n"
        "不要尝试寻找额外上下文。\n\n"
        f"<instruction>\n{candidate_prompt.strip()}\n</instruction>\n\n"
        f"<task>\n{case_input.strip()}\n</task>"
    )


def run_target(runner: str, candidate_prompt: str, case_input: str, timeout: int = 300) -> str:
    prompt = build_target_prompt(candidate_prompt, case_input)
    return run_agent(runner, prompt, timeout=timeout)


def build_grader_prompt(case_input: str, criteria: list[str], response: str) -> str:
    criteria_formatted = "\n".join(f"{i+1}. {c}" for i, c in enumerate(criteria))
    return (
        "直接根据下面提供的文本回答。\n"
        "不要读取本地文件。\n"
        "不要搜索目录。\n"
        "不要使用任何工具。\n"
        "不要尝试寻找额外上下文。\n\n"
        "请评估以下回答是否满足评测标准。\n\n"
        f"<task>\n{case_input.strip()}\n</task>\n\n"
        f"<criteria>\n{criteria_formatted}\n</criteria>\n\n"
        f"<response>\n{response.strip()}\n</response>\n\n"
        "严格按如下格式输出评测结果，对每条标准输出一行，编号必须与标准一致：\n"
        "1: PASS | 简短原因\n"
        "2: FAIL | 简短原因\n"
        "不要输出最终总分。"
    )


def parse_grader_output(output: str, expected_count: int) -> list[CriterionResult]:
    """Strictly parse grader criterion verdicts for 1..N criteria.

    Rejects unknown status, invalid numbering, duplicate indices, and unparseable extraneous content.
    """
    pattern = re.compile(
        r"^(?:\*\*)?(\d+)(?:\*\*)?[\s.:、]+(?:\*\*)?([A-Za-z0-9_-]+)(?:\*\*)?(?:\s*[:|]\s*(.*))?$"
    )
    parsed_by_index: dict[int, CriterionResult] = {}

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Skip markdown code fences if present at boundaries
        if line.startswith("```"):
            continue

        match = pattern.match(line)
        if not match:
            raise GraderParseError(f"Unparseable extraneous content in grader output: '{line}'")

        idx_str = match.group(1)
        status_raw = match.group(2).upper()
        reason = (match.group(3) or "").strip()

        idx = int(idx_str)
        if idx in parsed_by_index:
            raise GraderParseError(f"Duplicate criterion index {idx} in grader output")
        if idx < 1 or idx > expected_count:
            raise GraderParseError(
                f"Criterion index {idx} out of valid range (1..{expected_count})"
            )
        if status_raw not in ("PASS", "FAIL"):
            raise GraderParseError(
                f"Invalid criterion status '{status_raw}' for criterion {idx} (must be PASS or FAIL)"
            )

        parsed_by_index[idx] = CriterionResult(index=idx, status=status_raw, reason=reason)

    if len(parsed_by_index) != expected_count:
        missing = [i for i in range(1, expected_count + 1) if i not in parsed_by_index]
        raise GraderParseError(
            f"Expected {expected_count} criteria results, parsed {len(parsed_by_index)}. Missing: {missing}"
        )

    return [parsed_by_index[i] for i in range(1, expected_count + 1)]


def run_grader(
    runner: str, case_input: str, criteria: list[str], response: str, timeout: int = 300
) -> list[CriterionResult]:
    prompt = build_grader_prompt(case_input, criteria, response)
    raw_output = run_agent(runner, prompt, timeout=timeout)
    return parse_grader_output(raw_output, len(criteria))


def compute_split_score(results: list[CaseExecutionResult]) -> float:
    """Compute overall criterion-level pass percentage across cases and repeats.

    Raises HillclimbError if any result contains an error.
    """
    total_criteria = 0
    passed_criteria = 0
    for res in results:
        if res.error is not None:
            raise HillclimbError(
                f"Cannot compute split score: case '{res.id}' failed with error: {res.error}"
            )
        for crit in res.criteria:
            total_criteria += 1
            if crit.status == "PASS":
                passed_criteria += 1

    if total_criteria == 0:
        return 0.0
    return (passed_criteria / total_criteria) * 100.0


def extract_candidate_prompt(text: str) -> str:
    """Extract candidate prompt from the last <<<PROMPT>>> and first matching <<<END_PROMPT>>>."""
    start_tag = "<<<PROMPT>>>"
    end_tag = "<<<END_PROMPT>>>"

    start_idx = text.rfind(start_tag)
    if start_idx == -1:
        raise OptimizerMarkerError(f"Missing start marker '{start_tag}'")

    search_from = start_idx + len(start_tag)
    end_idx = text.find(end_tag, search_from)
    if end_idx == -1:
        raise OptimizerMarkerError(f"Missing end marker '{end_tag}' after start marker")

    candidate = text[search_from:end_idx].strip("\r\n")
    return candidate


def validate_candidate(
    candidate: str,
    best_prompt: str,
    train_cases: list[EvalCase],
    max_growth: float = 1.5,
) -> tuple[bool, str]:
    """Validate candidate prompt against emptiness, leakage, and length growth rules."""
    # 0. Check emptiness
    if not candidate or not candidate.strip():
        return False, "Candidate prompt cannot be empty or whitespace only"

    # 1. Check case ID leakage
    for case in train_cases:
        if case.id in candidate:
            return False, f"Candidate leaks train case id: '{case.id}'"

    # 2. Check input copying heuristic (snippets >= 30 chars)
    norm_candidate = " ".join(candidate.split())
    for case in train_cases:
        norm_input = " ".join(case.input.split())
        if len(norm_input) >= 30:
            for i in range(len(norm_input) - 30 + 1):
                snippet = norm_input[i : i + 30]
                if snippet in norm_candidate:
                    return False, f"Candidate copies train input snippet: '{snippet[:20]}...'"

    # 3. Check length growth
    max_len = int(len(best_prompt) * max_growth)
    if len(best_prompt) > 0 and len(candidate) > max_len:
        return (
            False,
            f"Candidate length ({len(candidate)}) exceeds max growth ({len(best_prompt)} * {max_growth} = {max_len})",
        )

    return True, ""


def build_optimizer_prompt(best_prompt: str, train_failures: list[dict]) -> str:
    """Construct prompt for optimizer LLM."""
    failures_text = ""
    if not train_failures:
        failures_text = "当前 train 评测中所有标准均已通过。请聚焦于优化表达结构、消除冗余与提升通用泛化能力，避免破坏已有约束。"
    else:
        failure_blocks = []
        for f in train_failures:
            block = [
                f"Case ID: {f.get('id', 'unknown')}",
                f"Task: {f.get('input', '')}",
                f"Response: {f.get('response', '')}",
                "Failed Criteria:",
            ]
            for fc in f.get("failed_criteria", []):
                block.append(f"  - Standard: {fc.get('criterion', '')}")
                block.append(f"    Feedback: {fc.get('reason', '')}")
            failure_blocks.append("\n".join(block))
        failures_text = "\n\n---\n\n".join(failure_blocks)

    return (
        "直接根据下面提供的文本回答。\n"
        "不要读取本地文件。\n"
        "不要搜索目录。\n"
        "不要使用任何工具。\n"
        "不要尝试寻找额外上下文。\n\n"
        "你是一个 Prompt 优化专家。当前有一个 Prompt 在部分评估任务中失败了。\n"
        "请根据以下失败案例，对当前 Prompt 进行最小有效优化。\n\n"
        "目标是改善重复出现的失败模式，而不是针对具体案例打补丁。\n"
        "每轮只做一个主要的概念性修改。\n\n"
        "优先：\n"
        "- 删除无效或冲突规则\n"
        "- 澄清模糊约束\n"
        "- 增加缺失的通用原则\n"
        "- 简化不必要 wording\n\n"
        "避免：\n"
        "- 把具体 eval case 写进 Prompt\n"
        "- 针对 case id 添加规则\n"
        "- 加大量例外\n"
        "- 无理由重写整个 Prompt\n"
        "- 单纯让 Prompt 越来越长\n\n"
        f"<current_prompt>\n{best_prompt.strip()}\n</current_prompt>\n\n"
        f"<failures>\n{failures_text}\n</failures>\n\n"
        "请输出完整的新 Prompt。\n"
        "必须使用如下标记包裹新 Prompt：\n"
        "<<<PROMPT>>>\n"
        "完整的新 Prompt\n"
        "<<<END_PROMPT>>>"
    )


def run_optimizer(
    runner: str, best_prompt: str, train_failures: list[dict], timeout: int = 300
) -> str:
    prompt = build_optimizer_prompt(best_prompt, train_failures)
    raw_output = run_agent(runner, prompt, timeout=timeout)
    return extract_candidate_prompt(raw_output)


def should_keep_candidate(
    candidate_train: float,
    candidate_val: float,
    best_train: float,
    best_val: float,
    min_gain: float,
) -> bool:
    """Acceptance rule: candidate_train >= best_train AND candidate_val >= best_val + min_gain."""
    return candidate_train >= best_train and candidate_val >= (best_val + min_gain)


def evaluate_split(
    runner: str,
    prompt: str,
    cases: list[EvalCase],
    repeats: int,
    timeout: int = 300,
) -> tuple[float, list[CaseExecutionResult], dict | None]:
    """Evaluate prompt against a split. Returns (score, results, first_error).

    Differentiates error stages: 'target' vs 'grader' and retains response on grader failure.
    """
    results: list[CaseExecutionResult] = []

    for case in cases:
        for rep in range(1, repeats + 1):
            target_response = ""
            try:
                target_response = run_target(runner, prompt, case.input, timeout=timeout)
            except Exception as exc:
                err_dict = {
                    "stage": "target",
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                results.append(
                    CaseExecutionResult(
                        id=case.id,
                        repeat=rep,
                        input=case.input,
                        response="",
                        error=err_dict,
                    )
                )
                return 0.0, results, err_dict

            try:
                criteria_results = run_grader(
                    runner, case.input, case.criteria, target_response, timeout=timeout
                )
                results.append(
                    CaseExecutionResult(
                        id=case.id,
                        repeat=rep,
                        input=case.input,
                        response=target_response,
                        criteria=criteria_results,
                    )
                )
            except Exception as exc:
                err_dict = {
                    "stage": "grader",
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                results.append(
                    CaseExecutionResult(
                        id=case.id,
                        repeat=rep,
                        input=case.input,
                        response=target_response,  # Retain obtained target response
                        error=err_dict,
                    )
                )
                return 0.0, results, err_dict

    score = compute_split_score(results)
    return score, results, None


def save_jsonl_results(filepath: str, results: list[CaseExecutionResult]) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")


def collect_train_failures(cases: list[EvalCase], results: list[CaseExecutionResult]) -> list[dict]:
    case_map = {c.id: c for c in cases}
    failures = []

    for r in results:
        if r.error is not None:
            continue
        failed_crits = [c for c in r.criteria if c.status == "FAIL"]
        if failed_crits:
            case = case_map.get(r.id)
            crit_texts = case.criteria if case else []
            f_item = {
                "id": r.id,
                "repeat": r.repeat,
                "input": case.input if case else "",
                "response": r.response,
                "failed_criteria": [
                    {
                        "index": fc.index,
                        "criterion": crit_texts[fc.index - 1]
                        if fc.index - 1 < len(crit_texts)
                        else "",
                        "reason": fc.reason,
                    }
                    for fc in failed_crits
                ],
            }
            failures.append(f_item)
    return failures


def run_noise_measurement(
    runner: str,
    target_prompt: str,
    train_cases: list[EvalCase],
    val_cases: list[EvalCase],
    repeats: int,
    suggested_min_gain: float = 3.0,
    timeout: int = 300,
    limit: int | None = None,
) -> int:
    """Run baseline twice independently and report/save observed val score delta."""
    estimates = estimate_noise_calls(len(train_cases), len(val_cases), repeats)
    print("Estimated model calls (Noise Measurement):")
    print(f"  Run 1: {estimates['per_run']}")
    print(f"  Run 2: {estimates['per_run']}")
    print(f"  Total: ~{estimates['total']}\n")

    run_dir = create_unique_run_dir(".hillclimb", prefix="-noise")
    with open(os.path.join(run_dir, "original-prompt.md"), "w", encoding="utf-8") as f:
        f.write(target_prompt)

    config_data = {
        "runner": runner,
        "repeats": repeats,
        "train_count": len(train_cases),
        "val_count": len(val_cases),
        "limit": limit,
    }
    with open(os.path.join(run_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    def write_noise_abort_summary(stage_reason: str) -> None:
        err_lines = []
        if limit is not None:
            err_lines.append("LIMITED SMOKE RUN — NOT A FULL EVALUATION\n")
        err_lines.extend(
            [
                "# Baseline Noise Measurement",
                "",
                f"Runner: {runner}",
                f"Repeats: {repeats}",
                "Status: ABORT",
                f"Reason: {stage_reason}",
                "",
            ]
        )
        with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(err_lines))

    print("Running Baseline measurement 1...")
    run1_dir = os.path.join(run_dir, "run-1")
    os.makedirs(run1_dir, exist_ok=True)
    train_score_1, train_res_1, err1 = evaluate_split(
        runner, target_prompt, train_cases, repeats, timeout=timeout
    )
    save_jsonl_results(os.path.join(run1_dir, "train.jsonl"), train_res_1)
    if err1:
        print(f"Baseline run 1 failed on train: {err1['message']}", file=sys.stderr)
        write_noise_abort_summary(f"Run 1 train failed: {err1['message']}")
        return 1

    val_score_1, val_res_1, err1_val = evaluate_split(
        runner, target_prompt, val_cases, repeats, timeout=timeout
    )
    save_jsonl_results(os.path.join(run1_dir, "val.jsonl"), val_res_1)
    if err1_val:
        print(f"Baseline run 1 failed on val: {err1_val['message']}", file=sys.stderr)
        write_noise_abort_summary(f"Run 1 val failed: {err1_val['message']}")
        return 1

    print("Running Baseline measurement 2...")
    run2_dir = os.path.join(run_dir, "run-2")
    os.makedirs(run2_dir, exist_ok=True)
    train_score_2, train_res_2, err2 = evaluate_split(
        runner, target_prompt, train_cases, repeats, timeout=timeout
    )
    save_jsonl_results(os.path.join(run2_dir, "train.jsonl"), train_res_2)
    if err2:
        print(f"Baseline run 2 failed on train: {err2['message']}", file=sys.stderr)
        write_noise_abort_summary(f"Run 2 train failed: {err2['message']}")
        return 1

    val_score_2, val_res_2, err2_val = evaluate_split(
        runner, target_prompt, val_cases, repeats, timeout=timeout
    )
    save_jsonl_results(os.path.join(run2_dir, "val.jsonl"), val_res_2)
    if err2_val:
        print(f"Baseline run 2 failed on val: {err2_val['message']}", file=sys.stderr)
        write_noise_abort_summary(f"Run 2 val failed: {err2_val['message']}")
        return 1

    train_delta = abs(train_score_1 - train_score_2)
    val_delta = abs(val_score_1 - val_score_2)
    rec_min_gain = max(int(val_delta + 1.0), int(suggested_min_gain))

    output = [
        "Baseline run 1",
        f"train: {train_score_1:.1f}",
        f"val:   {val_score_1:.1f}",
        "",
        "Baseline run 2",
        f"train: {train_score_2:.1f}",
        f"val:   {val_score_2:.1f}",
        "",
        "Observed train delta:",
        f"{train_delta:.1f}",
        "",
        "Observed val delta:",
        f"{val_delta:.1f}",
        "",
        f"Observed baseline variation is {val_delta:.1f} points.",
        f"Consider using --min-gain >= {rec_min_gain} or increasing --repeats.",
    ]
    summary_text = "\n".join(output)
    print(summary_text)

    summary_file_content = []
    if limit is not None:
        summary_file_content.append("LIMITED SMOKE RUN — NOT A FULL EVALUATION\n")
    summary_file_content.append(f"# Baseline Noise Measurement\n\nRunner: {runner}\nRepeats: {repeats}\n\n" + summary_text)
    with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(summary_file_content) + "\n")

    print(f"\nNoise measurement outputs saved to: {run_dir}")
    return 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prompt Hillclimb: automated prompt optimization via train/val evaluation."
    )
    parser.add_argument(
        "--target",
        type=str,
        required=True,
        help="Path to the initial candidate/target prompt file.",
    )
    parser.add_argument(
        "--eval",
        type=str,
        required=True,
        help="Path to evaluation JSONL file containing train, val, and final cases.",
    )
    parser.add_argument(
        "--runner",
        type=str,
        choices=["codex", "pi"],
        default="codex",
        help="CLI runner to use (default: codex).",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="Number of hillclimb optimization rounds (default: 3).",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Repeats per evaluation case (default: 1).",
    )
    parser.add_argument(
        "--min-gain",
        type=float,
        default=3.0,
        help="Minimum validation score gain required to KEEP candidate (default: 3.0).",
    )
    parser.add_argument(
        "--max-growth",
        type=float,
        default=1.5,
        help="Maximum allowed candidate length growth multiplier (default: 1.5).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of cases per split for quick smoke runs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration, dataset, executable, and exit without model calls.",
    )
    parser.add_argument(
        "--measure-noise",
        action="store_true",
        help="Run baseline twice independently to observe validation variance.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    # Prepend LIMITED SMOKE RUN header to all outputs when --limit is active
    if args.limit is not None:
        print("LIMITED SMOKE RUN — NOT A FULL EVALUATION\n")

    if not os.path.isfile(args.target):
        print(f"Error: Target prompt file '{args.target}' does not exist.", file=sys.stderr)
        return 1

    with open(args.target, "r", encoding="utf-8") as f:
        target_prompt = f.read()

    # Parameter validation
    try:
        validate_run_parameters(
            target_prompt=target_prompt,
            rounds=args.rounds,
            repeats=args.repeats,
            min_gain=args.min_gain,
            max_growth=args.max_growth,
            limit=args.limit,
        )
    except ValueError as exc:
        print(f"Error in arguments: {exc}", file=sys.stderr)
        return 1

    try:
        cases = load_eval_cases(args.eval, limit=args.limit)
    except EvalFormatError as exc:
        print(f"Error parsing eval cases: {exc}", file=sys.stderr)
        return 1

    train_cases = filter_by_split(cases, "train")
    val_cases = filter_by_split(cases, "val")
    final_cases = filter_by_split(cases, "final")

    try:
        check_runner_executable(args.runner)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Verify CLI help and flags
    try:
        verify_runner_cli_flags(args.runner)
    except RuntimeError as exc:
        print(f"Error verifying CLI flags: {exc}", file=sys.stderr)
        return 1

    # Verify .hillclimb is genuinely writable via file probe
    try:
        verify_hillclimb_writable(".hillclimb")
    except RuntimeError as exc:
        print(f"Error verifying .hillclimb writability: {exc}", file=sys.stderr)
        return 1

    contamination_warnings = check_global_context_contamination(args.runner)
    for warn in contamination_warnings:
        print(f"WARNING: {warn}", file=sys.stderr)

    if args.dry_run:
        if args.measure_noise:
            noise_est = estimate_noise_calls(len(train_cases), len(val_cases), args.repeats)
            print("Estimated model calls (Noise Measurement):")
            print(f"  Run 1: {noise_est['per_run']}")
            print(f"  Run 2: {noise_est['per_run']}")
            print(f"  Total: ~{noise_est['total']}")
        else:
            estimates = estimate_model_calls(
                train_count=len(train_cases),
                val_count=len(val_cases),
                final_count=len(final_cases),
                rounds=args.rounds,
                repeats=args.repeats,
            )
            print(format_call_estimate(estimates))

        print("\n[DRY RUN] All validation checks passed successfully.")
        print(f"  Target prompt length: {len(target_prompt)} chars")
        print(f"  Cases: {len(train_cases)} train, {len(val_cases)} val, {len(final_cases)} final")
        print(f"  Runner executable: {shutil.which(args.runner)}")
        print("  Runner CLI isolation flags verified via help inspection.")
        print("  .hillclimb write test succeeded.")
        print("  Dry run complete. No models were invoked.")
        return 0

    if args.measure_noise:
        return run_noise_measurement(
            runner=args.runner,
            target_prompt=target_prompt,
            train_cases=train_cases,
            val_cases=val_cases,
            repeats=args.repeats,
            suggested_min_gain=args.min_gain,
            limit=args.limit,
        )

    estimates = estimate_model_calls(
        train_count=len(train_cases),
        val_count=len(val_cases),
        final_count=len(final_cases),
        rounds=args.rounds,
        repeats=args.repeats,
    )
    print(format_call_estimate(estimates))

    # Initialize collision-free output directory
    run_dir = create_unique_run_dir(".hillclimb")

    with open(os.path.join(run_dir, "original-prompt.md"), "w", encoding="utf-8") as f:
        f.write(target_prompt)

    config_data = {
        "target": args.target,
        "eval": args.eval,
        "runner": args.runner,
        "rounds": args.rounds,
        "repeats": args.repeats,
        "min_gain": args.min_gain,
        "max_growth": args.max_growth,
        "limit": args.limit,
    }
    with open(os.path.join(run_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    print(f"\nStarting Hillclimb run in {run_dir}")

    # Step 1: Baseline Evaluation
    print("\n--- Running Baseline ---")
    baseline_dir = os.path.join(run_dir, "baseline")
    os.makedirs(baseline_dir, exist_ok=True)

    train_score, train_results, train_err = evaluate_split(
        args.runner, target_prompt, train_cases, args.repeats
    )
    save_jsonl_results(os.path.join(baseline_dir, "train.jsonl"), train_results)
    if train_err:
        summary_content = (
            f"# Prompt Hillclimb\n\n"
            f"Runner: {args.runner}\n"
            f"Status: ABORT\n"
            f"Reason: Baseline train evaluation failed at stage '{train_err['stage']}': {train_err['message']}\n"
        )
        if args.limit is not None:
            summary_content = "LIMITED SMOKE RUN — NOT A FULL EVALUATION\n\n" + summary_content
        with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
            f.write(summary_content)
        print(f"ABORT: Baseline train evaluation failed: {train_err['message']}", file=sys.stderr)
        return 1

    val_score, val_results, val_err = evaluate_split(
        args.runner, target_prompt, val_cases, args.repeats
    )
    save_jsonl_results(os.path.join(baseline_dir, "val.jsonl"), val_results)
    if val_err:
        summary_content = (
            f"# Prompt Hillclimb\n\n"
            f"Runner: {args.runner}\n"
            f"Status: ABORT\n"
            f"Reason: Baseline val evaluation failed at stage '{val_err['stage']}': {val_err['message']}\n"
        )
        if args.limit is not None:
            summary_content = "LIMITED SMOKE RUN — NOT A FULL EVALUATION\n\n" + summary_content
        with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
            f.write(summary_content)
        print(f"ABORT: Baseline val evaluation failed: {val_err['message']}", file=sys.stderr)
        return 1

    print(f"Baseline Train: {train_score:.1f}, Val: {val_score:.1f}")

    best_prompt = target_prompt
    best_train_score = train_score
    best_val_score = val_score
    latest_train_results = train_results

    round_summaries: list[dict] = []

    # Step 2: Hillclimb Rounds
    for r in range(1, args.rounds + 1):
        round_name = f"round-{r:02d}"
        round_dir = os.path.join(run_dir, round_name)
        os.makedirs(round_dir, exist_ok=True)

        print(f"\n--- Round {r} ---")
        train_failures = collect_train_failures(train_cases, latest_train_results)

        round_info: dict = {"round": r, "status": "OK", "decision": "REVERT"}

        try:
            candidate = run_optimizer(args.runner, best_prompt, train_failures)
        except Exception as exc:
            print(f"Optimizer failed in Round {r}: {exc}")
            round_info["status"] = "INVALID"
            round_info["reason"] = f"optimizer error: {exc}"
            round_info["decision"] = "REVERT"
            round_summaries.append(round_info)
            continue

        with open(os.path.join(round_dir, "candidate.md"), "w", encoding="utf-8") as f:
            f.write(candidate)

        valid, val_reason = validate_candidate(
            candidate, best_prompt, train_cases, max_growth=args.max_growth
        )
        if not valid:
            print(f"Candidate validation failed in Round {r}: {val_reason}")
            round_info["status"] = "INVALID"
            round_info["reason"] = val_reason
            round_info["decision"] = "REVERT"
            round_summaries.append(round_info)
            continue

        cand_train_score, cand_train_results, cand_train_err = evaluate_split(
            args.runner, candidate, train_cases, args.repeats
        )
        save_jsonl_results(os.path.join(round_dir, "train.jsonl"), cand_train_results)
        if cand_train_err:
            print(f"Candidate train evaluation failed in Round {r}: {cand_train_err['message']}")
            round_info["status"] = "INVALID"
            round_info["reason"] = f"candidate train error ({cand_train_err['stage']}): {cand_train_err['message']}"
            round_info["decision"] = "REVERT"
            round_summaries.append(round_info)
            continue

        cand_val_score, cand_val_results, cand_val_err = evaluate_split(
            args.runner, candidate, val_cases, args.repeats
        )
        save_jsonl_results(os.path.join(round_dir, "val.jsonl"), cand_val_results)
        if cand_val_err:
            print(f"Candidate val evaluation failed in Round {r}: {cand_val_err['message']}")
            round_info["status"] = "INVALID"
            round_info["reason"] = f"candidate val error ({cand_val_err['stage']}): {cand_val_err['message']}"
            round_info["decision"] = "REVERT"
            round_summaries.append(round_info)
            continue

        gain = cand_val_score - best_val_score
        round_info["train"] = cand_train_score
        round_info["val"] = cand_val_score
        round_info["gain"] = gain

        if should_keep_candidate(
            cand_train_score, cand_val_score, best_train_score, best_val_score, args.min_gain
        ):
            print(
                f"Round {r} KEEP: Train {cand_train_score:.1f}, Val {cand_val_score:.1f} (Gain: +{gain:.1f})"
            )
            round_info["decision"] = "KEEP"
            best_prompt = candidate
            best_train_score = cand_train_score
            best_val_score = cand_val_score
            latest_train_results = cand_train_results
        else:
            print(
                f"Round {r} REVERT: Train {cand_train_score:.1f}, Val {cand_val_score:.1f} (Gain: {gain:+.1f})"
            )
            round_info["decision"] = "REVERT"

        round_summaries.append(round_info)

    # Step 3: Save Best Prompt
    with open(os.path.join(run_dir, "best-prompt.md"), "w", encoding="utf-8") as f:
        f.write(best_prompt)

    # Step 4: Final Evaluation (Run exactly once on best prompt)
    print("\n--- Running Final Evaluation ---")
    final_dir = os.path.join(run_dir, "final")
    os.makedirs(final_dir, exist_ok=True)

    final_score, final_results, final_err = evaluate_split(
        args.runner, best_prompt, final_cases, args.repeats
    )
    save_jsonl_results(os.path.join(final_dir, "final.jsonl"), final_results)
    if final_err:
        print(f"Error: Final evaluation failed at stage '{final_err['stage']}': {final_err['message']}", file=sys.stderr)
        final_score_str = f"FAILED ({final_err['stage']}: {final_err['message']})"
    else:
        final_score_str = f"{final_score:.1f}"

    print(f"Final Score: {final_score_str}")

    # Step 5: Generate summary.md
    summary_lines = []
    if args.limit is not None:
        summary_lines.append("LIMITED SMOKE RUN — NOT A FULL EVALUATION\n")

    summary_lines.extend(
        [
            "# Prompt Hillclimb",
            "",
            f"Runner: {args.runner}",
            f"Rounds attempted: {args.rounds}",
            f"Repeats: {args.repeats}",
            f"Min gain: {args.min_gain}",
            "",
            "## Baseline",
            "",
            f"Train: {train_score:.1f}",
            f"Val: {val_score:.1f}",
            "",
        ]
    )

    for s in round_summaries:
        summary_lines.append(f"## Round {s['round']}")
        summary_lines.append("")
        if s.get("status") == "INVALID":
            summary_lines.append("Status: INVALID")
            summary_lines.append(f"Reason: {s.get('reason', 'unknown')}")
            summary_lines.append("Decision: REVERT")
        else:
            summary_lines.append(f"Train: {s['train']:.1f}")
            summary_lines.append(f"Val: {s['val']:.1f}")
            gain_val = s["gain"]
            summary_lines.append(f"Gain: {gain_val:+.1f}")
            summary_lines.append(f"Decision: {s['decision']}")
        summary_lines.append("")

    summary_lines.extend(
        [
            "## Best",
            "",
            f"Train: {best_train_score:.1f}",
            f"Val: {best_val_score:.1f}",
            "",
            "## Final",
            "",
            f"Final: {final_score_str}",
            "",
            "Best prompt:",
            "best-prompt.md",
            "",
        ]
    )

    summary_content = "\n".join(summary_lines)
    with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(summary_content)

    print("\n" + summary_content)
    print(f"Outputs written to: {run_dir}")

    # Return non-zero if final evaluation failed
    if final_err is not None:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
