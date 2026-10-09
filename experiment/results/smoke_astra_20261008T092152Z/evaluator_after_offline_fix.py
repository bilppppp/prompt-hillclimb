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
import xml.etree.ElementTree as ET
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
    """Resolve the preferred command to run pytest cleanly."""
    env_cmd = os.environ.get("PYTEST_CMD")
    if env_cmd:
        return env_cmd.split()

    repo_root = Path(__file__).resolve().parent.parent.parent
    exp_venv_py = repo_root / "experiment" / ".venv" / "bin" / "python"
    if exp_venv_py.is_file() and os.access(str(exp_venv_py), os.X_OK):
        return [str(exp_venv_py), "-B", "-m", "pytest"]

    return [sys.executable, "-B", "-m", "pytest"]


def parse_pytest_summary(stdout: str) -> dict[str, int]:
    """Extract pass/fail/error/skip counts from pytest stdout fallback."""
    counts = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "total": 0,
    }

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


def parse_junit_xml(xml_path: Path) -> dict[str, Any]:
    """Parse pytest JUnit XML into structured test case details and counts."""
    result: dict[str, Any] = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "total": 0,
        "test_cases": [],
        "parsed_successfully": False,
    }
    if not xml_path.is_file():
        return result

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        test_cases: list[dict[str, Any]] = []

        for tc in root.iter("testcase"):
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            time_str = tc.get("time", "0.0")
            try:
                time_val = float(time_str)
            except ValueError:
                time_val = 0.0
            file_val = tc.get("file", "")

            failure = tc.find("failure")
            error = tc.find("error")
            skipped = tc.find("skipped")

            if failure is not None:
                status = "failed"
                msg = failure.get("message", "") or (failure.text or "")
            elif error is not None:
                status = "error"
                msg = error.get("message", "") or (error.text or "")
            elif skipped is not None:
                status = "skipped"
                msg = skipped.get("message", "") or (skipped.text or "")
            else:
                status = "passed"
                msg = ""

            nodeid = f"{file_val}::{name}" if file_val else f"{classname}::{name}"
            test_cases.append({
                "classname": classname,
                "name": name,
                "nodeid": nodeid,
                "status": status,
                "time": time_val,
                "message": msg.strip()[:500],
            })
            result[status] += 1

        result["total"] = len(test_cases)
        result["test_cases"] = test_cases
        result["parsed_successfully"] = True
    except Exception:
        result["parsed_successfully"] = False

    return result


def canonical_test_id(nid: str) -> str:
    """Normalize test node ID into a canonical comparison string.

    Handles:
    - Path format: 'tests/test_parser.py::test_foo'
    - Windows path format: r'tests\test_parser.py::test_foo'
    - Dotted format: 'tests.test_parser::test_foo'
    - Relative prefixes: './tests/test_parser.py::test_foo'
    - Classes: 'tests/test_parser.py::TestClass::test_foo' vs 'tests.test_parser.TestClass::test_foo'
    - Parameterized tests: '...::test_foo[arg]'
    """
    if not nid or not isinstance(nid, str):
        return ""
    s = nid.strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    s = s.lstrip("/")
    parts = s.split("::")
    mod_or_file = parts[0]
    if mod_or_file.endswith(".py"):
        mod_or_file = mod_or_file[:-3]
    mod_or_file = mod_or_file.replace("/", ".")
    remaining = parts[1:]
    tokens = [t for t in mod_or_file.split(".") if t] + [p for p in remaining if p]
    return "::".join(tokens)


def classify_pytest_exit(exit_code: int) -> tuple[bool, str | None]:
    """Classify exit code into (is_evaluation_error, error_type)."""
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


def extract_mechanism_candidates(diff_text: str, modified_files: list[str], added_files: list[str]) -> list[str]:
    """Extract factual mechanism additions from non-test files without subjective evaluation."""
    candidates: list[str] = []
    for f in added_files:
        if not f.startswith("tests/") and "test" not in Path(f).name:
            candidates.append(f"new_source_file:{f}")

    for line in diff_text.splitlines():
        if line.startswith("+class ") and not line.startswith("+++"):
            name = line.split("class ")[1].split("(")[0].split(":")[0].strip()
            if name:
                candidates.append(f"added_class:{name}")
        elif line.startswith("+def ") and not line.startswith("+++") and not line.startswith("+    "):
            name = line.split("def ")[1].split("(")[0].split(":")[0].strip()
            if name:
                candidates.append(f"added_top_level_function:{name}")
    return sorted(set(candidates))


