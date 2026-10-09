"""Independent acceptance regressions. Synthetic archives only; no model calls.

These exercise production recovery/reconciliation rather than trusting cached metrics.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiment import matrix
from experiment.summarize import aggregate_batch, check_run_eligibility, summarize_run
from experiment.tests.test_summarize import create_mock_run_dir


class TestIndependentAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="independent-acceptance-")
        self.addCleanup(self.temp.cleanup)
        self.batch = Path(self.temp.name)
        self.spec = {"task": "T02", "condition": "P0", "run_index": 1, "schedule_index": 1}
        self.schedule = [self.spec]
        self.write_schedule()
        self.run = self.make_run(self.spec)
        metrics = summarize_run(self.run)
        self.assertTrue(metrics["eligible_for_behavioral_aggregation"], metrics["exclusion_reason"])
        (self.run / "metrics.json").write_text(json.dumps(metrics))

    def write_schedule(self):
        (self.batch / "schedule.json").write_text(json.dumps(self.schedule))

    def make_run(self, spec, prefix=None):
        root = self.batch if prefix is None else prefix
        run = create_mock_run_dir(
            root / spec["condition"] / spec["task"], f"run{spec['run_index']}",
            task=spec["task"], condition=spec["condition"], run_idx=spec["run_index"],
            batch_id="acceptance", schedule_index=spec["schedule_index"],
        )
        (run / "final_response.txt").write_text("Synthetic archive; no model invocation.")
        (run / "diff.patch").write_text("")
        (run / "judge_attempt.json").write_text(json.dumps({"status": "completed"}))
        return run

    def test_cached_metrics_cannot_override_corrupt_judge_stream(self):
        self.assertEqual(matrix.check_run_qualification(self.run)["status"], "completed")
        (self.run / "judge_raw.jsonl").write_text("{corrupt json\n")
        self.assertFalse(check_run_eligibility(self.run)["is_eligible"])
        self.assertNotEqual(matrix.check_run_qualification(self.run)["status"], "completed")

    def test_rejected_real_aggregation_cannot_end_as_completed(self):
        """Actual summarize CLI runs; a guard forbids every other subprocess."""
        (self.run / "judge_raw.jsonl").write_text("{corrupt json\n")
        original_execute = matrix.execute_subprocess
        summary_path = Path(matrix.ROOT / "summarize.py").resolve()

        def only_summary(cmd, **kwargs):
            self.assertEqual(cmd[0], sys.executable)
            self.assertEqual(Path(cmd[1]).resolve(), summary_path,
                             "Target/Judge subprocess calls are forbidden in acceptance")
            self.assertIn("--batch-dir", cmd)
            return original_execute(cmd, **kwargs)

        with patch("experiment.matrix.run_preflight", return_value=0), \
             patch("experiment.matrix.execute_subprocess", side_effect=only_summary), \
             patch("sys.argv", ["matrix.py", "--execute", "--resume",
                                "--batch-id", "acceptance", "--batch-dir", str(self.batch),
                                "--tasks", "T02", "--conditions", "P0", "--runs", "1"]), \
             contextlib.redirect_stdout(io.StringIO()):
            code = matrix.main()
        summary = json.loads((self.batch / "results" / "summary.json").read_text())
        self.assertEqual(summary["eligible_runs_count"], 0)
        self.assertNotEqual(code, 0, "Rejected evidence must not yield successful batch exit")
        progress = json.loads((self.batch / "progress.json").read_text())
        self.assertNotEqual(progress["status"], "completed")

    def test_corrupt_frozen_schedule_fails_closed(self):
        (self.batch / "schedule.json").write_text("{corrupt json\n")
        self.assertFalse(summarize_run(self.run)["eligible_for_behavioral_aggregation"])

    def test_out_of_range_frozen_schedule_index_fails_closed(self):
        metadata_path = self.run / "run_metadata.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["schedule_index"] = 999
        metadata_path.write_text(json.dumps(metadata))
        self.assertFalse(summarize_run(self.run)["eligible_for_behavioral_aggregation"])

    def test_resume_skipping_completed_cell_does_not_consume_pending_cell(self):
        second = {"task": "T03", "condition": "P0", "run_index": 1, "schedule_index": 2}
        self.schedule.append(second)
        self.write_schedule()
        previous = matrix.StatusRecorder(self.batch, "acceptance", 2, self.schedule)
        previous.update_progress(delta_completed=1, delta_target=1, delta_judge=1)
        recorder = matrix.StatusRecorder(self.batch, "acceptance", 2, self.schedule, resume=True)
        recorder.reconcile_schedule(self.batch, self.schedule)
        with patch("experiment.matrix.execute_subprocess", side_effect=AssertionError("No model calls allowed")):
            matrix.run_single_pipeline(self.spec, self.batch, True, 1, recorder, resume=True)
        self.assertEqual(recorder.stats["target_invocations"], 1)
        self.assertEqual(recorder.stats["judge_invocations"], 1)
        self.assertEqual(recorder.stats["pending_runs"], 1,
                         "One completed cell and one absent cell must leave one pending")

    def test_duplicate_archive_prevents_formal_ready_status(self):
        self.schedule = matrix.generate_schedule()
        self.write_schedule()
        runs = [self.make_run(spec) for spec in self.schedule]
        baseline = aggregate_batch(runs, expected_batch_id="acceptance")
        self.assertEqual(baseline["readiness_for_formal_analysis"], "READY")
        duplicate = self.make_run(self.schedule[0], prefix=self.batch / "duplicate")
        result = aggregate_batch(runs + [duplicate], expected_batch_id="acceptance")
        self.assertEqual(result["matrix_reconciliation"]["duplicate_count"], 1)
        self.assertNotEqual(result["readiness_for_formal_analysis"], "READY")
        self.assertNotEqual(result["batch_completion_status"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
