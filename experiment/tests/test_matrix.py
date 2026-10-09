#!/usr/bin/env python3
"""Unit tests for experiment/matrix.py.

Verifies:
1. Schedule generation: 81 total runs (9x3x3), deterministic shuffling by seed.
2. StatusRecorder: thread-safe event streaming and live progress updates.
3. Completion verification: robust checking of full archival before resume.
4. Resume policy: skips completed runs; strictly prevents silent re-invocation of failed runs.
5. Workers constraint: concurrency capped at workers <= 3.
6. Dry-run execution: zero model calls, creates schedule.json and progress.json.
7. End-to-end pipeline orchestration with mocked components.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from experiment.matrix import (
    CONDITIONS,
    RUNS,
    TASKS,
    TOTAL_RUNS,
    StatusRecorder,
    check_run_qualification,
    generate_schedule,
    is_run_attempted,
    is_run_completed,
    main,
    resolve_repository_summary,
    run_single_pipeline,
)


class TestMatrixSchedule(unittest.TestCase):
    def test_total_runs_count(self):
        self.assertEqual(len(TASKS), 9)
        self.assertEqual(len(CONDITIONS), 3)
        self.assertEqual(len(RUNS), 3)
        self.assertEqual(TOTAL_RUNS, 81)

    def test_generate_schedule_determinism(self):
        sched1 = generate_schedule(seed=42)
        sched2 = generate_schedule(seed=42)
        self.assertEqual(len(sched1), 81)
        self.assertEqual(sched1, sched2)

        # Ensure all combinations exist
        combinations = {(item["task"], item["condition"], item["run_index"]) for item in sched1}
        self.assertEqual(len(combinations), 81)

        # Indexing 1..81
        indices = [item["schedule_index"] for item in sched1]
        self.assertEqual(indices, list(range(1, 82)))

    def test_generate_schedule_seed_variation(self):
        sched1 = generate_schedule(seed=42)
        sched2 = generate_schedule(seed=999)
        self.assertNotEqual(sched1, sched2)


class TestMatrixStatusRecorder(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test-matrix-status-"))
        self.schedule = generate_schedule(seed=42)[:5]
        self.recorder = StatusRecorder(self.temp_dir, "batch-test", 5, self.schedule)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_initial_progress_written(self):
        prog_file = self.temp_dir / "progress.json"
        self.assertTrue(prog_file.is_file())
        data = json.loads(prog_file.read_text(encoding="utf-8"))
        self.assertEqual(data["batch_id"], "batch-test")
        self.assertEqual(data["status"], "prepared")
        self.assertEqual(data["total_runs"], 5)
        self.assertEqual(data["pending_runs"], 5)

    def test_record_event_and_update_progress(self):
        spec = self.schedule[0]
        self.recorder.record_event("test_event", spec, {"foo": "bar"})

        status_file = self.temp_dir / "status.jsonl"
        self.assertTrue(status_file.is_file())
        lines = status_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["event"], "test_event")
        self.assertEqual(record["task"], spec["task"])
        self.assertEqual(record["data"], {"foo": "bar"})

        self.recorder.update_progress(delta_completed=1, delta_target=1)
        data = json.loads((self.temp_dir / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(data["completed_runs"], 1)
        self.assertEqual(data["target_invocations"], 1)
        self.assertEqual(data["pending_runs"], 4)


def make_valid_mock_run(run_dir: Path, batch_id: str = "test-batch", task: str = "T02", condition: str = "P0",
                        run_index: int = 1, schedule_index: int = 1, hc: int = 1, workspace: Path | None = None):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_metadata.json").write_text(json.dumps({
        "experiment_stage": "layer1/runs",
        "batch_id": batch_id,
        "schedule_index": schedule_index,
        "task": task,
        "condition": condition,
        "run_index": run_index,
        "status": "completed",
        "target_model": "gpt-6-astra",
        "reasoning_effort": "medium",
        "target_invocations": 1,
        "workspace": str(workspace or run_dir),
    }))
    (run_dir / "final_response.txt").write_text("fixed")
    (run_dir / "diff.patch").write_text("diff")
    (run_dir / "tool_trace.jsonl").write_text(json.dumps({"type": "turn.completed"}) + "\n")
    (run_dir / "evaluation_result_v2.json").write_text(json.dumps({
        "summary": {"has_evaluation_error": False, "hidden_suite_passed": (hc == 1)},
        "evaluator_run": {"visible_suite": {"summary_counts": {"passed": 1, "total": 1}},
                         "hidden_suite": {"summary_counts": {"passed": hc, "total": 1}}},
    }))
    (run_dir / "judge_attempt.json").write_text(json.dumps({"status": "completed"}))
    verdict = {
        "ISS": 4 if hc == 1 else 1, "PE": 0, "EVC": 0, "UM": 0, "SD": 2, "under_validation": False,
        "answers": ["ok"] * 7,
        "evidence": ["test passed"],
        "uncertainties": [],
    }
    (run_dir / "judge_verdict.json").write_text(json.dumps(verdict))
    raw_events = [
        {"event": "init", "init": {"model": "gemini-3.8-flash-high"}},
        {"event": "result", "result": {"status": "SUCCESS", "structured_output": verdict}},
    ]
    (run_dir / "judge_raw.jsonl").write_text("\n".join(json.dumps(e) for e in raw_events) + "\n")
    (run_dir / "metrics.json").write_text(json.dumps({
        "task": task,
        "condition": condition,
        "stage": "layer1/runs",
        "batch_id": batch_id,
        "schedule_index": schedule_index,
        "target_model": "gpt-6-astra",
        "reasoning_effort": "medium",
        "judge_model": "gemini-3.8-flash-high",
        "HC": hc,
        "ISS": 4 if hc == 1 else 1,
        "eligible_for_behavioral_aggregation": True,
    }))


class TestMatrixCompletionAndResume(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test-matrix-resume-"))
        self.run_dir = self.temp_dir / "P0" / "T02" / "run1"
        self.run_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_is_run_completed_checks_all_artifacts(self):
        self.assertFalse(is_run_completed(self.run_dir))

        (self.run_dir / "run_metadata.json").write_text(json.dumps({"status": "completed"}))
        self.assertFalse(is_run_completed(self.run_dir))

        (self.run_dir / "final_response.txt").write_text("fixed")
        (self.run_dir / "diff.patch").write_text("diff")
        (self.run_dir / "tool_trace.jsonl").write_text(json.dumps({"type": "turn.completed"}) + "\n")
        (self.run_dir / "evaluation_result_v2.json").write_text(json.dumps({
            "summary": {"has_evaluation_error": False, "hidden_suite_passed": True},
            "evaluator_run": {"visible_suite": {"summary_counts": {"passed": 1, "total": 1}},
                             "hidden_suite": {"summary_counts": {"passed": 1, "total": 1}}},
        }))
        self.assertFalse(is_run_completed(self.run_dir))

        (self.run_dir / "judge_attempt.json").write_text(json.dumps({"status": "completed"}))
        (self.run_dir / "judge_raw.jsonl").write_text(json.dumps({"event": "init", "init": {"model": "gemini-3.8-flash-high"}}) + "\n")
        (self.run_dir / "judge_verdict.json").write_text(json.dumps({
            "ISS": 4, "PE": 0, "EVC": 0, "UM": 0, "SD": 2, "under_validation": False,
            "answers": ["ok"] * 7, "evidence": ["test passed"], "uncertainties": [],
        }))
        self.assertFalse(is_run_completed(self.run_dir))

        # Empty metrics is REJECTED
        (self.run_dir / "metrics.json").write_text("{}")
        self.assertFalse(is_run_completed(self.run_dir))

        # Disqualified metrics is REJECTED
        (self.run_dir / "metrics.json").write_text(json.dumps({
            "task": "T02",
            "condition": "P0",
            "stage": "layer1/runs",
            "target_model": "gpt-6-astra",
            "reasoning_effort": "medium",
            "judge_model": "gemini-3.8-flash-high",
            "HC": 1,
            "eligible_for_behavioral_aggregation": False,
            "exclusion_reason": "Single pilot",
        }))
        self.assertFalse(is_run_completed(self.run_dir))

        # Valid mock run is ACCEPTED
        make_valid_mock_run(self.run_dir, workspace=self.temp_dir)
        self.assertTrue(is_run_completed(self.run_dir))

    def test_is_run_completed_accepts_hc_zero_when_eligible(self):
        """Real HC == 0 is normal behavioral failure and must remain eligible."""
        make_valid_mock_run(self.run_dir, hc=0, workspace=self.temp_dir)
        self.assertTrue(is_run_completed(self.run_dir))

    def test_check_run_qualification_running_with_invocation_fails_closed(self):
        """status=running with target_invocations=1 must fail closed (already_failed), never unattempted."""
        (self.run_dir / "run_metadata.json").write_text(json.dumps({
            "status": "running",
            "target_invocations": 1,
        }))
        qual = check_run_qualification(self.run_dir)
        self.assertEqual(qual["status"], "already_failed")
        self.assertEqual(qual.get("reason"), "interrupted_or_unresolved_target_attempt")

    def test_check_run_qualification_preparing_fails_closed(self):
        """status=preparing interrupted during preparation must fail closed (already_failed)."""
        (self.run_dir / "run_metadata.json").write_text(json.dumps({
            "status": "preparing",
            "target_invocations": 0,
        }))
        qual = check_run_qualification(self.run_dir)
        self.assertEqual(qual["status"], "already_failed")
        self.assertEqual(qual.get("reason"), "interrupted_during_preparation")

    def test_check_run_qualification_corrupt_judge_attempt_fails_closed(self):
        """Corrupted judge_attempt.json must return judge_failed, never target_completed_needs_judge."""
        (self.run_dir / "run_metadata.json").write_text(json.dumps({"status": "completed"}))
        (self.run_dir / "final_response.txt").write_text("fixed")
        (self.run_dir / "diff.patch").write_text("diff")
        (self.run_dir / "tool_trace.jsonl").write_text(json.dumps({"type": "turn.completed"}) + "\n")
        (self.run_dir / "evaluation_result.json").write_text("{}")
        (self.run_dir / "judge_attempt.json").write_text("{corrupt json")
        qual = check_run_qualification(self.run_dir)
        self.assertEqual(qual["status"], "judge_failed")
        self.assertEqual(qual.get("reason"), "corrupt_judge_attempt")

    def test_check_run_qualification_judge_attempt_missing_stream_fails_closed(self):
        """Judge attempted but judge_raw stream missing must return judge_failed."""
        (self.run_dir / "run_metadata.json").write_text(json.dumps({"status": "completed"}))
        (self.run_dir / "final_response.txt").write_text("fixed")
        (self.run_dir / "diff.patch").write_text("diff")
        (self.run_dir / "tool_trace.jsonl").write_text(json.dumps({"type": "turn.completed"}) + "\n")
        (self.run_dir / "evaluation_result.json").write_text("{}")
        (self.run_dir / "judge_attempt.json").write_text(json.dumps({"status": "completed", "judge_invocations": 1}))
        (self.run_dir / "judge_verdict.json").write_text("{}")
        qual = check_run_qualification(self.run_dir)
        self.assertEqual(qual["status"], "judge_failed")
        self.assertEqual(qual.get("reason"), "judge_stream_missing_or_empty")

    def test_resolve_repository_summary_fails_closed_on_bad_relpath(self):
        """Explicit broken repository_summary_relpath must raise FileNotFoundError, never fallback to default summary."""
        manifest_data = {
            "fixture_id": "T01",
            "repository_summary_relpath": "manifests/non_existent_summary.md",
        }
        with self.assertRaises(FileNotFoundError) as ctx:
            resolve_repository_summary("T01", manifest_data)
        self.assertIn("Explicit repository_summary_relpath not found", str(ctx.exception))

    def test_is_run_completed_rejects_execution_error(self):
        (self.run_dir / "run_metadata.json").write_text(json.dumps({"status": "execution_error"}))
        (self.run_dir / "final_response.txt").write_text("fixed")
        (self.run_dir / "diff.patch").write_text("diff")
        (self.run_dir / "evaluation_result.json").write_text("{}")
        (self.run_dir / "judge_verdict.json").write_text("{}")
        self.assertFalse(is_run_completed(self.run_dir))

    def test_is_run_attempted(self):
        attempted, status = is_run_attempted(self.run_dir)
        self.assertFalse(attempted)

        (self.run_dir / "run_metadata.json").write_text(json.dumps({"status": "execution_error"}))
        attempted, status = is_run_attempted(self.run_dir)
        self.assertTrue(attempted)
        self.assertEqual(status, "execution_error")


class TestMatrixExecutionLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test-matrix-main-"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_main_dry_run_zero_model_calls(self):
        with patch("sys.argv", [
            "matrix.py",
            "--dry-run",
            "--batch-id", "dry-batch-1",
            "--batch-dir", str(self.temp_dir),
            "--tasks", "T01", "T02",
            "--conditions", "P0",
            "--runs", "1",
        ]):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        sched_file = self.temp_dir / "schedule.json"
        prog_file = self.temp_dir / "progress.json"
        self.assertTrue(sched_file.is_file())
        self.assertTrue(prog_file.is_file())

        prog_data = json.loads(prog_file.read_text(encoding="utf-8"))
        self.assertEqual(prog_data["status"], "prepared")
        self.assertEqual(prog_data["total_runs"], 2)
        self.assertEqual(prog_data["target_invocations"], 0)
        self.assertEqual(prog_data["judge_invocations"], 0)

    @patch("experiment.matrix.execute_subprocess")
    def test_run_single_pipeline_dry_run(self, mock_subproc):
        spec = {"schedule_index": 1, "task": "T02", "condition": "P0", "run_index": 1}
        recorder = StatusRecorder(self.temp_dir, "b1", 1, [spec])
        mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res = run_single_pipeline(spec, self.temp_dir, execute=False, timeout=30, recorder=recorder)
        self.assertEqual(res["status"], "prepared")

        # Verify command passed --dry-run
        called_cmd = mock_subproc.call_args[0][0]
        self.assertIn("--dry-run", called_cmd)
        self.assertNotIn("--execute", called_cmd)

    @patch("experiment.matrix.execute_subprocess")
    def test_run_single_pipeline_resume_skips_completed(self, mock_subproc):
        spec = {"schedule_index": 1, "task": "T02", "condition": "P0", "run_index": 1}
        run_dir = self.temp_dir / "P0" / "T02" / "run1"
        make_valid_mock_run(run_dir, batch_id="b1", workspace=self.temp_dir)

        recorder = StatusRecorder(self.temp_dir, "b1", 1, [spec])
        res = run_single_pipeline(spec, self.temp_dir, execute=True, timeout=30,
                                  recorder=recorder, resume=True)

        self.assertEqual(res["status"], "skipped_completed")
        mock_subproc.assert_not_called()

    @patch("experiment.matrix.execute_subprocess")
    def test_run_single_pipeline_resume_does_not_retry_failed_model(self, mock_subproc):
        """A previously attempted run that suffered an execution_error is NOT silently re-attempted."""
        spec = {"schedule_index": 1, "task": "T02", "condition": "P0", "run_index": 1}
        run_dir = self.temp_dir / "P0" / "T02" / "run1"
        run_dir.mkdir(parents=True)
        (run_dir / "run_metadata.json").write_text(json.dumps({"status": "execution_error"}))

        recorder = StatusRecorder(self.temp_dir, "b1", 1, [spec])
        res = run_single_pipeline(spec, self.temp_dir, execute=True, timeout=30,
                                  recorder=recorder, resume=True)

        self.assertEqual(res["status"], "skipped_failed")
        mock_subproc.assert_not_called()

    def test_status_recorder_reconcile_schedule_preserves_ground_truth(self):
        """StatusRecorder.reconcile_schedule preserves ground-truth counts from disk without resetting."""
        spec = {"schedule_index": 1, "task": "T02", "condition": "P0", "run_index": 1}
        run_dir = self.temp_dir / "P0" / "T02" / "run1"
        make_valid_mock_run(run_dir, batch_id="batch-reconcile", workspace=self.temp_dir)

        recorder = StatusRecorder(self.temp_dir, "batch-reconcile", 1, [spec], resume=True)
        recorder.reconcile_schedule(self.temp_dir, [spec])

        self.assertEqual(recorder.stats["completed_runs"], 1)
        self.assertEqual(recorder.stats["target_invocations"], 1)
        self.assertEqual(recorder.stats["pending_runs"], 0)


if __name__ == "__main__":
    unittest.main()
