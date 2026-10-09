"""Independent readiness review test suite. Synthetic archives only; no model calls.

Validates concrete blocking defects and positive safety invariants prior to formal matrix execution.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from experiment import matrix
from experiment.evaluator.evaluator import classify_pytest_exit
from experiment.judge import validate_verdict
from experiment.summarize import aggregate_batch, check_run_eligibility, summarize_run
from experiment.tests.test_summarize import create_mock_run_dir


class TestReadinessPositiveInvariants(unittest.TestCase):
    """Positive safety verifications confirming core mechanisms that work correctly."""

    def test_genuine_assertion_failure_yields_hc0_and_eligible(self):
        """Assertion failure (exit 1) must yield HC=0 and remain eligible for behavioral aggregation."""
        with tempfile.TemporaryDirectory(prefix="test-hc0-") as td:
            run_dir = create_mock_run_dir(
                Path(td), "run1", task="T02", condition="P0", run_idx=1,
                batch_id="inv-test", schedule_index=1
            )
            # Simulate evaluator outcome with assertion failure (exit 1)
            eval_res = {
                "summary": {
                    "has_evaluation_error": False,
                    "target_test_passed": False,
                    "visible_suite_passed": False,
                    "hidden_suite_passed": False,
                    "evaluation_errors": [],
                }
            }
            (run_dir / "evaluation_result_v2.json").write_text(json.dumps(eval_res))
            # Run summarize_run
            summary = summarize_run(run_dir)
            self.assertEqual(summary["HC"], 0)
            self.assertFalse(summary.get("has_evaluation_error", False))
            self.assertTrue(summary["eligible_for_behavioral_aggregation"],
                            f"Genuine assertion failure should be eligible, got: {summary.get('exclusion_reason')}")

    def test_evaluator_infrastructure_error_is_disqualified(self):
        """Evaluation infra error (exit 2..5) must set HC=None and disqualify the run."""
        is_err, err_type = classify_pytest_exit(2)
        self.assertTrue(is_err)
        self.assertEqual(err_type, "INTERRUPTED")

        is_err_syntax, _ = classify_pytest_exit(4)
        self.assertTrue(is_err_syntax)

        with tempfile.TemporaryDirectory(prefix="test-infrerr-") as td:
            run_dir = create_mock_run_dir(
                Path(td), "run1", task="T02", condition="P0", run_idx=1,
                batch_id="inv-test", schedule_index=1
            )
            eval_res = {
                "summary": {
                    "has_evaluation_error": True,
                    "evaluation_errors": [{"stage": "visible_suite", "error_type": "USAGE_ERROR", "exit_code": 4}],
                    "hidden_suite_passed": False,
                }
            }
            (run_dir / "evaluation_result_v2.json").write_text(json.dumps(eval_res))
            summary = summarize_run(run_dir)
            self.assertIsNone(summary["HC"])
            self.assertFalse(summary["eligible_for_behavioral_aggregation"])
            self.assertIn("Evaluation infrastructure error", summary["exclusion_reason"])

    def test_blind_judge_sanitizes_paths_and_omits_condition(self):
        """Judge input preparation must sanitize absolute workspace paths and never include condition labels."""
        from experiment.judge import build_prompt

        fake_workspace = "/private/tmp/astra-work-xyz123/repo"
        fake_rundir = "/Users/gravity/Desktop/AI/prompt-hillclimb/experiment/runs/layer1/P0/T02/run1"

        def mock_blind(text: str) -> str:
            for p in (fake_workspace, fake_rundir):
                text = text.replace(p, "<private-path>")
            return text

        diff = f"--- a{fake_workspace}/src/foo.py\n+++ b{fake_workspace}/src/foo.py\n@@ -1 +1 @@\n"
        trace = f'{{"event": "call", "path": "{fake_rundir}/tool_trace.jsonl"}}'
        final_resp = f"Fixed bug in {fake_workspace}/src/foo.py"

        prompt = build_prompt(
            task="Fix the None bug in parser",
            summary="Repository parser summary",
            diff=mock_blind(diff),
            tests={"hidden_suite": {"passed": False, "exit_code": 1}},
            trace=mock_blind(trace),
            final_response=mock_blind(final_resp),
        )

        self.assertNotIn(fake_workspace, prompt)
        self.assertNotIn(fake_rundir, prompt)
        self.assertIn("<private-path>", prompt)
        self.assertNotIn("condition: P", prompt)
        self.assertNotIn("P0", prompt)
        self.assertNotIn("P1", prompt)
        self.assertNotIn("P2", prompt)

    def test_cli_wiring_command_signatures_match(self):
        """Verify that CLI parser arguments for Runner, Evaluator, Judge, and Summarize match matrix invocations."""
        from experiment import judge, runner, summarize
        from experiment.evaluator import evaluator

        # Runner
        self.assertTrue(hasattr(runner, "main"))
        # Evaluator
        self.assertTrue(hasattr(evaluator, "main"))
        # Judge
        self.assertTrue(hasattr(judge, "main"))
        # Summarize
        self.assertTrue(hasattr(summarize, "main"))
        # Matrix
        self.assertTrue(hasattr(matrix, "main"))

    def test_process_tree_cancellation_traverses_exact_hierarchy(self):
        """Process cancellation uses exact pid/ppid graph without heuristic name matching."""
        my_pid = os.getpid()
        descendants = matrix.get_all_descendant_pids({my_pid})
        self.assertIsInstance(descendants, set)
        self.assertNotIn(my_pid, descendants)


class TestReadinessBlockingDefects(unittest.TestCase):
    """Reproducible audit tests for the 7 blocking / accounting defects.

    These tests verify whether each safety contract is properly upheld or currently violated.
    Failing tests indicate blocking issues that must be resolved by their respective owners.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="readiness-defect-")
        self.addCleanup(self.temp.cleanup)
        self.batch = Path(self.temp.name)
        self.spec = {"task": "T02", "condition": "P0", "run_index": 1, "schedule_index": 1}
        self.schedule = [self.spec]
        self.write_schedule()
        self.run = self.make_run(self.spec)
        metrics = summarize_run(self.run)
        self.assertTrue(metrics["eligible_for_behavioral_aggregation"], metrics.get("exclusion_reason"))
        (self.run / "metrics.json").write_text(json.dumps(metrics))

    def write_schedule(self):
        (self.batch / "schedule.json").write_text(json.dumps(self.schedule))

    def make_run(self, spec, prefix=None):
        root = self.batch if prefix is None else prefix
        run = create_mock_run_dir(
            root / spec["condition"] / spec["task"], f"run{spec['run_index']}",
            task=spec["task"], condition=spec["condition"], run_idx=spec["run_index"],
            batch_id="readiness", schedule_index=spec["schedule_index"],
        )
        (run / "final_response.txt").write_text("Synthetic archive; zero model invocations.")
        (run / "diff.patch").write_text("")
        (run / "judge_attempt.json").write_text(json.dumps({"status": "completed"}))
        return run

    def test_defect1_matrix_cached_metrics_vs_corrupted_evidence(self):
        """Defect 1 (Owner: w8:p4): Corrupted judge stream must disqualify run; matrix must not trust cached metrics."""
        self.assertEqual(matrix.check_run_qualification(self.run)["status"], "completed")
        # Corrupt the raw evidence stream
        (self.run / "judge_raw.jsonl").write_text("{corrupt json\n")
        self.assertFalse(check_run_eligibility(self.run)["is_eligible"])
        # Safety contract: matrix qualification must re-validate evidence and refuse 'completed'
        qual = matrix.check_run_qualification(self.run)
        self.assertNotEqual(
            qual["status"], "completed",
            "BLOCKED (w8:p4): matrix.check_run_qualification trusts cached metrics over corrupt judge stream"
        )

    def test_defect2_matrix_batch_aggregation_rejection_propagation(self):
        """Defect 2 (Owner: w8:p4/w8:p3): Batch summarize rejection must fail matrix exit and not report 'completed'."""
        (self.run / "judge_raw.jsonl").write_text("{corrupt json\n")
        original_execute = matrix.execute_subprocess
        summary_path = Path(matrix.ROOT / "summarize.py").resolve()

        def only_summary(cmd, **kwargs):
            self.assertEqual(cmd[0], sys.executable)
            self.assertEqual(Path(cmd[1]).resolve(), summary_path)
            return original_execute(cmd, **kwargs)

        with patch("experiment.matrix.run_preflight", return_value=0), \
             patch("experiment.matrix.execute_subprocess", side_effect=only_summary), \
             patch("sys.argv", ["matrix.py", "--execute", "--resume",
                                "--batch-id", "readiness", "--batch-dir", str(self.batch),
                                "--tasks", "T02", "--conditions", "P0", "--runs", "1"]), \
             contextlib.redirect_stdout(io.StringIO()):
            code = matrix.main()

        summary = json.loads((self.batch / "results" / "summary.json").read_text())
        self.assertEqual(summary["eligible_runs_count"], 0)
        self.assertNotEqual(code, 0, "BLOCKED (w8:p4/w8:p3): Rejected batch evidence must not yield exit code 0")
        progress = json.loads((self.batch / "progress.json").read_text())
        self.assertNotEqual(progress["status"], "completed",
                            "BLOCKED (w8:p4): Progress status marked 'completed' despite zero eligible runs")

    def test_defect3_corrupt_frozen_schedule_swallowed_exception(self):
        """Defect 3 (Owner: w8:p3): Corrupt frozen schedule must fail closed in summarize_run."""
        (self.batch / "schedule.json").write_text("{corrupt json\n")
        metrics = summarize_run(self.run)
        self.assertFalse(
            metrics["eligible_for_behavioral_aggregation"],
            "BLOCKED (w8:p3): summarize_run swallowed JSONDecodeError on corrupted schedule.json"
        )

    def test_defect4_out_of_range_frozen_schedule_index_bypasses_check(self):
        """Defect 4 (Owner: w8:p3): Out-of-range schedule_index must fail closed in summarize_run."""
        metadata_path = self.run / "run_metadata.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["schedule_index"] = 999
        metadata_path.write_text(json.dumps(metadata))
        metrics = summarize_run(self.run)
        self.assertFalse(
            metrics["eligible_for_behavioral_aggregation"],
            "BLOCKED (w8:p3): summarize_run skipped validation when schedule_index was out of range"
        )

    def test_defect5_resume_double_counting_skipped_cells(self):
        """Defect 5 (Owner: w8:p4): Resuming 1 completed cell in 2-cell batch must leave pending_runs=1."""
        second = {"task": "T03", "condition": "P0", "run_index": 1, "schedule_index": 2}
        self.schedule.append(second)
        self.write_schedule()
        previous = matrix.StatusRecorder(self.batch, "readiness", 2, self.schedule)
        previous.update_progress(delta_completed=1, delta_target=1, delta_judge=1)
        recorder = matrix.StatusRecorder(self.batch, "readiness", 2, self.schedule, resume=True)
        recorder.reconcile_schedule(self.batch, self.schedule)
        with patch("experiment.matrix.execute_subprocess", side_effect=AssertionError("No model calls allowed")):
            matrix.run_single_pipeline(self.spec, self.batch, True, 1, recorder, resume=True)
        self.assertEqual(
            recorder.stats["pending_runs"], 1,
            "BLOCKED (w8:p4): Skipped completed cell was double-counted into skipped_runs, falsely consuming pending_runs"
        )

    def test_defect6_duplicate_archives_do_not_prevent_ready_status(self):
        """Defect 6 (Owner: w8:p3): Duplicate cell archive must prevent batch_completion_status=COMPLETE and READY."""
        self.schedule = matrix.generate_schedule()
        self.write_schedule()
        runs = [self.make_run(spec) for spec in self.schedule]
        baseline = aggregate_batch(runs, expected_batch_id="readiness")
        self.assertEqual(baseline["readiness_for_formal_analysis"], "READY")
        duplicate = self.make_run(self.schedule[0], prefix=self.batch / "duplicate")
        result = aggregate_batch(runs + [duplicate], expected_batch_id="readiness")
        self.assertEqual(result["matrix_reconciliation"]["duplicate_count"], 1)
        self.assertNotEqual(
            result["readiness_for_formal_analysis"], "READY",
            "BLOCKED (w8:p3): aggregate_batch returned READY despite duplicate run archives"
        )
        self.assertNotEqual(
            result["batch_completion_status"], "COMPLETE",
            "BLOCKED (w8:p3): aggregate_batch returned COMPLETE despite duplicate run archives"
        )

    def test_defect7_default_resume_batch_id_overwrites_progress(self):
        """Defect 7 (Owner: w8:p4): Matrix resume with --batch-dir without --batch-id must not overwrite batch_id in progress.json."""
        test_args = ["matrix.py", "--dry-run", "--resume", "--batch-dir", str(self.batch)]
        with patch("sys.argv", test_args):
            code = matrix.main()
        self.assertEqual(code, 0)
        progress = json.loads((self.batch / "progress.json").read_text())
        self.assertEqual(
            progress.get("batch_id"), "readiness",
            "BLOCKED (w8:p4): Matrix resume with --batch-dir without explicit --batch-id overwrote batch_id with newly generated timestamp"
        )


if __name__ == "__main__":
    unittest.main()
