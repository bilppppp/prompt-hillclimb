"""Unit and regression tests for experiment.summarize batch aggregation, error isolation, and fail-closed checks."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from experiment.summarize import (
    aggregate_batch,
    calculate_group_metrics,
    get_task_category,
    reconcile_81_matrix,
    summarize_run,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def create_mock_run_dir(
    parent: Path,
    run_id: str,
    task: str = "T02",
    condition: str = "P0",
    run_idx: int = 1,
    batch_id: str | None = "batch_layer1_001",
    schedule_index: int | None = 1,
    reasoning_effort: str = "medium",
    experiment_stage: str = "layer1/runs",
    target_model: str = "gpt-6-astra",
    status: str = "completed",
    has_eval_error: bool = False,
    hidden_passed: bool = True,
    visible_passed: bool = True,
    iss: int = 4,
    pe: int = 0,
    evc: int = 0,
    um: int = 0,
    sd: int = 2,
    under_val: bool = False,
    tool_pollution: bool = False,
    judge_model_in_stream: str = "gemini-3.8-flash-high",
    has_turn_completed: bool = True,
    has_turn_failed: bool = False,
    corrupt_trace: bool = False,
    missing_trace: bool = False,
    missing_judge_stream: bool = False,
    corrupt_judge_stream: bool = False,
) -> Path:
    run_dir = parent / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "experiment_stage": experiment_stage,
        "status": status,
        "condition": condition,
        "task": task,
        "task_id": task,
        "run_index": run_idx,
        "run": run_idx,
        "target_model": target_model,
        "reasoning_effort": reasoning_effort,
        "target_invocations": 1,
        "duration_seconds": 25.5,
    }
    if batch_id is not None:
        metadata["batch_id"] = batch_id
    if schedule_index is not None:
        metadata["schedule_index"] = schedule_index
    if status != "completed":
        metadata["error"] = "Process timed out"
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    evaluation = {
        "summary": {
            "has_evaluation_error": has_eval_error,
            "evaluation_errors": [{"error": "Internal error"}] if has_eval_error else [],
            "hidden_suite_passed": hidden_passed,
            "visible_suite_passed": visible_passed,
            "target_test_passed": True,
        },
        "evaluator_run": {
            "target_test": {"target": f"tests/test_{task}.py::test_target"},
            "visible_suite": {"summary_counts": {"passed": 5, "total": 5}},
            "hidden_suite": {"summary_counts": {"passed": 6 if hidden_passed else 3, "total": 6}},
        },
        "code_changes": {
            "modified_files": ["src/core.py"],
            "added_files": [],
            "deleted_files": [],
            "lines_added": 4,
            "lines_deleted": 1,
            "tests_edited": [],
            "binary_files": [],
        },
    }
    (run_dir / "evaluation_result.json").write_text(json.dumps(evaluation), encoding="utf-8")

    verdict = {
        "ISS": iss,
        "PE": pe,
        "EVC": evc,
        "UM": um,
        "SD": sd,
        "under_validation": under_val,
        "answers": ["ok"] * 7,
        "evidence": ["test passed"],
        "uncertainties": [],
    }
    (run_dir / "judge_verdict.json").write_text(json.dumps(verdict), encoding="utf-8")

    if not missing_judge_stream:
        if corrupt_judge_stream:
            (run_dir / "judge_raw.jsonl").write_text("{corrupt json line\n", encoding="utf-8")
        else:
            raw_events = [
                {"event": "init", "init": {"model": judge_model_in_stream}},
            ]
            if tool_pollution:
                raw_events.append({"type": "tool_call", "tool": "read_file"})
            raw_events.append({"type": "result", "structured_output": verdict})
            (run_dir / "judge_raw.jsonl").write_text(
                "\n".join(json.dumps(ev) for ev in raw_events) + "\n",
                encoding="utf-8",
            )

    if not missing_trace:
        if corrupt_trace:
            (run_dir / "tool_trace.jsonl").write_text("{corrupt trace\n", encoding="utf-8")
        else:
            trace_events = [
                {"type": "item.completed", "item": {"type": "command_execution", "command": f"pytest tests/test_{task}.py", "exit_code": 0, "aggregated_output": "1 passed"}},
            ]
            if has_turn_completed:
                trace_events.append({"type": "turn.completed", "status": "done"})
            if has_turn_failed:
                trace_events.append({"type": "turn.failed", "error": "fatal"})
            (run_dir / "tool_trace.jsonl").write_text(
                "\n".join(json.dumps(ev) for ev in trace_events) + "\n",
                encoding="utf-8",
            )

    (run_dir / "changed_files.txt").write_text("src/core.py\n", encoding="utf-8")
    return run_dir


class TestSummarize(unittest.TestCase):
    """Test suite for summarize.py batch aggregation, metric independence, and fail-closed checks."""

    def test_real_old_pilot_exclusion_without_stage(self):
        """Historical pilot run in experiment/runs/layer1/P0/T02/run1 lacks experiment_stage and must remain excluded."""
        real_pilot_path = PROJECT_ROOT / "experiment" / "runs" / "layer1" / "P0" / "T02" / "run1"
        if not real_pilot_path.is_dir():
            self.skipTest("Real pilot run dir not present on host")

        res = summarize_run(real_pilot_path)
        self.assertFalse(res["eligible_for_behavioral_aggregation"])
        self.assertEqual(res["stage"], "pilot")
        self.assertIn("Single pipeline pilot", res["exclusion_reason"])
        self.assertEqual(res["HC"], 1)
        self.assertEqual(res["ISS"], 4)

    def test_single_formal_run_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(tmp_path, "run_001", task="T02", condition="P0")
            res = summarize_run(run)

            self.assertTrue(res["eligible_for_behavioral_aggregation"])
            self.assertIsNone(res["exclusion_reason"])
            self.assertEqual(res["HC"], 1)
            self.assertEqual(res["ISS"], 4)
            self.assertEqual(res["PE"], 0)
            self.assertEqual(res["EVC"], 0)
            self.assertEqual(res["UM"], 0)
            self.assertEqual(res["SD"], 2)
            self.assertFalse(res["under_validation"])
            self.assertIn("Over-validation", res["category"])
            self.assertEqual(res["judge_model"], "gemini-3.8-flash-high")

    def test_missing_stage_is_excluded(self):
        """Missing or non-formal experiment_stage must not default to formal."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(tmp_path, "run_nostage", task="T02", condition="P0", experiment_stage=None)
            res = summarize_run(run)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("Missing or invalid formal experiment_stage", res["exclusion_reason"])

    def test_real_hidden_failure_is_hc0_and_eligible(self):
        """A normal hidden assertion failure represents real behavioral HC=0 and must not be excluded."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(
                tmp_path, "run_hc0", task="T02", condition="P0",
                hidden_passed=False, iss=2,
            )
            res = summarize_run(run)

            self.assertEqual(res["HC"], 0)
            self.assertEqual(res["ISS"], 2)
            self.assertTrue(res["eligible_for_behavioral_aggregation"])
            self.assertIsNone(res["exclusion_reason"])

    def test_execution_error_is_excluded_not_zero_scored(self):
        """Execution crashes must not be converted to ISS=0 or HC=0; they must be marked missing/excluded."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(
                tmp_path, "run_crash", task="T02", condition="P0",
                status="execution_error",
            )
            res = summarize_run(run)

            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("Target execution error", res["exclusion_reason"])
            self.assertIsNone(res["HC"])
            self.assertIsNone(res["ISS"])

    def test_evaluation_error_is_excluded(self):
        """Evaluation harness crashes must be marked excluded, not scored as 0."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(
                tmp_path, "run_eval_err", task="T02", condition="P0",
                has_eval_error=True,
            )
            res = summarize_run(run)

            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("Evaluation infrastructure error", res["exclusion_reason"])
            self.assertIsNone(res["HC"])
            self.assertIsNone(res["ISS"])

    def test_missing_or_corrupted_trace_is_excluded(self):
        """Missing or corrupted trace files must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Missing trace
            run1 = create_mock_run_dir(tmp_path, "run_missing_tr", missing_trace=True)
            res1 = summarize_run(run1)
            self.assertFalse(res1["eligible_for_behavioral_aggregation"])
            self.assertIn("Target trace missing", res1["exclusion_reason"])

            # Corrupted trace
            run2 = create_mock_run_dir(tmp_path, "run_corrupt_tr", corrupt_trace=True)
            res2 = summarize_run(run2)
            self.assertFalse(res2["eligible_for_behavioral_aggregation"])
            self.assertIn("Corrupted tool_trace", res2["exclusion_reason"])

    def test_trace_missing_turn_completed_or_turn_failed_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Trace lacks turn.completed
            run1 = create_mock_run_dir(tmp_path, "run_no_completed", has_turn_completed=False)
            res1 = summarize_run(run1)
            self.assertFalse(res1["eligible_for_behavioral_aggregation"])
            self.assertIn("turn.completed", res1["exclusion_reason"])

            # Trace has turn.failed
            run2 = create_mock_run_dir(tmp_path, "run_turn_failed", has_turn_failed=True)
            res2 = summarize_run(run2)
            self.assertFalse(res2["eligible_for_behavioral_aggregation"])
            self.assertIn("turn.failed", res2["exclusion_reason"])

    def test_missing_or_corrupted_judge_stream_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Missing stream
            run1 = create_mock_run_dir(tmp_path, "run_no_jstream", missing_judge_stream=True)
            res1 = summarize_run(run1)
            self.assertFalse(res1["eligible_for_behavioral_aggregation"])
            self.assertEqual(res1["judge_model"], "missing")
            self.assertIn("Judge stream missing", res1["exclusion_reason"])

            # Corrupted stream
            run2 = create_mock_run_dir(tmp_path, "run_corrupt_jstream", corrupt_judge_stream=True)
            res2 = summarize_run(run2)
            self.assertFalse(res2["eligible_for_behavioral_aggregation"])
            self.assertEqual(res2["judge_model"], "missing")

    def test_judge_wrong_init_model_is_excluded(self):
        """Judge stream with wrong init model must be rejected without fallback guessing."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(tmp_path, "run_wrong_jmodel", judge_model_in_stream="gemini-3.7-flash-high")
            res = summarize_run(run)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertEqual(res["judge_model"], "gemini-3.7-flash-high")
            self.assertIn("gemini-3.8-flash-high", res["exclusion_reason"])

    def test_wrong_target_model_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(tmp_path, "run_wrong_tmodel", target_model="claude-sonnet")
            res = summarize_run(run)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("Invalid target_model", res["exclusion_reason"])

    def test_judge_tool_pollution_is_excluded(self):
        """Tool pollution in judge invalidates neutrality and excludes the run."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(
                tmp_path, "run_judge_polluted", task="T02", condition="P0",
                tool_pollution=True,
            )
            res = summarize_run(run)

            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("tool", res["exclusion_reason"].lower())

    def test_task_categories(self):
        self.assertIn("Over-validation", get_task_category("T01"))
        self.assertIn("Over-validation", get_task_category("T02"))
        self.assertIn("Over-validation", get_task_category("T03"))
        self.assertIn("Proxy optimization", get_task_category("T04"))
        self.assertIn("Proxy optimization", get_task_category("T05"))
        self.assertIn("Proxy optimization", get_task_category("T06"))
        self.assertIn("Unnecessary machinery", get_task_category("T07"))
        self.assertIn("Unnecessary machinery", get_task_category("T08"))
        self.assertIn("Unnecessary machinery", get_task_category("T09"))

    def test_zero_eligible_report_claims_no_false_negatives(self):
        """When 0 runs are eligible, report must not claim all intent satisfied or prove no proxy."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            crash_run = create_mock_run_dir(tmp_path, "crash_1", status="execution_error")
            out_dir = tmp_path / "out"
            res = aggregate_batch([crash_run], output_dir=out_dir)

            self.assertEqual(res["eligible_runs_count"], 0)
            self.assertEqual(res["excluded_runs_count"], 1)

            md = (out_dir / "02_layer1_results.md").read_text(encoding="utf-8")
            self.assertIn("Evaluation Incomplete (0 eligible formal runs completed)", md)
            self.assertNotIn("all implementations satisfied intent", md)

    def test_empty_batch_cli_no_nameerror(self):
        """Calling summarize CLI on an empty batch directory must not crash with NameError (e.g. sys)."""
        with tempfile.TemporaryDirectory() as tmp:
            empty_dir = Path(tmp) / "empty"
            empty_dir.mkdir()
            cmd = [sys.executable, "-m", "experiment.summarize", "--batch-dir", str(empty_dir)]
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
            self.assertNotEqual(proc.returncode, 0)
            self.assertNotIn("NameError", proc.stderr)
            self.assertIn("No run_metadata.json found", proc.stderr)

    def test_81_matrix_reconciliation_and_batch_aggregation(self):
        """Batch aggregation processes runs, reconciles 81 cells, and outputs CSV, JSON, and MD."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            batch_runs = []

            # Populate 12 runs (4 tasks x 3 conditions)
            idx = 1
            for task in ("T01", "T02", "T04", "T07"):
                for cond in ("P0", "P1", "P2"):
                    run_id = f"{task}_{cond}_run1"
                    run_p = create_mock_run_dir(
                        tmp_path, run_id, task=task, condition=cond, run_idx=1,
                        schedule_index=idx,
                    )
                    batch_runs.append(run_p)
                    idx += 1

            out_dir = tmp_path / "results_out"
            res = aggregate_batch(batch_runs, output_dir=out_dir)

            recon = res["matrix_reconciliation"]
            self.assertEqual(recon["expected_cells_count"], 81)
            self.assertEqual(recon["completed_eligible_count"], 12)
            self.assertEqual(recon["missing_count"], 69)
            self.assertEqual(res["batch_completion_status"], "INCOMPLETE")
            self.assertEqual(res["readiness_for_formal_analysis"], "INCOMPLETE_DATA")

            md_content = (out_dir / "02_layer1_results.md").read_text(encoding="utf-8")
            self.assertIn("Missing Cells (69 of 81)", md_content)
            self.assertIn("Batch Status: INCOMPLETE", md_content)
            self.assertIn("Category A: Over-validation", md_content)
            self.assertIn("Category B: Proxy optimization", md_content)
            self.assertIn("Category C: Unnecessary machinery", md_content)

    def test_formal_gate_batch_id_enforcement(self):
        """Runs without non-empty string batch_id must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Missing batch_id
            run1 = create_mock_run_dir(tmp_path, "run_no_bid", batch_id=None)
            res1 = summarize_run(run1)
            self.assertFalse(res1["eligible_for_behavioral_aggregation"])
            self.assertIn("batch_id", res1["exclusion_reason"])

            # Empty string batch_id
            run2 = create_mock_run_dir(tmp_path, "run_empty_bid", batch_id="   ")
            res2 = summarize_run(run2)
            self.assertFalse(res2["eligible_for_behavioral_aggregation"])
            self.assertIn("batch_id", res2["exclusion_reason"])

    def test_formal_gate_schedule_index_enforcement(self):
        """Runs with missing, non-integer, boolean, or <= 0 schedule_index must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Missing schedule_index
            run1 = create_mock_run_dir(tmp_path, "run_no_sched", schedule_index=None)
            res1 = summarize_run(run1)
            self.assertFalse(res1["eligible_for_behavioral_aggregation"])
            self.assertIn("schedule_index", res1["exclusion_reason"])

            # Non-positive schedule_index
            run2 = create_mock_run_dir(tmp_path, "run_zero_sched", schedule_index=0)
            res2 = summarize_run(run2)
            self.assertFalse(res2["eligible_for_behavioral_aggregation"])
            self.assertIn("schedule_index", res2["exclusion_reason"])

            # Boolean schedule_index
            run3 = create_mock_run_dir(tmp_path, "run_bool_sched", schedule_index=True)
            res3 = summarize_run(run3)
            self.assertFalse(res3["eligible_for_behavioral_aggregation"])
            self.assertIn("schedule_index", res3["exclusion_reason"])

    def test_formal_gate_task_range_enforcement(self):
        """Tasks outside T01..T09 must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run1 = create_mock_run_dir(tmp_path, "run_t10", task="T10")
            res1 = summarize_run(run1)
            self.assertFalse(res1["eligible_for_behavioral_aggregation"])
            self.assertIn("Invalid task identifier", res1["exclusion_reason"])

    def test_formal_gate_run_index_range_enforcement(self):
        """Run index outside 1..3 must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run1 = create_mock_run_dir(tmp_path, "run_idx4", run_idx=4)
            res1 = summarize_run(run1)
            self.assertFalse(res1["eligible_for_behavioral_aggregation"])
            self.assertIn("run_index", res1["exclusion_reason"])

            run2 = create_mock_run_dir(tmp_path, "run_idx0", run_idx=0)
            res2 = summarize_run(run2)
            self.assertFalse(res2["eligible_for_behavioral_aggregation"])
            self.assertIn("run_index", res2["exclusion_reason"])

    def test_formal_gate_reasoning_effort_enforcement(self):
        """Non-medium reasoning effort must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run1 = create_mock_run_dir(tmp_path, "run_low_effort", reasoning_effort="low")
            res1 = summarize_run(run1)
            self.assertFalse(res1["eligible_for_behavioral_aggregation"])
            self.assertIn("reasoning_effort", res1["exclusion_reason"])

    def test_cross_batch_mixing_is_excluded(self):
        """Batch aggregation must reject runs belonging to a different batch_id."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_a = create_mock_run_dir(tmp_path, "run_a", task="T01", condition="P0", batch_id="batch_alpha")
            run_b = create_mock_run_dir(tmp_path, "run_b", task="T02", condition="P0", batch_id="batch_beta")

            res = aggregate_batch([run_a, run_b], expected_batch_id="batch_alpha")
            self.assertEqual(res["eligible_runs_count"], 1)
            self.assertEqual(res["excluded_runs_count"], 1)

            disqualified = [r for r in res["runs"] if r["run_id"] == "run_b"][0]
            self.assertFalse(disqualified["eligible_for_behavioral_aggregation"])
            self.assertIn("Cross-batch pollution", disqualified["exclusion_reason"])

    def test_duplicate_cell_is_not_double_weighted(self):
        """Duplicate cell runs must not be double counted or double-weighted in group metrics."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run1 = create_mock_run_dir(tmp_path, "run1", task="T02", condition="P0", run_idx=1, schedule_index=1)
            run1_dup = create_mock_run_dir(tmp_path, "run1_dup", task="T02", condition="P0", run_idx=1, schedule_index=1)

            res = aggregate_batch([run1, run1_dup])
            self.assertEqual(res["eligible_runs_count"], 1)
            self.assertEqual(res["excluded_runs_count"], 1)

            dup_run = [r for r in res["runs"] if r["run_id"] == "run1_dup"][0]
            self.assertFalse(dup_run["eligible_for_behavioral_aggregation"])
            self.assertIn("Duplicate cell", dup_run["exclusion_reason"])

            t02_p0 = res["task_groups"]["T02_P0"]
            self.assertEqual(t02_p0["n_eligible"], 1)

    def test_single_run_cli_preserves_rejected_metrics_for_audit(self):
        """Single-run CLI preserves factual metrics in metrics.json even when the run is excluded."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(tmp_path, "run_crash", status="execution_error")

            cmd = [sys.executable, "-m", "experiment.summarize", "--run-dir", str(run)]
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
            self.assertEqual(proc.returncode, 0)

            metrics_file = run / "metrics.json"
            self.assertTrue(metrics_file.is_file())
            data = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertFalse(data["eligible_for_behavioral_aggregation"])
            self.assertIn("Target execution error", data["exclusion_reason"])
            # Preserves factual evaluation metrics
            self.assertEqual(data["visible_passed"], 5)
            self.assertEqual(data["visible_total"], 5)

    def test_check_run_eligibility_interface(self):
        """p4 qualification check interface contract."""
        from experiment.summarize import check_run_eligibility
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_ok = create_mock_run_dir(tmp_path, "run_ok", task="T02", condition="P0", run_idx=1)
            res_ok = check_run_eligibility(run_ok)
            self.assertTrue(res_ok["is_eligible"])
            self.assertTrue(res_ok["has_complete_evidence"])
            self.assertEqual(res_ok["task"], "T02")
            self.assertEqual(res_ok["condition"], "P0")
            self.assertEqual(res_ok["run_index"], 1)
            self.assertIsNone(res_ok["exclusion_reason"])

            run_bad = create_mock_run_dir(tmp_path, "run_bad", missing_trace=True)
            res_bad = check_run_eligibility(run_bad)
            self.assertFalse(res_bad["is_eligible"])
            self.assertFalse(res_bad["has_complete_evidence"])
            self.assertIn("Target trace missing", res_bad["exclusion_reason"])

    def test_frozen_schedule_mismatch(self):
        """Mismatch between metadata and frozen schedule.json must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp) / "batch"
            batch_dir.mkdir()
            schedule = [
                {"schedule_index": 1, "task": "T01", "condition": "P0", "run_index": 1},
            ]
            (batch_dir / "schedule.json").write_text(json.dumps(schedule), encoding="utf-8")

            # Create run claiming schedule_index 1 but with task T02
            run_dir = create_mock_run_dir(
                batch_dir, "run_wrong_cell", task="T02", condition="P0", run_idx=1,
                schedule_index=1,
            )
            res = summarize_run(run_dir)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("Frozen schedule mismatch", res["exclusion_reason"])

    def test_corrupt_frozen_schedule_json_fails_closed(self):
        """Corrupt frozen schedule.json must fail closed without swallowing exceptions."""
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp) / "batch"
            batch_dir.mkdir()
            (batch_dir / "schedule.json").write_text("{corrupt json\n", encoding="utf-8")

            run_dir = create_mock_run_dir(
                batch_dir, "run1", task="T02", condition="P0", run_idx=1, schedule_index=1,
            )
            res = summarize_run(run_dir)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("Corrupted frozen schedule file", res["exclusion_reason"])

    def test_malformed_frozen_schedule_structure_fails_closed(self):
        """Malformed shape/indexing/duplicates in frozen schedule must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp) / "batch"
            batch_dir.mkdir()

            # 1. Not a list
            (batch_dir / "schedule.json").write_text(json.dumps({"task": "T01"}), encoding="utf-8")
            run_dir = create_mock_run_dir(batch_dir, "run1", task="T02", condition="P0", run_idx=1, schedule_index=1)
            res = summarize_run(run_dir)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("must be a non-empty list", res["exclusion_reason"])

            # 2. Empty list
            (batch_dir / "schedule.json").write_text(json.dumps([]), encoding="utf-8")
            res = summarize_run(run_dir)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("must be a non-empty list", res["exclusion_reason"])

            # 3. Schedule index does not match position
            bad_pos = [{"schedule_index": 2, "task": "T01", "condition": "P0", "run_index": 1}]
            (batch_dir / "schedule.json").write_text(json.dumps(bad_pos), encoding="utf-8")
            res = summarize_run(run_dir)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("matching position", res["exclusion_reason"])

            # 4. Duplicate schedule cell in frozen schedule
            dup_sched = [
                {"schedule_index": 1, "task": "T01", "condition": "P0", "run_index": 1},
                {"schedule_index": 2, "task": "T01", "condition": "P0", "run_index": 1},
            ]
            (batch_dir / "schedule.json").write_text(json.dumps(dup_sched), encoding="utf-8")
            res = summarize_run(run_dir)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("Duplicate cell", res["exclusion_reason"])

    def test_out_of_range_frozen_schedule_index_fails_closed(self):
        """schedule_index 999 or out of range must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp) / "batch"
            batch_dir.mkdir()
            schedule = [
                {"schedule_index": 1, "task": "T02", "condition": "P0", "run_index": 1},
            ]
            (batch_dir / "schedule.json").write_text(json.dumps(schedule), encoding="utf-8")

            run_dir = create_mock_run_dir(
                batch_dir, "run1", task="T02", condition="P0", run_idx=1, schedule_index=999,
            )
            res = summarize_run(run_dir)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIn("Out-of-range schedule_index", res["exclusion_reason"])

    def test_empty_evaluation_schema_or_missing_keys_fails_closed(self):
        """Evaluation schema with empty {} or missing critical keys must fail closed and not default to HC=0."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(tmp_path, "run_empty_eval")
            eval_path = run / "evaluation_result.json"

            # 1. Empty {}
            eval_path.write_text("{}", encoding="utf-8")
            res = summarize_run(run)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIsNone(res["HC"])
            self.assertIn("Empty or invalid evaluation schema", res["exclusion_reason"])

            # 2. Missing has_evaluation_error
            eval_path.write_text(json.dumps({"summary": {"hidden_suite_passed": False}}), encoding="utf-8")
            res = summarize_run(run)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIsNone(res["HC"])
            self.assertIn("missing boolean 'has_evaluation_error'", res["exclusion_reason"])

            # 3. Missing hidden_suite_passed
            eval_path.write_text(json.dumps({"summary": {"has_evaluation_error": False}}), encoding="utf-8")
            res = summarize_run(run)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIsNone(res["HC"])
            self.assertIn("missing boolean 'hidden_suite_passed'", res["exclusion_reason"])

    def test_mixed_batch_conflict_without_explicit_id_fails_closed(self):
        """Multiple batches discovered without explicit expected_batch_id report mixed batch conflict."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_a = create_mock_run_dir(tmp_path, "run_a", batch_id="batch_1")
            run_b = create_mock_run_dir(tmp_path, "run_b", batch_id="batch_2")

            res = aggregate_batch([run_a, run_b], expected_batch_id=None)
            self.assertIn("mixed_batch_conflict", res["batch_id"])
            self.assertEqual(res["eligible_runs_count"], 0)
            self.assertEqual(res["excluded_runs_count"], 2)
            self.assertEqual(res["readiness_for_formal_analysis"], "INCOMPLETE_DATA")
            self.assertEqual(res["batch_completion_status"], "INCOMPLETE")

    def test_evaluation_hidden_suite_passed_requires_exact_bool(self):
        """hidden_suite_passed must be exact boolean; arbitrary ints (e.g. 7, 0, 1) or strings fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(tmp_path, "run_eval_bool_check")
            eval_path = run / "evaluation_result.json"

            # 1. Arbitrary integer 7 must fail closed and not become HC=1
            eval_path.write_text(json.dumps({"summary": {"has_evaluation_error": False, "hidden_suite_passed": 7}}), encoding="utf-8")
            res = summarize_run(run)
            self.assertFalse(res["eligible_for_behavioral_aggregation"])
            self.assertIsNone(res["HC"])
            self.assertIn("missing boolean 'hidden_suite_passed'", res["exclusion_reason"])

            # 2. Integer 1 or 0 must fail closed
            eval_path.write_text(json.dumps({"summary": {"has_evaluation_error": False, "hidden_suite_passed": 1}}), encoding="utf-8")
            res1 = summarize_run(run)
            self.assertFalse(res1["eligible_for_behavioral_aggregation"])
            self.assertIsNone(res1["HC"])

            # 3. String "true" must fail closed
            eval_path.write_text(json.dumps({"summary": {"has_evaluation_error": False, "hidden_suite_passed": "true"}}), encoding="utf-8")
            res_s = summarize_run(run)
            self.assertFalse(res_s["eligible_for_behavioral_aggregation"])
            self.assertIsNone(res_s["HC"])

            # 4. Genuine boolean False remains eligible with HC=0
            eval_path.write_text(json.dumps({"summary": {"has_evaluation_error": False, "hidden_suite_passed": False}}), encoding="utf-8")
            res_f = summarize_run(run)
            self.assertTrue(res_f["eligible_for_behavioral_aggregation"])
            self.assertEqual(res_f["HC"], 0)

            # 5. Genuine boolean True remains eligible with HC=1
            eval_path.write_text(json.dumps({"summary": {"has_evaluation_error": False, "hidden_suite_passed": True}}), encoding="utf-8")
            res_t = summarize_run(run)
            self.assertTrue(res_t["eligible_for_behavioral_aggregation"])
            self.assertEqual(res_t["HC"], 1)

    def test_formal_completed_run_requires_exact_target_invocations_one(self):
        """Formal completed run requires explicit target_invocations == 1; missing, 0, negative, >1, or bool fails closed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = create_mock_run_dir(tmp_path, "run_invocations_check")
            meta_path = run / "run_metadata.json"
            base_meta = json.loads(meta_path.read_text(encoding="utf-8"))

            # 1. Missing target_invocations must NOT guess count 1; must fail closed
            del base_meta["target_invocations"]
            meta_path.write_text(json.dumps(base_meta), encoding="utf-8")
            res_missing = summarize_run(run)
            self.assertFalse(res_missing["eligible_for_behavioral_aggregation"])
            self.assertIsNone(res_missing["target_invocations"])
            self.assertIn("target_invocations", res_missing["exclusion_reason"])

            # 2. target_invocations == 0 must fail closed
            base_meta["target_invocations"] = 0
            meta_path.write_text(json.dumps(base_meta), encoding="utf-8")
            res_zero = summarize_run(run)
            self.assertFalse(res_zero["eligible_for_behavioral_aggregation"])
            self.assertIn("target_invocations", res_zero["exclusion_reason"])

            # 3. target_invocations == -1 must fail closed
            base_meta["target_invocations"] = -1
            meta_path.write_text(json.dumps(base_meta), encoding="utf-8")
            res_neg = summarize_run(run)
            self.assertFalse(res_neg["eligible_for_behavioral_aggregation"])
            self.assertIn("target_invocations", res_neg["exclusion_reason"])

            # 4. target_invocations == True (bool) must fail closed
            base_meta["target_invocations"] = True
            meta_path.write_text(json.dumps(base_meta), encoding="utf-8")
            res_bool = summarize_run(run)
            self.assertFalse(res_bool["eligible_for_behavioral_aggregation"])
            self.assertIn("target_invocations", res_bool["exclusion_reason"])

            # 5. target_invocations == 2 (>1) must fail closed
            base_meta["target_invocations"] = 2
            meta_path.write_text(json.dumps(base_meta), encoding="utf-8")
            res_two = summarize_run(run)
            self.assertFalse(res_two["eligible_for_behavioral_aggregation"])
            self.assertIn("target_invocations", res_two["exclusion_reason"])

            # 6. Explicit integer 1 must pass
            base_meta["target_invocations"] = 1
            meta_path.write_text(json.dumps(base_meta), encoding="utf-8")
            res_ok = summarize_run(run)
            self.assertTrue(res_ok["eligible_for_behavioral_aggregation"])
            self.assertEqual(res_ok["target_invocations"], 1)

    def test_pilot_judge_stream_audit_and_marker_verification(self):
        """Pilot run audits judge raw stream and completed marker to record invocations while remaining excluded."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Create a pilot run
            run = create_mock_run_dir(tmp_path, "pilot_run_audit", experiment_stage="pilot", condition="P0")
            # Update metadata stage to pilot
            meta_path = run / "run_metadata.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["experiment_stage"] = "pilot"
            meta["limitations"] = ["Single pilot is not evidence for formal 81-run aggregation."]
            meta_path.write_text(json.dumps(meta), encoding="utf-8")

            # 1. Clean valid stream + completed marker -> eligible=False, invocations=1, judge_model=gemini-3.8-flash-high
            res1 = summarize_run(run)
            self.assertFalse(res1["eligible_for_behavioral_aggregation"])
            self.assertEqual(res1["stage"], "pilot")
            self.assertEqual(res1["judge_model_invocations"], 1)
            self.assertEqual(res1["judge_model"], "gemini-3.8-flash-high")
            self.assertEqual(res1["ISS"], 4)
            self.assertEqual(res1["HC"], 1)

            # 2. Corrupt or tool-polluted stream -> invocations=0, eligible=False
            (run / "judge_raw.jsonl").write_text(
                json.dumps({"event": "init", "init": {"model": "gemini-3.8-flash-high"}}) + "\n" +
                json.dumps({"type": "tool_call", "tool": "terminal"}) + "\n",
                encoding="utf-8",
            )
            res2 = summarize_run(run)
            self.assertFalse(res2["eligible_for_behavioral_aggregation"])
            self.assertEqual(res2["judge_model_invocations"], 0)
            self.assertEqual(res2["judge_tool_calls"], 1)
            self.assertIn("tool pollution", res2["exclusion_reason"])

            # 3. Missing stream -> invocations=0, eligible=False
            (run / "judge_raw.jsonl").unlink()
            res3 = summarize_run(run)
            self.assertFalse(res3["eligible_for_behavioral_aggregation"])
            self.assertEqual(res3["judge_model_invocations"], 0)
            self.assertIn("missing or incomplete", res3["exclusion_reason"])


if __name__ == "__main__":
    unittest.main()
