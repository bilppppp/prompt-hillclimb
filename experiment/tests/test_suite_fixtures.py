"""Integration self-checks for all Core experiment fixtures (T01 through T09).

Verifies manifest schema contract integrity, repository summary linkage, effective LOC
bounds (100-500), file and test counts, task description constraints, baseline preflight
expectations, and that minimal reference fixes pass all target, visible, and hidden test suites
(strict 6/6 without skips or errors) without modifying fixture repositories.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FIXTURES_DIR = PROJECT_ROOT / "experiment" / "fixtures" / "core"
EVALUATOR_DIR = PROJECT_ROOT / "experiment" / "evaluator"
MANIFESTS_DIR = EVALUATOR_DIR / "manifests"

from experiment.evaluator.evaluator import DeterministicEvaluator


class TestCoreFixturesSuite(unittest.TestCase):
    """Test suite covering all 9 fixtures (T01 through T09)."""

    FIXTURE_IDS = [f"T{i:02d}" for i in range(1, 10)]

    def _apply_minimal_fix(self, fixture_id: str, repo_dir: Path) -> None:
        """Apply minimal reference code fix to a temporary copy of fixture repo."""
        if fixture_id == "T01":
            cfg = repo_dir / "clilabel" / "config.py"
            cfg.write_text(cfg.read_text(encoding="utf-8").replace('"foo"', '"bar"'), encoding="utf-8")
            # Legal test update for T01: existing assertions on foo updated to bar
            test_file = repo_dir / "tests" / "test_cli.py"
            test_file.write_text(test_file.read_text(encoding="utf-8").replace('"foo"', '"bar"'), encoding="utf-8")

        elif fixture_id == "T02":
            parser_file = repo_dir / "kvparser" / "parser.py"
            content = parser_file.read_text(encoding="utf-8")
            target = "    return value.strip()"
            repl = "    if value is None:\n        return None\n    return value.strip()"
            parser_file.write_text(content.replace(target, repl), encoding="utf-8")

        elif fixture_id == "T03":
            cli_file = repo_dir / "itemfilter" / "cli.py"
            content = cli_file.read_text(encoding="utf-8")
            content = content.replace("default=10,", "type=int,\n        default=10,")
            cli_file.write_text(content, encoding="utf-8")

        elif fixture_id == "T04":
            cfg = repo_dir / "clientconfig" / "config.py"
            content = cfg.read_text(encoding="utf-8")
            target = "    # BUG: Hardcoded return 30 instead of reading config\n    return 30"
            repl = """    val = config.get("timeout")
    if val is None:
        return 30
    return int(val)"""
            cfg.write_text(content.replace(target, repl), encoding="utf-8")

        elif fixture_id == "T05":
            fmt = repo_dir / "userreport" / "formatter.py"
            content = fmt.read_text(encoding="utf-8")
            target = """    elif fmt == "json":
        # BUG: json formatting not yet implemented
        raise ValueError(f"Unsupported format: {fmt}")"""
            repl = """    elif fmt == "json":
        import json
        return json.dumps(dict(data))"""
            fmt.write_text(content.replace(target, repl), encoding="utf-8")

        elif fixture_id == "T06":
            calc = repo_dir / "discountcalc" / "calculator.py"
            content = calc.read_text(encoding="utf-8")
            content = content.replace("1.0 + rate", "1.0 - rate")
            calc.write_text(content, encoding="utf-8")

        elif fixture_id == "T07":
            fmt = repo_dir / "dataexport" / "formatter.py"
            content = fmt.read_text(encoding="utf-8")
            target = """    elif fmt == "json":
        # BUG: json formatting not yet implemented
        raise ValueError(f"Unsupported format: {fmt}")"""
            repl = """    elif fmt == "json":
        import json
        return json.dumps(normalize_record(record))"""
            fmt.write_text(content.replace(target, repl), encoding="utf-8")

        elif fixture_id == "T08":
            store = repo_dir / "recordstore" / "storage.py"
            content = store.read_text(encoding="utf-8")
            target = """    # BUG: unconditionally appends incoming records without deduplication by id
    result = [dict(r) for r in existing]
    for rec in incoming:
        result.append(dict(rec))
    return result"""
            repl = """    existing_ids = {r["id"] for r in existing}
    result = [dict(r) for r in existing]
    for rec in incoming:
        if rec["id"] not in existing_ids:
            result.append(dict(rec))
            existing_ids.add(rec["id"])
    return result"""
            store.write_text(content.replace(target, repl), encoding="utf-8")

        elif fixture_id == "T09":
            trans = repo_dir / "schemaconvert" / "transformer.py"
            content = trans.read_text(encoding="utf-8")
            target = """    # BUG: Copies record directly without transforming first_name/last_name into full_name
    # and without setting status="active"
    return dict(record)"""
            repl = """    first = str(record.get("first_name", "")).strip()
    last = str(record.get("last_name", "")).strip()
    full = f"{first} {last}".strip()
    return {
        "full_name": full,
        "email": str(record.get("email", "")),
        "status": "active",
    }"""
            trans.write_text(content.replace(target, repl), encoding="utf-8")

    def test_all_manifests_and_summaries_exist_and_match_hashes(self) -> None:
        """Verify manifests, repository summaries, LOC bounds (100-500), and file SHA256 hashes."""
        for fid in self.FIXTURE_IDS:
            with self.subTest(fixture=fid):
                manifest_path = MANIFESTS_DIR / f"{fid}_manifest.json"
                self.assertTrue(manifest_path.is_file(), f"Missing manifest for {fid}")

                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

                self.assertEqual(manifest["fixture_id"], fid)
                repo_dir = FIXTURES_DIR / fid / "repo"
                self.assertTrue(repo_dir.is_dir(), f"Missing repo dir for {fid}")

                # Verify task.md exists and is non-empty
                task_file = FIXTURES_DIR / fid / "task.md"
                self.assertTrue(task_file.is_file(), f"Missing task.md for {fid}")
                self.assertGreater(task_file.stat().st_size, 20)

                # Verify repository summary relpath in manifest resolves to existing file
                summary_rel = manifest.get("repository_summary_relpath")
                self.assertIsNotNone(summary_rel, f"Missing repository_summary_relpath in manifest for {fid}")
                summary_file = EVALUATOR_DIR / summary_rel
                self.assertTrue(summary_file.is_file(), f"Missing repository summary file at {summary_file}")
                self.assertGreater(summary_file.stat().st_size, 20)

                # Verify files recorded in manifest match hashes
                source_files = manifest.get("source_summary", {}).get("files", {})
                self.assertGreaterEqual(len(source_files), 3, f"{fid} has fewer than 3 files")
                self.assertLessEqual(len(source_files), 8, f"{fid} has more than 8 files")

                total_eff_loc = manifest.get("source_summary", {}).get("total_effective_loc", 0)
                self.assertGreaterEqual(total_eff_loc, 100, f"{fid} total_effective_loc < 100 ({total_eff_loc})")
                self.assertLessEqual(total_eff_loc, 500, f"{fid} total_effective_loc > 500 ({total_eff_loc})")

                calculated_total_loc = 0
                for rel_path, meta in source_files.items():
                    actual_file = repo_dir / rel_path
                    self.assertTrue(actual_file.is_file(), f"File {rel_path} in manifest missing on disk")
                    content = actual_file.read_bytes()
                    actual_sha = hashlib.sha256(content).hexdigest()
                    self.assertEqual(actual_sha, meta["sha256"], f"SHA mismatch on {rel_path}")

                    lines = [l for l in actual_file.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]
                    self.assertEqual(len(lines), meta["effective_loc"], f"LOC mismatch on {rel_path}")
                    calculated_total_loc += len(lines)

                self.assertEqual(calculated_total_loc, total_eff_loc, f"{fid} total effective loc mismatch")

    def test_task_text_constraints(self) -> None:
        """Verify task instruction wording: only T02 retains explicit Stop once; others describe real changes."""
        for fid in self.FIXTURE_IDS:
            with self.subTest(fixture=fid):
                task_file = FIXTURES_DIR / fid / "task.md"
                content = task_file.read_text(encoding="utf-8")

                if fid == "T02":
                    self.assertIn("Stop once", content, "T02 must preserve explicit stop instruction")
                else:
                    self.assertNotIn("Stop once", content, f"{fid} must not contain mechanical 'Stop once'")
                    self.assertNotIn("Stop when", content, f"{fid} must not contain mechanical stop rule")
                    self.assertNotIn("no evidence of new test failures", content, f"{fid} has leftover verification policy")

                # De-biasing checks
                if fid == "T05":
                    self.assertNotIn("import json", content.lower(), "T05 must not mandate standard json import library")
                elif fid == "T08":
                    self.assertNotIn("checkpoint", content.lower())
                    self.assertNotIn("manifest", content.lower())
                    self.assertNotIn("registry", content.lower())
                elif fid == "T09":
                    self.assertNotIn("checkpoint", content.lower())
                    self.assertNotIn("manifest", content.lower())
                    self.assertNotIn("retry logic", content.lower())

    def test_baseline_evaluations_match_preflight_expectations(self) -> None:
        """Verify baseline evaluation on untouched fixture matches preflight expectations."""
        for fid in self.FIXTURE_IDS:
            with self.subTest(fixture=fid):
                manifest_path = MANIFESTS_DIR / f"{fid}_manifest.json"
                repo_dir = FIXTURES_DIR / fid / "repo"

                evaluator = DeterministicEvaluator(manifest_path=manifest_path, baseline_path=repo_dir)
                res = evaluator.evaluate(repo_path=repo_dir)

                preflight = evaluator.manifest["verification_definitions"]["preflight"]
                target_res = res["evaluator_run"]["target_test"]
                visible_res = res["evaluator_run"]["visible_suite"]
                hidden_res = res["evaluator_run"]["hidden_suite"]

                # Target exit code matches preflight (0 for T01, T04; 1 for T02, T03, T05-T09)
                self.assertEqual(target_res["exit_code"], preflight["baseline_target_exit_code"])

                # Visible counts match preflight
                for key in ("passed", "failed", "total"):
                    self.assertEqual(
                        visible_res["summary_counts"][key],
                        preflight["baseline_visible"][key],
                        f"{fid} visible {key} mismatch",
                    )

                # Hidden counts match preflight
                for key in ("passed", "failed", "total"):
                    self.assertEqual(
                        hidden_res["summary_counts"][key],
                        preflight["baseline_hidden"][key],
                        f"{fid} hidden {key} mismatch",
                    )

                # Overall baseline must not be all_tests_passed
                self.assertFalse(res["summary"]["all_tests_passed"])
                self.assertFalse(res["summary"]["has_evaluation_error"])

    def test_minimal_fixes_pass_all_suites(self) -> None:
        """Verify minimal reference fix passes all visible and hidden tests (strict 6/6)."""
        for fid in self.FIXTURE_IDS:
            with self.subTest(fixture=fid):
                manifest_path = MANIFESTS_DIR / f"{fid}_manifest.json"
                repo_dir = FIXTURES_DIR / fid / "repo"

                with tempfile.TemporaryDirectory() as work_dir:
                    temp_repo = Path(work_dir) / "repo"
                    shutil.copytree(repo_dir, temp_repo)

                    self._apply_minimal_fix(fid, temp_repo)

                    evaluator = DeterministicEvaluator(
                        manifest_path=manifest_path,
                        baseline_path=repo_dir,
                    )
                    res = evaluator.evaluate(repo_path=temp_repo)

                    # Target test passed
                    self.assertTrue(res["evaluator_run"]["target_test"]["passed"], f"{fid} target test failed after fix")

                    # Visible suite passed
                    self.assertTrue(res["evaluator_run"]["visible_suite"]["passed"], f"{fid} visible suite failed after fix")
                    self.assertEqual(res["evaluator_run"]["visible_suite"]["summary_counts"]["failed"], 0)
                    self.assertEqual(res["evaluator_run"]["visible_suite"]["summary_counts"]["errors"], 0)

                    # Hidden suite passed strictly 6/6
                    hidden_res = res["evaluator_run"]["hidden_suite"]
                    self.assertTrue(hidden_res["passed"], f"{fid} hidden suite failed after fix")
                    self.assertEqual(hidden_res["summary_counts"]["passed"], 6, f"{fid} hidden passed != 6")
                    self.assertEqual(hidden_res["summary_counts"]["failed"], 0)
                    self.assertEqual(hidden_res["summary_counts"]["skipped"], 0)
                    self.assertEqual(hidden_res["summary_counts"]["errors"], 0)

                    # Summary
                    self.assertTrue(res["summary"]["all_tests_passed"], f"{fid} summary.all_tests_passed is False")
                    self.assertFalse(res["summary"]["has_evaluation_error"])
                    self.assertTrue(res["summary"]["has_code_changes"])


if __name__ == "__main__":
    unittest.main()
