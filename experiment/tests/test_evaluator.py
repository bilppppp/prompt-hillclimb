"""Self-check unit and integration tests for deterministic evaluator and T02 fixture."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from experiment.evaluator.evaluator import (
    DeterministicEvaluator,
    compute_repo_diff,
    evaluate,
)

FIXTURE_REPO = PROJECT_ROOT / "experiment" / "fixtures" / "core" / "T02" / "repo"
MANIFEST_PATH = PROJECT_ROOT / "experiment" / "evaluator" / "manifests" / "T02_manifest.json"
VENV_PYTHON = PROJECT_ROOT / "experiment" / ".venv" / "bin" / "python"


class TestT02Evaluator(unittest.TestCase):
    """Test suite verifying evaluator behavior and T02 fixture invariants."""

    def setUp(self) -> None:
        self.assertTrue(FIXTURE_REPO.is_dir(), f"Fixture repo missing: {FIXTURE_REPO}")
        self.assertTrue(MANIFEST_PATH.is_file(), f"Manifest missing: {MANIFEST_PATH}")

    def test_fixture_isolation_invariants(self) -> None:
        """Verify fixture directory does not contain hidden tests, manifests, or caches."""
        # 1. No hidden test files in fixture
        for path in FIXTURE_REPO.rglob("*"):
            self.assertNotIn("hidden", path.name.lower())
            self.assertNotIn("manifest", path.name.lower())
            self.assertNotIn("rubric", path.name.lower())
            self.assertNotIn("__pycache__", str(path))
            self.assertFalse(path.name.endswith(".pyc"))

        # 2. Verify source files count (3 source files + 1 test file)
        src_files = list((FIXTURE_REPO / "kvparser").glob("*.py"))
        self.assertEqual(len(src_files), 3)

        test_files = list((FIXTURE_REPO / "tests").glob("*.py"))
        self.assertEqual(len(test_files), 1)

    def test_baseline_fixture_evaluation(self) -> None:
        """Original fixture must fail target test and hidden test on None bug without execution error."""
        with tempfile.TemporaryDirectory() as artifact_dir:
            res = evaluate(
                repo_path=FIXTURE_REPO,
                artifact_path=artifact_dir,
                manifest_path=MANIFEST_PATH,
            )

            # Target test should fail due to assertion/AttributeError (exit code 1)
            target_res = res["evaluator_run"]["target_test"]
            self.assertFalse(target_res["passed"])
            self.assertEqual(target_res["exit_code"], 1)
            self.assertTrue(target_res["assertion_failure"])
            self.assertFalse(target_res["evaluation_error"])
            self.assertIn("AttributeError", target_res["stdout"])

            # Visible suite should fail target test but pass others
            visible_res = res["evaluator_run"]["visible_suite"]
            self.assertFalse(visible_res["passed"])
            self.assertEqual(visible_res["exit_code"], 1)
            self.assertTrue(visible_res["assertion_failure"])
            self.assertFalse(visible_res["evaluation_error"])
            visible_counts = visible_res["summary_counts"]
            self.assertEqual(visible_counts["failed"], 1)
            self.assertEqual(visible_counts["passed"], 4)

            # Hidden suite should fail on None cases
            hidden_res = res["evaluator_run"]["hidden_suite"]
            self.assertFalse(hidden_res["passed"])
            self.assertEqual(hidden_res["exit_code"], 1)
            self.assertTrue(hidden_res["assertion_failure"])
            self.assertFalse(hidden_res["evaluation_error"])
            hidden_counts = hidden_res["summary_counts"]
            self.assertGreater(hidden_counts["failed"], 0)

            # Overall summary
            self.assertFalse(res["summary"]["all_tests_passed"])
            self.assertFalse(res["summary"]["has_evaluation_error"])
            self.assertFalse(res["summary"]["has_code_changes"])
            self.assertEqual(res["summary"]["modified_files_count"], 0)
            self.assertEqual(res["summary"]["added_test_cases"], [])
            self.assertEqual(res["summary"]["added_visible_tests_count"], 0)

            # Artifact file written
            artifact_file = Path(artifact_dir) / "evaluation_result.json"
            self.assertTrue(artifact_file.is_file())

    def test_minimal_fix_passes_all_tests(self) -> None:
        """After minimal fix in a copied workspace, target test and hidden tests must pass strictly 6/6."""
        with tempfile.TemporaryDirectory() as work_dir:
            temp_repo = Path(work_dir) / "repo"
            shutil.copytree(FIXTURE_REPO, temp_repo)

            # Apply minimal fix: handle None in clean_value
            parser_py = temp_repo / "kvparser" / "parser.py"
            content = parser_py.read_text(encoding="utf-8")
            self.assertIn("return value.strip()", content)

            fixed_content = content.replace(
                "    return value.strip()\n",
                "    if value is None:\n        return None\n    return value.strip()\n",
            )
            parser_py.write_text(fixed_content, encoding="utf-8")

            with tempfile.TemporaryDirectory() as artifact_dir:
                res = evaluate(
                    repo_path=temp_repo,
                    artifact_path=artifact_dir,
                    manifest_path=MANIFEST_PATH,
                    baseline_path=FIXTURE_REPO,
                )

                # Target test should now pass (1/1, no skip/error)
                target_res = res["evaluator_run"]["target_test"]
                self.assertTrue(target_res["passed"])
                self.assertEqual(target_res["exit_code"], 0)
                self.assertFalse(target_res["evaluation_error"])
                self.assertEqual(target_res["summary_counts"]["passed"], 1)
                self.assertEqual(target_res["summary_counts"]["failed"], 0)
                self.assertEqual(target_res["summary_counts"]["skipped"], 0)

                # Visible suite should pass 5/5
                visible_res = res["evaluator_run"]["visible_suite"]
                self.assertTrue(visible_res["passed"])
                self.assertEqual(visible_res["summary_counts"]["passed"], 5)
                self.assertEqual(visible_res["summary_counts"]["failed"], 0)
                self.assertEqual(visible_res["summary_counts"]["skipped"], 0)
                self.assertEqual(visible_res["summary_counts"]["errors"], 0)

                # Hidden suite must be strictly 6/6 passed, 0 skipped, 0 error
                hidden_res = res["evaluator_run"]["hidden_suite"]
                self.assertTrue(hidden_res["passed"])
                self.assertEqual(hidden_res["summary_counts"]["passed"], 6)
                self.assertEqual(hidden_res["summary_counts"]["failed"], 0)
                self.assertEqual(hidden_res["summary_counts"]["skipped"], 0)
                self.assertEqual(hidden_res["summary_counts"]["errors"], 0)
                self.assertFalse(hidden_res["evaluation_error"])

                # Overall summary
                self.assertTrue(res["summary"]["all_tests_passed"])
                self.assertFalse(res["summary"]["has_evaluation_error"])
                self.assertTrue(res["summary"]["has_code_changes"])
                self.assertEqual(res["summary"]["modified_files_count"], 1)
                self.assertEqual(res["code_changes"]["modified_files"], ["kvparser/parser.py"])
                self.assertEqual(res["summary"]["lines_added"], 2)
                self.assertEqual(res["summary"]["lines_deleted"], 0)
                self.assertEqual(res["summary"]["added_test_cases"], [])
                self.assertEqual(res["summary"]["added_visible_tests_count"], 0)
                self.assertEqual(res["summary"]["tests_edited"], [])

                # Unified diff generated in patch file
                patch_file = Path(artifact_dir) / "changes.patch"
                self.assertTrue(patch_file.is_file())
                patch_text = patch_file.read_text(encoding="utf-8")
                self.assertIn("+    if value is None:", patch_text)

    def test_snapshot_execution_does_not_pollute_or_delete_agent_evidence(self) -> None:
        """Evaluator runs inside snapshot: preserves pre-existing cache evidence and creates no pollution in repo."""
        with tempfile.TemporaryDirectory() as work_dir:
            temp_repo = Path(work_dir) / "repo"
            shutil.copytree(FIXTURE_REPO, temp_repo)

            # Pre-create agent evidence: a dummy __pycache__ and .pytest_cache
            dummy_cache = temp_repo / ".pytest_cache" / "v" / "cache"
            dummy_cache.mkdir(parents=True)
            (dummy_cache / "lastfailed").write_text('{"tests/test_parser.py": true}', encoding="utf-8")

            dummy_pycache = temp_repo / "kvparser" / "__pycache__"
            dummy_pycache.mkdir(parents=True)
            (dummy_pycache / "parser.cpython-312.pyc").write_bytes(b"dummy_bytecode")

            initial_files = set(temp_repo.rglob("*"))

            evaluate(repo_path=temp_repo)

            after_files = set(temp_repo.rglob("*"))

            # 1. Existing agent evidence was NOT deleted
            self.assertTrue((dummy_cache / "lastfailed").is_file())
            self.assertTrue((dummy_pycache / "parser.cpython-312.pyc").is_file())

            # 2. No new pollution added to original temp_repo
            self.assertEqual(initial_files, after_files)

    def test_evaluation_error_distinction_from_assertion_failure(self) -> None:
        """Distinguish exit codes like 4 (usage error) / 5 (no tests) from normal assertion failure (exit 1)."""
        with tempfile.TemporaryDirectory() as work_dir:
            temp_repo = Path(work_dir) / "repo"
            shutil.copytree(FIXTURE_REPO, temp_repo)

            evaluator = DeterministicEvaluator(manifest_path=MANIFEST_PATH)
            # Run non-existent test target -> exit code 4 or 5
            res = evaluator._run_single_test_command(temp_repo, "tests/non_existent.py")
            self.assertNotEqual(res["exit_code"], 0)
            self.assertTrue(res["evaluation_error"])
            self.assertFalse(res["assertion_failure"])
            self.assertIn(res["error_type"], ("USAGE_ERROR", "NO_TESTS_COLLECTED"))

    def test_cli_execution(self) -> None:
        """Test invoking evaluator CLI."""
        with tempfile.TemporaryDirectory() as artifact_dir:
            cmd = [
                str(VENV_PYTHON),
                "-B",
                "-m",
                "experiment.evaluator",
                "--repo",
                str(FIXTURE_REPO),
                "--artifact",
                artifact_dir,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
            # Baseline fails tests -> exit code 1
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Deterministic Evaluation Report", proc.stdout)
            self.assertIn("Target Test Passed:   False", proc.stdout)
            self.assertIn("Evaluation Error:     False", proc.stdout)

            artifact_file = Path(artifact_dir) / "evaluation_result.json"
            self.assertTrue(artifact_file.is_file())

    def test_visible_suite_allows_added_tests(self) -> None:
        """Visible suite must pass even when new tests are added, without failing the correct implementation."""
        with tempfile.TemporaryDirectory() as work_dir:
            temp_repo = Path(work_dir) / "repo"
            shutil.copytree(FIXTURE_REPO, temp_repo)

            # 1. Apply minimal fix
            parser_py = temp_repo / "kvparser" / "parser.py"
            content = parser_py.read_text(encoding="utf-8")
            fixed_content = content.replace(
                "    return value.strip()\n",
                "    if value is None:\n        return None\n    return value.strip()\n",
            )
            parser_py.write_text(fixed_content, encoding="utf-8")

            # 2. Add an additional passing test to visible tests
            test_file = temp_repo / "tests" / "test_parser.py"
            extra_test = "\n\ndef test_custom_added_case():\n    assert clean_value('  extra  ') == 'extra'\n"
            test_file.write_text(test_file.read_text(encoding="utf-8") + extra_test, encoding="utf-8")

            res = evaluate(
                repo_path=temp_repo,
                manifest_path=MANIFEST_PATH,
                baseline_path=FIXTURE_REPO,
            )

            # Visible suite must pass (passed >= 5, here 6)
            self.assertTrue(res["summary"]["visible_suite_passed"])
            self.assertEqual(res["summary"]["added_visible_tests_count"], 1)
            self.assertIn("tests/test_parser.py", res["summary"]["tests_edited"])
            self.assertEqual(len(res["summary"]["added_test_cases"]), 1)
            self.assertIn("test_custom_added_case", res["summary"]["added_test_cases"][0])
            self.assertTrue(res["summary"]["all_tests_passed"])

    def test_added_tests_exact_baseline_identity_and_canonical_matching(self) -> None:
        """Baseline passing and failing tests are recognized; only genuine additions appear in added_test_cases."""
        from experiment.evaluator.evaluator import canonical_test_id

        # 1. Canonical ID equivalence tests
        self.assertEqual(
            canonical_test_id("tests/test_parser.py::test_parse_header_with_none_value"),
            canonical_test_id("tests.test_parser::test_parse_header_with_none_value"),
        )
        self.assertEqual(
            canonical_test_id("./tests/test_parser.py::test_parse_simple_header"),
            canonical_test_id("tests.test_parser::test_parse_simple_header"),
        )
        self.assertEqual(
            canonical_test_id(r"tests\test_parser.py::test_foo"),
            canonical_test_id("tests.test_parser::test_foo"),
        )
        self.assertEqual(
            canonical_test_id("tests/test_parser.py::TestClass::test_method"),
            canonical_test_id("tests.test_parser.TestClass::test_method"),
        )
        self.assertEqual(
            canonical_test_id("tests/test_parser.py::test_foo[param1]"),
            canonical_test_id("tests.test_parser::test_foo[param1]"),
        )

        # 2. Evaluation with pure minimal fix (no test file change)
        with tempfile.TemporaryDirectory() as work_dir:
            temp_repo = Path(work_dir) / "repo"
            shutil.copytree(FIXTURE_REPO, temp_repo)
            parser_py = temp_repo / "kvparser" / "parser.py"
            content = parser_py.read_text(encoding="utf-8")
            fixed = content.replace(
                "    return value.strip()\n",
                "    if value is None:\n        return None\n    return value.strip()\n",
            )
            parser_py.write_text(fixed, encoding="utf-8")

            res_fix = evaluate(
                repo_path=temp_repo,
                manifest_path=MANIFEST_PATH,
                baseline_path=FIXTURE_REPO,
            )
            # Baseline had 4 passing + 1 failing visible tests.
            # Now all 5 pass: none are added tests!
            self.assertEqual(res_fix["summary"]["added_test_cases"], [])
            self.assertEqual(res_fix["summary"]["added_visible_tests_count"], 0)
            self.assertEqual(res_fix["summary"]["tests_edited"], [])

            # 3. Add exactly 1 new test to visible suite
            test_file = temp_repo / "tests" / "test_parser.py"
            extra_test = "\n\ndef test_completely_new_case():\n    assert True\n"
            test_file.write_text(test_file.read_text(encoding="utf-8") + extra_test, encoding="utf-8")

            res_added = evaluate(
                repo_path=temp_repo,
                manifest_path=MANIFEST_PATH,
                baseline_path=FIXTURE_REPO,
            )
            self.assertEqual(len(res_added["summary"]["added_test_cases"]), 1)
            self.assertIn("test_completely_new_case", res_added["summary"]["added_test_cases"][0])
            self.assertEqual(res_added["summary"]["added_visible_tests_count"], 1)

    def test_hidden_suite_rejects_skipped_tests(self) -> None:
        """Hidden suite must fail if tests are skipped rather than passing."""
        with tempfile.TemporaryDirectory() as work_dir:
            temp_repo = Path(work_dir) / "repo"
            shutil.copytree(FIXTURE_REPO, temp_repo)

            evaluator = DeterministicEvaluator(manifest_path=MANIFEST_PATH)
            # Simulate a result where hidden tests are all skipped
            fake_res = {
                "exit_code": 0,
                "evaluation_error": False,
                "counts": {"total": 6, "passed": 0, "failed": 0, "skipped": 6, "errors": 0},
            }
            exp_hidden = evaluator.manifest.get("verification_definitions", {}).get("expected_counts", {}).get("hidden_suite", {})
            exp_hid_total = exp_hidden.get("total", 6)
            exp_hid_passed = exp_hidden.get("passed", exp_hid_total)

            hidden_counts = fake_res["counts"]
            hidden_suite_passed = (
                fake_res["exit_code"] == 0
                and not fake_res["evaluation_error"]
                and exp_hid_total > 0
                and hidden_counts["total"] >= exp_hid_total
                and hidden_counts["passed"] == exp_hid_passed
                and hidden_counts["failed"] == 0
                and hidden_counts["skipped"] == 0
                and hidden_counts["errors"] == 0
            )
            self.assertFalse(hidden_suite_passed)

    def test_dynamic_manifest_resolution_by_fixture_id(self) -> None:
        """Evaluator resolves manifest dynamically via fixture_id."""
        evaluator = DeterministicEvaluator(fixture_id="T02")
        self.assertEqual(evaluator.fixture_id, "T02")
        self.assertTrue(evaluator.manifest_path.is_file())
        self.assertTrue(evaluator.baseline_path.is_dir())


if __name__ == "__main__":
    unittest.main()
