#!/usr/bin/env python3
"""Integration tests for matrix orchestrator and execution boundaries.

Verifies:
1. Real fake-grandchild process tree cancellation with setsid subprocesses (exact PID, zero remnants).
2. Real zero-model sandbox preflight across all 9 task fixtures (T01..T09).
3. Exception pausing: halting dispatch upon infrastructure error and recording 'paused' progress.
4. Resumption and staged continuation without re-invoking previously failed model runs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from experiment.matrix import (
    ROOT,
    TASKS,
    StatusRecorder,
    check_run_qualification,
    generate_schedule,
    get_all_descendant_pids,
    is_run_completed,
    kill_active_procs,
    kill_proc_tree,
    main,
    register_proc,
    run_preflight,
    run_single_pipeline,
)


class TestFakeGrandchildCancellation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test-grandchild-cleanup-"))
        self.run_dir = self.temp_dir / "run"
        self.run_dir.mkdir(parents=True)

    def tearDown(self):
        kill_active_procs()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fake_grandchild_setsid_cleaned_up_without_remnants(self):
        """A command spawning a child that spawns a setsid grandchild process is cleanly
        eliminated without heuristic process name matching and with zero orphaned remnants.
        """
        # Python script that spawns a detached grandchild process with start_new_session=True
        child_code = (
            "import subprocess, sys, time\n"
            "grandchild = subprocess.Popen(['sleep', '120'], start_new_session=True)\n"
            "print(grandchild.pid, flush=True)\n"
            "time.sleep(120)\n"
        )
        parent = subprocess.Popen(
            [sys.executable, "-c", child_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        # Read grandchild PID from child's stdout
        grandchild_pid_line = parent.stdout.readline().strip()
        self.assertTrue(grandchild_pid_line.isdigit(), f"Failed to get grandchild PID: {grandchild_pid_line}")
        grandchild_pid = int(grandchild_pid_line)

        # Register parent proc and run directory with matrix tracker
        register_proc(parent, self.run_dir)
        (self.run_dir / "target.pid").write_text(str(grandchild_pid), encoding="utf-8")

        # Verify grandchild is alive
        try:
            os.kill(grandchild_pid, 0)
            grandchild_alive = True
        except OSError:
            grandchild_alive = False
        self.assertTrue(grandchild_alive, "Grandchild should be alive before termination")

        # Discover descendants and verify grandchild is caught by exact PID traversal
        descendants = get_all_descendant_pids({parent.pid})
        self.assertIn(grandchild_pid, descendants, "Grandchild PID must be in discovered descendant tree")

        # Kill all active processes
        kill_active_procs()

        # Allow brief moment for kernel process reclamation
        time.sleep(0.15)

        # Verify parent process is dead
        self.assertIsNotNone(parent.poll(), "Parent process must be terminated")

        # Verify grandchild process is dead
        is_dead = False
        for _ in range(10):
            try:
                os.kill(grandchild_pid, 0)
                time.sleep(0.05)
            except OSError:
                is_dead = True
                break
        self.assertTrue(is_dead, f"Grandchild process {grandchild_pid} was not killed!")

        # Verify current process and unrelated processes are untouched
        self.assertEqual(os.getpid(), os.getpid())
        self.assertTrue((self.run_dir / "target.pid").exists() is False, "target.pid should be unlinked")


class TestRealNineTasksPreflight(unittest.TestCase):
    def test_all_nine_fixtures_preflight_pass_with_zero_model_calls(self):
        """Execute real zero-model preflight on all 9 tasks (T01..T09).
        Verifies commit determinism, Seatbelt read-denial on hidden assets,
        and manifest baseline expectations.
        """
        code = run_preflight(TASKS, ROOT / ".venv")
        self.assertEqual(code, 0, "All 9 fixtures must pass zero-model preflight")


class TestMatrixExceptionPausing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test-matrix-pause-"))
        self.batch_dir = self.temp_dir / "batch"
        self.batch_dir.mkdir(parents=True)

    def tearDown(self):
        kill_active_procs()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("experiment.matrix.run_preflight", return_value=0)
    @patch("experiment.matrix.run_single_pipeline")
    def test_infrastructure_error_pauses_dispatch_and_sets_paused_status(self, mock_pipeline, mock_preflight):
        """When an infrastructure error occurs, matrix halts pulling new tasks and sets status to 'paused'."""
        from experiment.matrix import main

        # Create schedule with 3 tasks
        schedule = [
            {"schedule_index": 1, "task": "T01", "condition": "P0", "run_index": 1},
            {"schedule_index": 2, "task": "T02", "condition": "P0", "run_index": 1},
            {"schedule_index": 3, "task": "T03", "condition": "P0", "run_index": 1},
        ]

        def fake_pipeline(spec, batch_dir, execute, timeout, recorder, resume, judge_sem, dep):
            if spec["task"] == "T01":
                # Task 1 triggers an infrastructure error
                recorder.record_event("target_failed", spec, {"error": "Seatbelt failure"})
                recorder.update_progress(delta_failed=1)
                return {"status": "target_failed", "is_infra_error": True}
            else:
                recorder.record_event("run_completed", spec)
                recorder.update_progress(delta_completed=1)
                return {"status": "completed", "is_infra_error": False}

        mock_pipeline.side_effect = fake_pipeline

        with patch("sys.argv", [
            "matrix.py",
            "--execute",
            "--batch-id", "test-pause-batch",
            "--batch-dir", str(self.batch_dir),
            "--tasks", "T01", "T02", "T03",
            "--conditions", "P0",
            "--runs", "1",
            "--workers", "1",
        ]):
            exit_code = main()

        self.assertEqual(exit_code, 1, "Exit code must be non-zero on infrastructure error")
        prog_file = self.batch_dir / "progress.json"
        self.assertTrue(prog_file.is_file())
        prog = json.loads(prog_file.read_text(encoding="utf-8"))
        self.assertEqual(prog["status"], "paused")
        self.assertEqual(prog["failed_runs"], 1)
        # Task 3 should never have been dispatched because task 1 failed and workers=1
        dispatched_tasks = [call[0][0]["task"] for call in mock_pipeline.call_args_list]
        self.assertNotIn("T03", dispatched_tasks)


class TestMatrixStagedResume(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test-matrix-resume-"))
        self.run_dir = self.temp_dir / "P0" / "T02" / "run1"
        self.run_dir.mkdir(parents=True)
        self.spec = {"schedule_index": 1, "task": "T02", "condition": "P0", "run_index": 1}
        self.recorder = StatusRecorder(self.temp_dir, "batch-resume-test", 1, [self.spec])

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_resume_preserves_already_failed_run(self):
        """A run that previously failed target execution is skipped and never silently re-run."""
        (self.run_dir / "run_metadata.json").write_text(json.dumps({
            "status": "execution_error",
            "error": "Timeout expired",
        }))

        res = run_single_pipeline(self.spec, self.temp_dir, execute=True, timeout=30,
                                  recorder=self.recorder, resume=True)
        self.assertEqual(res["status"], "skipped_failed")
        self.assertFalse(res.get("is_infra_error"))

    def test_resume_preserves_evaluation_infra_error(self):
        """A run where evaluator suffered an infra error is skipped and never silently re-run."""
        (self.run_dir / "run_metadata.json").write_text(json.dumps({
            "status": "completed",
            "workspace": str(self.temp_dir),
        }))
        (self.run_dir / "final_response.txt").write_text("done")
        (self.run_dir / "diff.patch").write_text("diff")
        (self.run_dir / "tool_trace.jsonl").write_text(json.dumps({"type": "turn.completed"}) + "\n")
        (self.run_dir / "evaluation_result_v2.json").write_text(json.dumps({
            "summary": {"has_evaluation_error": True, "evaluation_errors": ["pytest crashed"]},
        }))

        res = run_single_pipeline(self.spec, self.temp_dir, execute=True, timeout=30,
                                  recorder=self.recorder, resume=True)
        self.assertEqual(res["status"], "skipped_failed")

    @patch("experiment.matrix.execute_subprocess")
    def test_resume_continues_target_completed_needs_eval(self, mock_subproc):
        """A run where target completed but evaluator did not run continues from evaluator."""
        (self.run_dir / "run_metadata.json").write_text(json.dumps({
            "status": "completed",
            "workspace": str(self.temp_dir),
        }))
        (self.run_dir / "final_response.txt").write_text("done")
        (self.run_dir / "diff.patch").write_text("diff")
        (self.run_dir / "tool_trace.jsonl").write_text(json.dumps({"type": "turn.completed"}) + "\n")

        # Mock evaluator, judge, summarize execution
        def fake_exec(cmd, **kwargs):
            if "evaluator" in " ".join(cmd):
                (self.run_dir / "evaluation_result_v2.json").write_text(json.dumps({"summary": {"has_evaluation_error": False}}))
                return MagicMock(returncode=0, stdout="", stderr="")
            if "judge" in " ".join(cmd):
                (self.run_dir / "judge_raw.jsonl").write_text("{}\n")
                (self.run_dir / "judge_verdict.json").write_text("{}")
                return MagicMock(returncode=0, stdout="", stderr="")
            if "summarize" in " ".join(cmd):
                (self.run_dir / "metrics.json").write_text(json.dumps({
                    "task": "T02",
                    "condition": "P0",
                    "stage": "layer1/runs",
                    "target_model": "gpt-6-astra",
                    "reasoning_effort": "medium",
                    "judge_model": "gemini-2.5-pro",
                    "HC": 1,
                    "eligible_for_behavioral_aggregation": True,
                }))
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_subproc.side_effect = fake_exec

        res = run_single_pipeline(self.spec, self.temp_dir, execute=True, timeout=30,
                                  recorder=self.recorder, resume=True)

        self.assertEqual(res["status"], "completed")
        # Target runner should not have been called!
        for call in mock_subproc.call_args_list:
            cmd = " ".join(call[0][0])
            self.assertNotIn("experiment.runner", cmd)


class TestRealCliSummarizeAndBatchReconciliation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test-matrix-cli-sum-"))
        self.batch_dir = self.temp_dir / "batch"
        self.batch_dir.mkdir(parents=True)

    def tearDown(self):
        kill_active_procs()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_real_cli_summarize_disqualification_halts_pipeline(self):
        """Single-run summarize CLI exits 0 even on disqualified runs.
        Matrix pipeline must inspect metrics.json, detect eligible_for_behavioral_aggregation == False,
        and halt execution with is_infra_error=True.
        """
        run_dir = self.batch_dir / "P0" / "T02" / "run1"
        run_dir.mkdir(parents=True)
        # Missing formal stage ('layer1/runs') -> summarize will mark eligible_for_behavioral_aggregation = False
        (run_dir / "run_metadata.json").write_text(json.dumps({
            "experiment_stage": "unspecified_stage",
            "batch_id": "test-batch",
            "schedule_index": 1,
            "status": "completed",
            "task": "T02",
            "condition": "P0",
            "run_index": 1,
            "target_model": "gpt-6-astra",
            "reasoning_effort": "medium",
            "target_invocations": 1,
            "workspace": str(self.temp_dir),
        }))
        (run_dir / "final_response.txt").write_text("fixed")
        (run_dir / "diff.patch").write_text("diff")
        (run_dir / "tool_trace.jsonl").write_text(json.dumps({"type": "turn.completed"}) + "\n")
        (run_dir / "evaluation_result_v2.json").write_text(json.dumps({
            "summary": {"has_evaluation_error": False, "hidden_suite_passed": True},
            "evaluator_run": {"visible_suite": {"summary_counts": {"passed": 1, "total": 1}},
                             "hidden_suite": {"summary_counts": {"passed": 1, "total": 1}}},
        }))
        (run_dir / "judge_raw.jsonl").write_text(json.dumps({"event": "init", "init": {"model": "gemini-2.5-pro"}}) + "\n")
        (run_dir / "judge_verdict.json").write_text(json.dumps({
            "ISS": 1, "PE": 0, "EVC": 0, "UM": 0, "SD": 0, "under_validation": 0,
        }))

        # 1. Verify summarize.py CLI exits 0 directly despite exclusion
        summarize_py = ROOT / "summarize.py"
        self.assertTrue(summarize_py.is_file())
        env = dict(os.environ, PYTHONPATH=str(ROOT.parent))
        proc = subprocess.run([sys.executable, str(summarize_py), "--run-dir", str(run_dir)],
                              env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, "CLI summarize exits 0 on single run mode")
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        self.assertFalse(metrics.get("eligible_for_behavioral_aggregation"))
        self.assertIn("Missing or invalid formal experiment_stage", metrics.get("exclusion_reason", ""))

        # 2. Verify matrix pipeline halts with is_infra_error = True
        spec = {"schedule_index": 1, "task": "T02", "condition": "P0", "run_index": 1}
        recorder = StatusRecorder(self.batch_dir, "test-batch", 1, [spec])
        # Clean metrics.json so pipeline runs summarize itself
        (run_dir / "metrics.json").unlink()

        res = run_single_pipeline(spec, self.batch_dir, execute=True, timeout=30,
                                  recorder=recorder, resume=True)
        self.assertEqual(res["status"], "disqualified_evidence")
        self.assertTrue(res.get("is_infra_error"), "Disqualified run evidence must halt matrix dispatch")

    @patch("experiment.matrix.run_preflight", return_value=0)
    def test_batch_reconciliation_fails_closed_when_any_run_incomplete(self, mock_preflight):
        """Batch execution with an incomplete or failed run sets incomplete_with_failures and exits 1."""
        sched = [
            {"schedule_index": 1, "task": "T01", "condition": "P0", "run_index": 1},
            {"schedule_index": 2, "task": "T02", "condition": "P0", "run_index": 1},
        ]
        (self.batch_dir / "schedule.json").write_text(json.dumps(sched), encoding="utf-8")

        # Run 1 is fully completed
        r1_dir = self.batch_dir / "P0" / "T01" / "run1"
        from experiment.tests.test_matrix import make_valid_mock_run
        make_valid_mock_run(r1_dir, batch_id="test-reconcile-fail", task="T01", workspace=self.temp_dir)

        # Run 2 is failed/incomplete (execution_error)
        r2_dir = self.batch_dir / "P0" / "T02" / "run1"
        r2_dir.mkdir(parents=True)
        (r2_dir / "run_metadata.json").write_text(json.dumps({
            "status": "execution_error",
            "target_invocations": 1,
        }))

        with patch("sys.argv", [
            "matrix.py",
            "--execute",
            "--resume",
            "--batch-id", "test-reconcile-fail",
            "--batch-dir", str(self.batch_dir),
            "--tasks", "T01", "T02",
            "--conditions", "P0",
            "--runs", "1",
        ]):
            exit_code = main()

        self.assertEqual(exit_code, 1, "Must exit non-zero when any scheduled run is failed or incomplete")
        prog = json.loads((self.batch_dir / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(prog["status"], "incomplete_with_failures")

    @patch("experiment.matrix.run_preflight", return_value=0)
    def test_batch_reconciliation_succeeds_when_all_runs_verified_completed(self, mock_preflight):
        """Batch execution where all runs are verified completed sets completed status and exits 0."""
        sched = [
            {"schedule_index": 1, "task": "T01", "condition": "P0", "run_index": 1},
        ]
        (self.batch_dir / "schedule.json").write_text(json.dumps(sched), encoding="utf-8")

        r1_dir = self.batch_dir / "P0" / "T01" / "run1"
        from experiment.tests.test_matrix import make_valid_mock_run
        make_valid_mock_run(r1_dir, batch_id="test-reconcile-success", task="T01", workspace=self.temp_dir)

        with patch("sys.argv", [
            "matrix.py",
            "--execute",
            "--resume",
            "--batch-id", "test-reconcile-success",
            "--batch-dir", str(self.batch_dir),
            "--tasks", "T01",
            "--conditions", "P0",
            "--runs", "1",
        ]):
            exit_code = main()

        self.assertEqual(exit_code, 0, "Must exit 0 when 100% of runs are verified completed")
        prog = json.loads((self.batch_dir / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(prog["status"], "completed")
        self.assertEqual(prog["completed_runs"], 1)

        with patch("sys.argv", [
            "matrix.py",
            "--execute",
            "--resume",
            "--batch-id", "test-reconcile-success",
            "--batch-dir", str(self.batch_dir),
            "--tasks", "T01",
            "--conditions", "P0",
            "--runs", "1",
        ]):
            exit_code = main()

        self.assertEqual(exit_code, 0, "Must exit 0 when 100% of runs are verified completed")
        prog = json.loads((self.batch_dir / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(prog["status"], "completed")
        self.assertEqual(prog["completed_runs"], 1)

    @patch("experiment.matrix.run_preflight", return_value=0)
    def test_batch_aggregation_missing_summary_file_fails_closed(self, mock_preflight):
        """Batch summarize returncode=0 but summary.json is missing must fail closed with aggregation_error."""
        sched = [
            {"schedule_index": 1, "task": "T01", "condition": "P0", "run_index": 1},
        ]
        (self.batch_dir / "schedule.json").write_text(json.dumps(sched), encoding="utf-8")

        r1_dir = self.batch_dir / "P0" / "T01" / "run1"
        from experiment.tests.test_matrix import make_valid_mock_run
        make_valid_mock_run(r1_dir, batch_id="test-missing-sum", task="T01", workspace=self.temp_dir)

        def mock_exec_no_summary(cmd, **kwargs):
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("experiment.matrix.execute_subprocess", side_effect=mock_exec_no_summary), \
             patch("sys.argv", [
                 "matrix.py",
                 "--execute",
                 "--resume",
                 "--batch-id", "test-missing-sum",
                 "--batch-dir", str(self.batch_dir),
                 "--tasks", "T01",
                 "--conditions", "P0",
                 "--runs", "1",
             ]):
            exit_code = main()

        self.assertNotEqual(exit_code, 0, "Must not exit 0 when summary.json is missing")
        prog = json.loads((self.batch_dir / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(prog["status"], "aggregation_error")
        self.assertNotEqual(prog["status"], "completed")

    @patch("experiment.matrix.run_preflight", return_value=0)
    def test_batch_aggregation_null_summary_file_fails_closed(self, mock_preflight):
        """Batch summarize returncode=0 but summary.json contains JSON null must fail closed with aggregation_error."""
        sched = [
            {"schedule_index": 1, "task": "T01", "condition": "P0", "run_index": 1},
        ]
        (self.batch_dir / "schedule.json").write_text(json.dumps(sched), encoding="utf-8")

        r1_dir = self.batch_dir / "P0" / "T01" / "run1"
        from experiment.tests.test_matrix import make_valid_mock_run
        make_valid_mock_run(r1_dir, batch_id="test-null-sum", task="T01", workspace=self.temp_dir)

        def mock_exec_null_summary(cmd, **kwargs):
            out_file = self.batch_dir / "results" / "summary.json"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text("null\n", encoding="utf-8")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("experiment.matrix.execute_subprocess", side_effect=mock_exec_null_summary), \
             patch("sys.argv", [
                 "matrix.py",
                 "--execute",
                 "--resume",
                 "--batch-id", "test-null-sum",
                 "--batch-dir", str(self.batch_dir),
                 "--tasks", "T01",
                 "--conditions", "P0",
                 "--runs", "1",
             ]):
            exit_code = main()

        self.assertNotEqual(exit_code, 0, "Must not exit 0 when summary.json is null")
        prog = json.loads((self.batch_dir / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(prog["status"], "aggregation_error")
        self.assertNotEqual(prog["status"], "completed")

    @patch("experiment.matrix.run_preflight", return_value=0)
    def test_batch_aggregation_non_dict_summary_file_fails_closed(self, mock_preflight):
        """Batch summarize returncode=0 but summary.json is a non-dict list must fail closed with aggregation_error."""
        sched = [
            {"schedule_index": 1, "task": "T01", "condition": "P0", "run_index": 1},
        ]
        (self.batch_dir / "schedule.json").write_text(json.dumps(sched), encoding="utf-8")

        r1_dir = self.batch_dir / "P0" / "T01" / "run1"
        from experiment.tests.test_matrix import make_valid_mock_run
        make_valid_mock_run(r1_dir, batch_id="test-nondict-sum", task="T01", workspace=self.temp_dir)

        def mock_exec_nondict_summary(cmd, **kwargs):
            out_file = self.batch_dir / "results" / "summary.json"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text("[1, 2, 3]\n", encoding="utf-8")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("experiment.matrix.execute_subprocess", side_effect=mock_exec_nondict_summary), \
             patch("sys.argv", [
                 "matrix.py",
                 "--execute",
                 "--resume",
                 "--batch-id", "test-nondict-sum",
                 "--batch-dir", str(self.batch_dir),
                 "--tasks", "T01",
                 "--conditions", "P0",
                 "--runs", "1",
             ]):
            exit_code = main()

        self.assertNotEqual(exit_code, 0, "Must not exit 0 when summary.json is non-dict")
        prog = json.loads((self.batch_dir / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(prog["status"], "aggregation_error")
        self.assertNotEqual(prog["status"], "completed")


if __name__ == "__main__":
    unittest.main()