def compute_repo_diff(
    baseline_path: Path,
    repo_path: Path,
) -> dict[str, Any]:
    """Deterministically compute file, LOC, test modification, and mechanism facts."""
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
    binary_files: list[str] = []
    diff_lines: list[str] = []
    lines_added = 0
    lines_deleted = 0

    test_lines_added = 0
    test_lines_deleted = 0
    source_lines_added = 0
    source_lines_deleted = 0

    for rel_path in all_keys:
        old_bytes = baseline_files[rel_path].read_bytes() if rel_path in baseline_files else b""
        new_bytes = repo_files[rel_path].read_bytes() if rel_path in repo_files else b""
        is_test_file = rel_path.startswith("tests/") or "test" in Path(rel_path).name

        if b"\x00" in old_bytes or b"\x00" in new_bytes:
            if old_bytes == new_bytes and rel_path in baseline_files and rel_path in repo_files:
                continue
            if rel_path not in baseline_files:
                added_files.append(rel_path)
            elif rel_path not in repo_files:
                deleted_files.append(rel_path)
            else:
                modified_files.append(rel_path)
            binary_files.append(rel_path)
            diff_lines.append(f"Binary files a/{rel_path} and b/{rel_path} differ\n")
            continue

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
            d_count = sum(1 for line in file_diff if line.startswith("-") and not line.startswith("---"))
            lines_deleted += d_count
            if is_test_file:
                test_lines_deleted += d_count
            else:
                source_lines_deleted += d_count

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
            a_count = sum(1 for line in file_diff if line.startswith("+") and not line.startswith("+++"))
            lines_added += a_count
            if is_test_file:
                test_lines_added += a_count
            else:
                source_lines_added += a_count

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
                a_count = sum(1 for line in file_diff if line.startswith("+") and not line.startswith("+++"))
                d_count = sum(1 for line in file_diff if line.startswith("-") and not line.startswith("---"))
                lines_added += a_count
                lines_deleted += d_count
                if is_test_file:
                    test_lines_added += a_count
                    test_lines_deleted += d_count
                else:
                    source_lines_added += a_count
                    source_lines_deleted += d_count

    unified_diff = "".join(diff_lines)
    tests_edited = [f for f in modified_files if f.startswith("tests/") or "test" in Path(f).name]
    source_files_modified = [f for f in modified_files if f.endswith(".py") and f not in tests_edited]
    mechanism_candidates = extract_mechanism_candidates(unified_diff, modified_files, added_files)

    return {
        "modified_files": modified_files,
        "added_files": added_files,
        "deleted_files": deleted_files,
        "binary_files": binary_files,
        "tests_edited": tests_edited,
        "source_files_modified": source_files_modified,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "net_loc_change": lines_added - lines_deleted,
        "test_lines_added": test_lines_added,
        "test_lines_deleted": test_lines_deleted,
        "source_lines_added": source_lines_added,
        "source_lines_deleted": source_lines_deleted,
        "mechanism_candidates": mechanism_candidates,
        "unified_diff": unified_diff,
    }


