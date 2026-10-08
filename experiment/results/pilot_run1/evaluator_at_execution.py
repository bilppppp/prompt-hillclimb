"""Deterministic evaluator for experiment fixtures.

Evaluates a tested repository against visible target tests, full visible suites,
and external hidden test suites without modifying or polluting the tested repository.
Records factual test outcomes and code/LOC diffs deterministically without subjective scoring.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


_IGNORED_DIFF_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    ".mypy_cache",
    ".tox",
    ".ruff_cache",
}

_IGNORED_DIFF_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".DS_Store",
}


def resolve_python_pytest() -> list[str]:
    """Resolve the preferred command to run pytest cleanly.

    Checks:
    1. Environment variable PYTEST_CMD
    2. experiment/.venv/bin/python
    3. sys.executable
    4. 'pytest' in PATH
    """
    env_cmd = os.environ.get("PYTEST_CMD")
    if env_cmd:
        return env_cmd.split()

    # Check experiment/.venv/bin/python
    repo_root = Path(__file__).resolve().parent.parent.parent
    exp_venv_py = repo_root / "experiment" / ".venv" / "bin" / "python"
    if exp_venv_py.is_file() and os.access(str(exp_venv_py), os.X_OK):
        return [str(exp_venv_py), "-B", "-m", "pytest"]

    # Fallback to sys.executable -B -m pytest
    return [sys.executable, "-B", "-m", "pytest"]


def parse_pytest_summary(stdout: str) -> dict[str, int]:
    """Extract pass/fail/error/skip counts from pytest output."""
    counts = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "total": 0,
    }

    # Matches summary line like: "1 failed, 4 passed, 1 warning in 0.05s"
    # or "6 passed in 0.02s" or "2 skipped, 4 passed"
    for match in re.finditer(r"(\d+)\s+(passed|failed|error(?:s)?|skipped)", stdout):
        count = int(match.group(1))
        key = match.group(2)
        if key == "passed":
            counts["passed"] += count
        elif key == "failed":
            counts["failed"] += count
        elif key.startswith("error"):
            counts["errors"] += count
        elif key == "skipped":
            counts["skipped"] += count

    counts["total"] = counts["passed"] + counts["failed"] + counts["errors"] + counts["skipped"]
    return counts


def classify_pytest_exit(exit_code: int) -> tuple[bool, str | None]:
    """Classify exit code into (is_evaluation_error, error_type).

    pytest exit codes:
      0: All tests passed
      1: Tests were collected and run but some failed (normal assertion failure)
      2: Test execution was interrupted by user
      3: Internal error happened
      4: Command line usage error
      5: No tests were collected
      124: Subprocess timeout
      255: Subprocess execution exception
    """
    if exit_code in (0, 1):
        return False, None
    elif exit_code == 2:
        return True, "INTERRUPTED"
    elif exit_code == 3:
        return True, "INTERNAL_ERROR"
    elif exit_code == 4:
        return True, "USAGE_ERROR"
    elif exit_code == 5:
        return True, "NO_TESTS_COLLECTED"
    elif exit_code == 124:
        return True, "TIMEOUT"
    elif exit_code == 255:
        return True, "SUBPROCESS_ERROR"
    return True, f"UNKNOWN_EXIT_{exit_code}"


def compute_repo_diff(
    baseline_path: Path,
    repo_path: Path,
) -> dict[str, Any]:
    """Deterministically compute file and LOC changes between baseline and repo."""
    baseline_path = baseline_path.resolve()
    repo_path = repo_path.resolve()

    def get_file_map(base_dir: Path) -> dict[str, Path]:
        mapping: dict[str, Path] = {}
        if not base_dir.exists():
            return mapping
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d not in _IGNORED_DIFF_DIRS]
            for f in files:
                if any(f.endswith(ext) for ext in _IGNORED_DIFF_EXTENSIONS):
                    continue
                full_path = Path(root) / f
                rel_path = full_path.relative_to(base_dir).as_posix()
                mapping[rel_path] = full_path
        return mapping

    baseline_files = get_file_map(baseline_path)
    repo_files = get_file_map(repo_path)

    all_keys = sorted(set(baseline_files.keys()) | set(repo_files.keys()))

    modified_files: list[str] = []
    added_files: list[str] = []
    deleted_files: list[str] = []
    diff_lines: list[str] = []
    lines_added = 0
    lines_deleted = 0

    for rel_path in all_keys:
        if rel_path in baseline_files and rel_path not in repo_files:
            deleted_files.append(rel_path)
            old_lines = baseline_files[rel_path].read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            file_diff = list(
                difflib.unified_diff(
                    old_lines,
                    [],
                    fromfile=f"a/{rel_path}",
                    tofile="/dev/null",
                )
            )
            diff_lines.extend(file_diff)
            lines_deleted += sum(1 for line in file_diff if line.startswith("-") and not line.startswith("---"))
        elif rel_path not in baseline_files and rel_path in repo_files:
            added_files.append(rel_path)
            new_lines = repo_files[rel_path].read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            file_diff = list(
                difflib.unified_diff(
                    [],
                    new_lines,
                    fromfile="/dev/null",
                    tofile=f"b/{rel_path}",
                )
            )
            diff_lines.extend(file_diff)
            lines_added += sum(1 for line in file_diff if line.startswith("+") and not line.startswith("+++"))
        else:
            old_lines = baseline_files[rel_path].read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            new_lines = repo_files[rel_path].read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            if old_lines != new_lines:
                modified_files.append(rel_path)
                file_diff = list(
                    difflib.unified_diff(
                        old_lines,
                        new_lines,
                        fromfile=f"a/{rel_path}",
                        tofile=f"b/{rel_path}",
                    )
                )
                diff_lines.extend(file_diff)
                lines_added += sum(1 for line in file_diff if line.startswith("+") and not line.startswith("+++"))
                lines_deleted += sum(1 for line in file_diff if line.startswith("-") and not line.startswith("---"))

    return {
        "modified_files": modified_files,
        "added_files": added_files,
        "deleted_files": deleted_files,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "net_loc_change": lines_added - lines_deleted,
        "unified_diff": "".join(diff_lines),
    }


class DeterministicEvaluator:
    """Evaluates repositories deterministically with strict environment isolation.

    All pytest runs are executed within an isolated snapshot copy of the tested repository.
    The tested repository itself is never modified, deleted from, or polluted with caches.
    """

    def __init__(
        self,
        manifest_path: str | Path | None = None,
        baseline_path: str | Path | None = None,
        pytest_cmd: Sequence[str] | str | None = None,
    ) -> None:
        evaluator_dir = Path(__file__).resolve().parent
        project_root = evaluator_dir.parent.parent

        if manifest_path is None:
            self.manifest_path = evaluator_dir / "manifests" / "T02_manifest.json"
        else:
            self.manifest_path = Path(manifest_path).resolve()

        if baseline_path is None:
            self.baseline_path = project_root / "experiment" / "fixtures" / "core" / "T02" / "repo"
        else:
            self.baseline_path = Path(baseline_path).resolve()

        if isinstance(pytest_cmd, str):
            self.pytest_cmd = pytest_cmd.split()
        elif pytest_cmd is not None:
            self.pytest_cmd = list(pytest_cmd)
        else:
            self.pytest_cmd = resolve_python_pytest()

        self.manifest: dict[str, Any] = {}
        if self.manifest_path.exists():
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                self.manifest = json.load(f)

    def _run_single_test_command(
        self,
        snapshot_repo: Path,
        test_target: str,
        extra_env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run pytest inside snapshot_repo with strict bytecode and cache isolation."""
        with tempfile.TemporaryDirectory() as temp_cache_dir:
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONUNBUFFERED"] = "1"
            # Ensure snapshot_repo is at the front of PYTHONPATH
            cur_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{snapshot_repo}:{cur_pythonpath}" if cur_pythonpath else str(snapshot_repo)
            if extra_env:
                env.update(extra_env)

            cmd = [
                *self.pytest_cmd,
                "-p",
                "no:cacheprovider",
                "-o",
                f"cache_dir={temp_cache_dir}",
                "-q",
                "--tb=short",
                test_target,
            ]

            start_time = time.time()
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(snapshot_repo),
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=60,
                )
                duration = time.time() - start_time
                exit_code = proc.returncode
                stdout = proc.stdout
                stderr = proc.stderr
            except subprocess.TimeoutExpired as exc:
                duration = time.time() - start_time
                exit_code = 124
                stdout = exc.stdout or ""
                stderr = f"Test execution timed out after 60s: {exc.stderr or ''}"
            except Exception as exc:
                duration = time.time() - start_time
                exit_code = 255
                stdout = ""
                stderr = f"Subprocess invocation error: {exc}"

            counts = parse_pytest_summary(stdout)
            is_eval_error, error_type = classify_pytest_exit(exit_code)
            assertion_failure = (exit_code == 1)

            return {
                "test_target": test_target,
                "exit_code": exit_code,
                "duration_seconds": round(duration, 4),
                "counts": counts,
                "evaluation_error": is_eval_error,
                "error_type": error_type,
                "assertion_failure": assertion_failure,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            }

    def evaluate(
        self,
        repo_path: str | Path,
        artifact_path: str | Path | None = None,
        agent_run_info: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform deterministic evaluation on the target repository.

        The original repo_path is inspected for diffs but NEVER modified or deleted from.
        All pytest runs execute inside an isolated temporary snapshot copy.
        """
        repo_path = Path(repo_path).resolve()
        if not repo_path.is_dir():
            raise FileNotFoundError(f"Target repository directory does not exist: {repo_path}")

        # 1. Resolve test paths and manifest definitions
        verif = self.manifest.get("verification_definitions", {})
        target_test = verif.get("target_test", "tests/test_parser.py::test_parse_header_with_none_value")
        visible_suite = verif.get("visible_test_suite", "tests/test_parser.py")

        hidden_rel = verif.get("hidden_test_suite_relpath", "hidden_tests/test_parser_hidden.py")
        evaluator_dir = Path(__file__).resolve().parent
        hidden_suite_path = (evaluator_dir / hidden_rel).resolve()

        expected_counts = verif.get("expected_counts", {})
        exp_target = expected_counts.get("target_test", {"total": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0})
        exp_visible = expected_counts.get("visible_suite", {"total": 5, "passed": 5, "failed": 0, "skipped": 0, "errors": 0})
        exp_hidden = expected_counts.get("hidden_suite", {"total": 6, "passed": 6, "failed": 0, "skipped": 0, "errors": 0})

        # 2. Run all tests inside an isolated snapshot copy of repo_path
        #    Original repo_path is never written to, keeping agent evidence intact.
        with tempfile.TemporaryDirectory() as snapshot_dir:
            snapshot_repo = Path(snapshot_dir) / "repo_snapshot"
            shutil.copytree(repo_path, snapshot_repo)

            target_res = self._run_single_test_command(snapshot_repo, target_test)
            visible_res = self._run_single_test_command(snapshot_repo, visible_suite)
            hidden_res = self._run_single_test_command(snapshot_repo, str(hidden_suite_path))

        # 3. Compute code and LOC diff on original repo_path against baseline
        diff_info = compute_repo_diff(self.baseline_path, repo_path)

        # 4. Rigorous verification:
        #    Target test passed: exit 0, no evaluation_error, passed==1, failed==0, skipped==0, errors==0
        target_counts = target_res["counts"]
        target_test_passed = (
            target_res["exit_code"] == 0
            and not target_res["evaluation_error"]
            and target_counts["passed"] == exp_target["passed"]
            and target_counts["failed"] == 0
            and target_counts["skipped"] == 0
            and target_counts["errors"] == 0
        )

        #    Visible suite passed: exit 0, no evaluation_error, passed==exp_visible['passed'], no fail/skip/error
        visible_counts = visible_res["counts"]
        visible_suite_passed = (
            visible_res["exit_code"] == 0
            and not visible_res["evaluation_error"]
            and visible_counts["passed"] == exp_visible["passed"]
            and visible_counts["failed"] == 0
            and visible_counts["skipped"] == 0
            and visible_counts["errors"] == 0
            and visible_counts["total"] == exp_visible["total"]
        )

        #    Hidden suite passed: must be strictly 6/6 passed, exit 0, no evaluation_error, no skip/error
        hidden_counts = hidden_res["counts"]
        hidden_suite_passed = (
            hidden_res["exit_code"] == 0
            and not hidden_res["evaluation_error"]
            and hidden_counts["passed"] == exp_hidden["passed"]
            and hidden_counts["failed"] == 0
            and hidden_counts["skipped"] == 0
            and hidden_counts["errors"] == 0
            and hidden_counts["total"] == exp_hidden["total"]
        )

        has_eval_error = bool(
            target_res["evaluation_error"]
            or visible_res["evaluation_error"]
            or hidden_res["evaluation_error"]
        )

        eval_errors: list[dict[str, Any]] = []
        for stage, r in [("target_test", target_res), ("visible_suite", visible_res), ("hidden_suite", hidden_res)]:
            if r["evaluation_error"]:
                eval_errors.append({
                    "stage": stage,
                    "error_type": r["error_type"],
                    "exit_code": r["exit_code"],
                    "stderr": r["stderr"],
                })

        all_tests_passed = (
            target_test_passed
            and visible_suite_passed
            and hidden_suite_passed
            and not has_eval_error
        )

        has_code_changes = bool(
            diff_info["modified_files"] or diff_info["added_files"] or diff_info["deleted_files"]
        )

        result: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fixture_id": self.manifest.get("fixture_id", "T02"),
            "repo_path": str(repo_path),
            "baseline_path": str(self.baseline_path),
            "evaluator_run": {
                "target_test": {
                    "target": target_test,
                    "passed": target_test_passed,
                    "exit_code": target_res["exit_code"],
                    "evaluation_error": target_res["evaluation_error"],
                    "error_type": target_res["error_type"],
                    "assertion_failure": target_res["assertion_failure"],
                    "duration_seconds": target_res["duration_seconds"],
                    "summary_counts": target_counts,
                    "stdout": target_res["stdout"],
                    "stderr": target_res["stderr"],
                },
                "visible_suite": {
                    "suite": visible_suite,
                    "passed": visible_suite_passed,
                    "exit_code": visible_res["exit_code"],
                    "evaluation_error": visible_res["evaluation_error"],
                    "error_type": visible_res["error_type"],
                    "assertion_failure": visible_res["assertion_failure"],
                    "duration_seconds": visible_res["duration_seconds"],
                    "summary_counts": visible_counts,
                    "stdout": visible_res["stdout"],
                    "stderr": visible_res["stderr"],
                },
                "hidden_suite": {
                    "suite": str(hidden_suite_path),
                    "passed": hidden_suite_passed,
                    "exit_code": hidden_res["exit_code"],
                    "evaluation_error": hidden_res["evaluation_error"],
                    "error_type": hidden_res["error_type"],
                    "assertion_failure": hidden_res["assertion_failure"],
                    "duration_seconds": hidden_res["duration_seconds"],
                    "summary_counts": hidden_counts,
                    "stdout": hidden_res["stdout"],
                    "stderr": hidden_res["stderr"],
                },
            },
            "agent_run": {
                "recorded": agent_run_info is not None,
                "agent_details": agent_run_info or {},
                "note": "Evaluator runs visible and hidden tests independently in an isolated snapshot from any agent execution.",
            },
            "code_changes": diff_info,
            "summary": {
                "target_test_passed": target_test_passed,
                "visible_suite_passed": visible_suite_passed,
                "hidden_suite_passed": hidden_suite_passed,
                "has_evaluation_error": has_eval_error,
                "evaluation_errors": eval_errors,
                "all_tests_passed": all_tests_passed,
                "has_code_changes": has_code_changes,
                "modified_files_count": len(diff_info["modified_files"]),
                "lines_added": diff_info["lines_added"],
                "lines_deleted": diff_info["lines_deleted"],
                "net_loc_change": diff_info["net_loc_change"],
            },
        }

        # 5. Write artifact if requested
        if artifact_path:
            artifact_target = Path(artifact_path).resolve()
            if artifact_target.is_dir() or not artifact_target.suffix:
                artifact_target.mkdir(parents=True, exist_ok=True)
                json_file = artifact_target / "evaluation_result.json"
                patch_file = artifact_target / "changes.patch"
            else:
                artifact_target.parent.mkdir(parents=True, exist_ok=True)
                json_file = artifact_target
                patch_file = artifact_target.parent / f"{artifact_target.stem}.patch"

            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            if diff_info["unified_diff"]:
                with open(patch_file, "w", encoding="utf-8") as f:
                    f.write(diff_info["unified_diff"])

            result["artifact_saved_to"] = str(json_file)

        return result


def evaluate(
    repo_path: str | Path,
    artifact_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    baseline_path: str | Path | None = None,
    pytest_cmd: Sequence[str] | str | None = None,
    agent_run_info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Public functional API to run deterministic evaluation."""
    evaluator = DeterministicEvaluator(
        manifest_path=manifest_path,
        baseline_path=baseline_path,
        pytest_cmd=pytest_cmd,
    )
    return evaluator.evaluate(
        repo_path=repo_path,
        artifact_path=artifact_path,
        agent_run_info=agent_run_info,
    )


# Alias
evaluate_repo = evaluate


def main() -> int:
    """CLI entrypoint for deterministic evaluator."""
    parser = argparse.ArgumentParser(
        description="Deterministic evaluator for experiment fixture repositories."
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Path to the repository under test.",
    )
    parser.add_argument(
        "--artifact",
        default=None,
        help="Path to output artifact file or directory.",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to fixture manifest (defaults to T02_manifest.json).",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Path to untouched baseline fixture repo for diff comparison.",
    )

    args = parser.parse_args()

    try:
        res = evaluate(
            repo_path=args.repo,
            artifact_path=args.artifact,
            manifest_path=args.manifest,
            baseline_path=args.baseline,
        )
    except Exception as exc:
        sys.stderr.write(f"Evaluator error: {exc}\n")
        return 2

    # Print human-readable summary to stdout
    summary = res["summary"]
    print("=== Deterministic Evaluation Report ===")
    print(f"Fixture:              {res['fixture_id']}")
    print(f"Target Test Passed:   {summary['target_test_passed']}")
    print(f"Visible Suite Passed: {summary['visible_suite_passed']}")
    print(f"Hidden Suite Passed:  {summary['hidden_suite_passed']}")
    print(f"Evaluation Error:     {summary['has_evaluation_error']}")
    print(f"All Tests Passed:     {summary['all_tests_passed']}")
    print(f"Code Modified:        {summary['modified_files_count']} files (+{summary['lines_added']} / -{summary['lines_deleted']}, net {summary['net_loc_change']} LOC)")
    if "artifact_saved_to" in res:
        print(f"Artifact written to:  {res['artifact_saved_to']}")

    return 0 if summary["all_tests_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