def resolve_manifest_and_paths(
    evaluator_dir: Path,
    project_root: Path,
    manifest_path: str | Path | None = None,
    baseline_path: str | Path | None = None,
    fixture_id: str | None = None,
    repo_path: str | Path | None = None,
) -> tuple[Path, dict[str, Any], Path, str]:
    """Generalize manifest and baseline resolution without hardcoding T02."""
    manifests_dir = evaluator_dir / "manifests"

    # 1. Determine target fixture ID if not explicitly provided
    resolved_fixture_id = fixture_id
    if not resolved_fixture_id and repo_path:
        p_str = str(repo_path)
        m = re.search(r"/(T\d{2})(/|$)", p_str)
        if m:
            resolved_fixture_id = m.group(1)

    # 2. Determine manifest file
    chosen_manifest_file: Path | None = None
    if manifest_path is not None:
        chosen_manifest_file = Path(manifest_path).resolve()
    elif resolved_fixture_id:
        cand1 = manifests_dir / f"{resolved_fixture_id}_manifest.json"
        cand2 = manifests_dir / f"{resolved_fixture_id}.json"
        if cand1.is_file():
            chosen_manifest_file = cand1
        elif cand2.is_file():
            chosen_manifest_file = cand2

    if chosen_manifest_file is None or not chosen_manifest_file.is_file():
        # Fallback to T02_manifest.json if exists
        default_t02 = manifests_dir / "T02_manifest.json"
        if default_t02.is_file():
            chosen_manifest_file = default_t02
        else:
            # Pick any first manifest in directory
            any_manifests = sorted(manifests_dir.glob("*_manifest.json"))
            if any_manifests:
                chosen_manifest_file = any_manifests[0]
            else:
                chosen_manifest_file = default_t02

    # Load manifest content, resolving $ref if present
    manifest_data: dict[str, Any] = {}
    if chosen_manifest_file.is_file():
        with open(chosen_manifest_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        if "$ref" in raw_data:
            ref_path = (chosen_manifest_file.parent / raw_data["$ref"]).resolve()
            if ref_path.is_file():
                with open(ref_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
            else:
                manifest_data = raw_data
        else:
            manifest_data = raw_data

    actual_fixture_id = manifest_data.get("fixture_id") or resolved_fixture_id or "T02"

    # 3. Determine baseline path
    chosen_baseline: Path
    if baseline_path is not None:
        chosen_baseline = Path(baseline_path).resolve()
    else:
        # Search in experiment/fixtures/core/{fixture_id}/repo
        cand_base1 = project_root / "experiment" / "fixtures" / "core" / actual_fixture_id / "repo"
        cand_base2 = project_root / "experiment" / "fixtures" / actual_fixture_id / "repo"
        if cand_base1.is_dir():
            chosen_baseline = cand_base1
        elif cand_base2.is_dir():
            chosen_baseline = cand_base2
        else:
            chosen_baseline = cand_base1

    return chosen_manifest_file, manifest_data, chosen_baseline, actual_fixture_id


class DeterministicEvaluator:
    """Evaluates repositories deterministically with strict environment isolation.

    All pytest runs are executed within an isolated snapshot copy of the tested repository.
    The tested repository itself is never modified, deleted from, or polluted with caches.
    """

    def __init__(
        self,
        manifest_path: str | Path | None = None,
        baseline_path: str | Path | None = None,
        fixture_id: str | None = None,
        pytest_cmd: Sequence[str] | str | None = None,
    ) -> None:
        self.evaluator_dir = Path(__file__).resolve().parent
        self.project_root = self.evaluator_dir.parent.parent

        m_file, m_data, b_path, f_id = resolve_manifest_and_paths(
            evaluator_dir=self.evaluator_dir,
            project_root=self.project_root,
            manifest_path=manifest_path,
            baseline_path=baseline_path,
            fixture_id=fixture_id,
        )
        self.manifest_path = m_file
        self.manifest = m_data
        self.baseline_path = b_path
        self.fixture_id = f_id

        if isinstance(pytest_cmd, str):
            self.pytest_cmd = pytest_cmd.split()
        elif pytest_cmd is not None:
            self.pytest_cmd = list(pytest_cmd)
        else:
            self.pytest_cmd = resolve_python_pytest()

        self._cached_baseline_test_cases: list[dict[str, Any]] | None = None

    def _run_single_test_command(
        self,
        snapshot_repo: Path,
        test_target: str,
        extra_env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run pytest inside snapshot_repo with JUnit XML and clean isolation."""
        with tempfile.TemporaryDirectory() as temp_cache_dir:
            temp_cache_path = Path(temp_cache_dir)
            junit_xml_path = temp_cache_path / "junit_report.xml"

            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            env.pop("PYTEST_ADDOPTS", None)
            env.pop("PYTEST_PLUGINS", None)

            cur_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{snapshot_repo}:{cur_pythonpath}" if cur_pythonpath else str(snapshot_repo)
            if extra_env:
                env.update(extra_env)

            cmd = [
                *self.pytest_cmd,
                "-p",
                "no:cacheprovider",
                "-q",
                "--tb=short",
                f"--junitxml={junit_xml_path}",
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
                stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr = f"Test execution timed out after 60s: {exc.stderr or ''}"
            except Exception as exc:
                duration = time.time() - start_time
                exit_code = 255
                stdout = ""
                stderr = f"Subprocess invocation error: {exc}"

            junit_res = parse_junit_xml(junit_xml_path)
            if junit_res["parsed_successfully"] and junit_res["total"] > 0:
                counts = {
                    "passed": junit_res["passed"],
                    "failed": junit_res["failed"],
                    "errors": junit_res["errors"],
                    "skipped": junit_res["skipped"],
                    "total": junit_res["total"],
                }
                test_cases = junit_res["test_cases"]
            else:
                counts = parse_pytest_summary(stdout)
                test_cases = []

            is_eval_error, error_type = classify_pytest_exit(exit_code)
            assertion_failure = (exit_code == 1)

            return {
                "test_target": test_target,
                "exit_code": exit_code,
                "duration_seconds": round(duration, 4),
                "counts": counts,
                "test_cases": test_cases,
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

        # If fixture_id was not explicitly specified at init, re-check if manifest needs dynamic matching
        if not self.manifest:
            m_file, m_data, b_path, f_id = resolve_manifest_and_paths(
                evaluator_dir=self.evaluator_dir,
                project_root=self.project_root,
                manifest_path=self.manifest_path,
                baseline_path=self.baseline_path,
                fixture_id=self.fixture_id,
                repo_path=repo_path,
            )
            self.manifest_path = m_file
            self.manifest = m_data
            self.baseline_path = b_path
            self.fixture_id = f_id

        # 1. Resolve test paths and manifest definitions
        verif = self.manifest.get("verification_definitions", {})
        target_test = verif.get("target_test", "tests/test_parser.py::test_parse_header_with_none_value")
        visible_suite = verif.get("visible_test_suite", "tests/test_parser.py")

        hidden_rel = verif.get("hidden_test_suite_relpath", "hidden_tests/test_parser_hidden.py")
        hidden_suite_path = (self.evaluator_dir / hidden_rel).resolve()

        expected_counts = verif.get("expected_counts", {})
        exp_target = expected_counts.get("target_test", {"total": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0})
        exp_visible = expected_counts.get("visible_suite", {"total": 5, "passed": 5, "failed": 0, "skipped": 0, "errors": 0})
        exp_hidden = expected_counts.get("hidden_suite", {"total": 6, "passed": 6, "failed": 0, "skipped": 0, "errors": 0})

        # 2. Run all tests inside an isolated snapshot copy of repo_path
        with tempfile.TemporaryDirectory() as snapshot_dir:
            snapshot_repo = Path(snapshot_dir) / "repo_snapshot"
            shutil.copytree(repo_path, snapshot_repo)

            target_res = self._run_single_test_command(snapshot_repo, target_test)
            visible_res = self._run_single_test_command(snapshot_repo, visible_suite)
            hidden_res = self._run_single_test_command(snapshot_repo, str(hidden_suite_path))

            # Isolated baseline visible suite execution/collection if baseline directory is valid
            baseline_visible_test_cases: list[dict[str, Any]] = []
            if self._cached_baseline_test_cases is not None:
                baseline_visible_test_cases = self._cached_baseline_test_cases
            elif self.baseline_path and self.baseline_path.is_dir():
                try:
                    snapshot_baseline = Path(snapshot_dir) / "baseline_snapshot"
                    if not snapshot_baseline.exists():
                        shutil.copytree(self.baseline_path, snapshot_baseline)
                    base_res = self._run_single_test_command(snapshot_baseline, visible_suite)
                    if base_res.get("test_cases"):
                        self._cached_baseline_test_cases = base_res["test_cases"]
                        baseline_visible_test_cases = base_res["test_cases"]
                except Exception:
                    baseline_visible_test_cases = []

        # 3. Compute code and LOC diff on original repo_path against baseline
        diff_info = compute_repo_diff(self.baseline_path, repo_path)

        # 4. Rigorous verification:
        # A. Target test passed: exit 0, no evaluation_error, passed >= exp_target['passed'], no fail/skip/error
        target_counts = target_res["counts"]
        target_test_passed = (
            target_res["exit_code"] == 0
            and not target_res["evaluation_error"]
            and target_counts["passed"] >= exp_target.get("passed", 1)
            and target_counts["failed"] == 0
            and target_counts["skipped"] == 0
            and target_counts["errors"] == 0
        )

        # B. Visible suite passed:
        #    Allow new tests! Do NOT fail simply because passed > initial expected.
        #    Must pass all required baseline tests with no fail/error.
        visible_counts = visible_res["counts"]
        exp_vis_passed = exp_visible.get("passed", 5)
        exp_vis_total = exp_visible.get("total", 5)
        visible_suite_passed = (
            visible_res["exit_code"] == 0
            and not visible_res["evaluation_error"]
            and visible_counts["passed"] >= exp_vis_passed
            and visible_counts["failed"] == 0
            and visible_counts["errors"] == 0
            and visible_counts["skipped"] <= exp_visible.get("skipped", 0)
            and visible_counts["total"] >= exp_vis_total
        )

        # C. Hidden suite passed:
        #    Hidden expected must have fixed reliable quantity. Disallow skipping all tests to count as pass!
        hidden_counts = hidden_res["counts"]
        exp_hid_total = exp_hidden.get("total", 6)
        exp_hid_passed = exp_hidden.get("passed", exp_hid_total)
        hidden_suite_passed = (
            hidden_res["exit_code"] == 0
            and not hidden_res["evaluation_error"]
            and exp_hid_total > 0
            and hidden_counts["total"] >= exp_hid_total
            and hidden_counts["passed"] == exp_hid_passed
            and hidden_counts["failed"] == 0
            and hidden_counts["skipped"] == 0
            and hidden_counts["errors"] == 0
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

        # Build comprehensive baseline identity set (both passing & failing initial tests)
        manifest_baseline_ids: list[str] = []
        for item in verif.get("expected_initial_passing_visible", []):
            if item and isinstance(item, str):
                manifest_baseline_ids.append(item)
        for item in verif.get("expected_initial_failing_visible", []):
            if item and isinstance(item, str) and item not in manifest_baseline_ids:
                manifest_baseline_ids.append(item)
        if target_test and isinstance(target_test, str) and target_test not in manifest_baseline_ids:
            manifest_baseline_ids.append(target_test)

        baseline_raw_nodeids = set(manifest_baseline_ids)
        for tc in baseline_visible_test_cases:
            if tc.get("nodeid"):
                baseline_raw_nodeids.add(tc["nodeid"])

        canonical_baseline = {
            canonical_test_id(nid) for nid in baseline_raw_nodeids if nid
        }

        repo_test_nodeids = [tc["nodeid"] for tc in visible_res.get("test_cases", [])]
        added_tests_list = [
            nid for nid in repo_test_nodeids
            if nid not in baseline_raw_nodeids
            and canonical_test_id(nid) not in canonical_baseline
        ]

        if visible_res.get("test_cases"):
            added_visible_tests_count = max(len(added_tests_list), max(0, visible_counts["total"] - exp_vis_total))
        else:
            added_visible_tests_count = max(0, visible_counts["total"] - exp_vis_total)

        result: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fixture_id": self.manifest.get("fixture_id", self.fixture_id),
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
                    "test_cases": target_res.get("test_cases", []),
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
                    "test_cases": visible_res.get("test_cases", []),
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
                    "test_cases": hidden_res.get("test_cases", []),
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
                "tests_edited": diff_info["tests_edited"],
                "added_visible_tests_count": added_visible_tests_count,
                "added_test_cases": added_tests_list,
                "lines_added": diff_info["lines_added"],
                "lines_deleted": diff_info["lines_deleted"],
                "net_loc_change": diff_info["net_loc_change"],
                "binary_files": diff_info["binary_files"],
                "mechanism_candidates": diff_info["mechanism_candidates"],
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
    fixture_id: str | None = None,
    pytest_cmd: Sequence[str] | str | None = None,
    agent_run_info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Public functional API to run deterministic evaluation."""
    evaluator = DeterministicEvaluator(
        manifest_path=manifest_path,
        baseline_path=baseline_path,
        fixture_id=fixture_id,
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
        help="Path to fixture manifest (defaults to auto-detected or T02_manifest.json).",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Path to untouched baseline fixture repo for diff comparison.",
    )
    parser.add_argument(
        "--fixture-id",
        default=None,
        help="Explicit fixture identifier (e.g. T01, T02).",
    )

    args = parser.parse_args()

    try:
        res = evaluate(
            repo_path=args.repo,
            artifact_path=args.artifact,
            manifest_path=args.manifest,
            baseline_path=args.baseline,
            fixture_id=args.fixture_id,
        )
    except Exception as exc:
        sys.stderr.write(f"Evaluator error: {exc}\n")
        return 2

    summary = res["summary"]
    print("=== Deterministic Evaluation Report ===")
    print(f"Fixture:              {res['fixture_id']}")
    print(f"Target Test Passed:   {summary['target_test_passed']}")
    print(f"Visible Suite Passed: {summary['visible_suite_passed']}")
    print(f"Hidden Suite Passed:  {summary['hidden_suite_passed']}")
    print(f"Evaluation Error:     {summary['has_evaluation_error']}")
    print(f"All Tests Passed:     {summary['all_tests_passed']}")
    print(f"Code Modified:        {summary['modified_files_count']} files (+{summary['lines_added']} / -{summary['lines_deleted']}, net {summary['net_loc_change']} LOC)")
    if summary["tests_edited"]:
        print(f"Tests Edited:         {', '.join(summary['tests_edited'])}")
    if summary["added_visible_tests_count"] > 0:
        print(f"New Tests Added:      {summary['added_visible_tests_count']}")
    if "artifact_saved_to" in res:
        print(f"Artifact written to:  {res['artifact_saved_to']}")

    return 0 if summary["all_tests_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
