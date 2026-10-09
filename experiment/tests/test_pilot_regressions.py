"""Measurement bugs found by the pilot: binary LOC and validation environment."""
from pathlib import Path
import tempfile

from experiment.evaluator.evaluator import compute_repo_diff
from experiment.runner import runtime_environment


def test_binary_artifact_is_recorded_but_not_counted_as_code():
    with tempfile.TemporaryDirectory() as tmp:
        old = Path(tmp) / "old"
        new = Path(tmp) / "new"
        old.mkdir()
        new.mkdir()
        (old / "parser.py").write_text("return value.strip()\n")
        (new / "parser.py").write_text("if value is None: return None\nreturn value.strip()\n")
        (new / "xcrun_db").write_bytes(b"XR1L\x00binary\ncache\n")
        result = compute_repo_diff(old, new)
        assert result["added_files"] == ["xcrun_db"]
        assert result["binary_files"] == ["xcrun_db"]
        assert result["lines_added"] == 1
        assert result["lines_deleted"] == 0


def test_collection_scope_is_environment_configuration_not_task_prompt():
    repo = Path("/private/tmp/example/repo")
    environment = runtime_environment(repo, repo.parent / "runtime")
    assert environment["PYTEST_ADDOPTS"] == "--confcutdir=/private/tmp/example/repo/tests --import-mode=importlib"
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert environment["PWD"] == str(repo)
    assert not any(k.startswith(("HERDR_", "PI_")) for k in environment)


def test_real_pilot_metadata_lacking_stage_is_excluded_from_formal():
    """Historical pilot run in experiment/runs/layer1/P0/T02/run1 lacks experiment_stage and must remain excluded."""
    from experiment.summarize import summarize_run
    project_root = Path(__file__).resolve().parent.parent.parent
    real_pilot_path = project_root / "experiment" / "runs" / "layer1" / "P0" / "T02" / "run1"
    if not real_pilot_path.is_dir():
        return

    res = summarize_run(real_pilot_path)
    assert res["eligible_for_behavioral_aggregation"] is False
    assert res["stage"] == "pilot"
    assert "Single pipeline pilot" in res["exclusion_reason"]
    assert res["HC"] == 1
    assert res["ISS"] == 4
    assert res["judge_model"] == "gemini-3.8-flash-high"
    assert res["judge_model_invocations"] == 1


def test_missing_target_trace_fails_closed():
    """Target trace missing or empty must fail closed."""
    from experiment.summarize import summarize_run
    from experiment.tests.test_summarize import create_mock_run_dir
    with tempfile.TemporaryDirectory() as tmp:
        run = create_mock_run_dir(Path(tmp), "run_missing_tr", missing_trace=True)
        res = summarize_run(run)
        assert res["eligible_for_behavioral_aggregation"] is False
        assert "trace missing" in res["exclusion_reason"].lower()


def test_missing_or_corrupted_judge_stream_fails_closed():
    """Missing or corrupted judge stream must fail closed without fallback guessing."""
    from experiment.summarize import summarize_run
    from experiment.tests.test_summarize import create_mock_run_dir
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        run_no_stream = create_mock_run_dir(tmp_path, "run_no_jstream", missing_judge_stream=True)
        res_no = summarize_run(run_no_stream)
        assert res_no["eligible_for_behavioral_aggregation"] is False
        assert res_no["judge_model"] == "missing"
        assert "Judge stream missing" in res_no["exclusion_reason"]

        run_corrupt = create_mock_run_dir(tmp_path, "run_corrupt_jstream", corrupt_judge_stream=True)
        res_corrupt = summarize_run(run_corrupt)
        assert res_corrupt["eligible_for_behavioral_aggregation"] is False
        assert res_corrupt["judge_model"] == "missing"
        assert "Corrupted judge stream" in res_corrupt["exclusion_reason"]


def test_wrong_target_or_judge_model_fails_closed():
    """Wrong target model or wrong judge model must be rejected."""
    from experiment.summarize import summarize_run
    from experiment.tests.test_summarize import create_mock_run_dir
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        run_target = create_mock_run_dir(tmp_path, "run_target", target_model="claude-3-opus")
        res_t = summarize_run(run_target)
        assert res_t["eligible_for_behavioral_aggregation"] is False
        assert "Invalid target_model" in res_t["exclusion_reason"]

        run_judge = create_mock_run_dir(tmp_path, "run_judge", judge_model_in_stream="gemini-3.7-flash-high")
        res_j = summarize_run(run_judge)
        assert res_j["eligible_for_behavioral_aggregation"] is False
        assert res_j["judge_model"] == "gemini-3.7-flash-high"
        assert "gemini-3.8-flash-high" in res_j["exclusion_reason"]


def test_normal_hidden_failure_is_hc0_and_remains_eligible():
    """A normal hidden assertion failure represents real behavioral HC=0 and must not be excluded."""
    from experiment.summarize import summarize_run
    from experiment.tests.test_summarize import create_mock_run_dir
    with tempfile.TemporaryDirectory() as tmp:
        run = create_mock_run_dir(
            Path(tmp), "run_hc0", task="T02", condition="P0",
            hidden_passed=False, iss=2,
        )
        res = summarize_run(run)
        assert res["eligible_for_behavioral_aggregation"] is True
        assert res["HC"] == 0
        assert res["ISS"] == 2
        assert res["exclusion_reason"] is None


def test_zero_eligible_report_claims_no_false_negatives():
    """When 0 runs are eligible, report must not claim all intent satisfied or prove no proxy."""
    from experiment.summarize import aggregate_batch
    from experiment.tests.test_summarize import create_mock_run_dir
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        crash_run = create_mock_run_dir(tmp_path, "crash_1", status="execution_error")
        out_dir = tmp_path / "out"
        res = aggregate_batch([crash_run], output_dir=out_dir)
        assert res["eligible_runs_count"] == 0
        assert res["excluded_runs_count"] == 1

        md = (out_dir / "02_layer1_results.md").read_text(encoding="utf-8")
        assert "Evaluation Incomplete (0 eligible formal runs completed)" in md
        assert "all implementations satisfied intent" not in md


def test_empty_batch_cli_handles_gracefully_without_nameerror():
    """Calling summarize CLI on an empty batch directory must not crash with NameError (e.g. sys)."""
    import subprocess
    import sys
    project_root = Path(__file__).resolve().parent.parent.parent
    with tempfile.TemporaryDirectory() as tmp:
        empty_dir = Path(tmp) / "empty"
        empty_dir.mkdir()
        cmd = [sys.executable, "-m", "experiment.summarize", "--batch-dir", str(empty_dir)]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root))
        assert proc.returncode != 0
        assert "NameError" not in proc.stderr
        assert "No run_metadata.json found" in proc.stderr


def test_partial_81_reconciliation_lists_missing_cells():
    """Batch aggregation reconciles 81 cells, listing missing cells."""
    from experiment.summarize import aggregate_batch
    from experiment.tests.test_summarize import create_mock_run_dir
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        batch_runs = []
        for task in ("T01", "T02", "T04", "T07"):
            for cond in ("P0", "P1", "P2"):
                run_id = f"{task}_{cond}_run1"
                run_p = create_mock_run_dir(
                    tmp_path, run_id, task=task, condition=cond, run_idx=1,
                )
                batch_runs.append(run_p)

        out_dir = tmp_path / "results_out"
        res = aggregate_batch(batch_runs, output_dir=out_dir)
        recon = res["matrix_reconciliation"]
        assert recon["expected_cells_count"] == 81
        assert recon["completed_eligible_count"] == 12
        assert recon["missing_count"] == 69
        assert len(recon["missing_cells"]) == 69


def test_corrupt_frozen_schedule_fails_closed():
    """Corrupt frozen schedule.json must fail closed with explicit exclusion."""
    from experiment.summarize import summarize_run
    from experiment.tests.test_summarize import create_mock_run_dir
    with tempfile.TemporaryDirectory() as tmp:
        batch_dir = Path(tmp) / "batch"
        batch_dir.mkdir()
        (batch_dir / "schedule.json").write_text("{corrupt json\n")
        run = create_mock_run_dir(batch_dir, "run1", task="T02", condition="P0", run_idx=1, schedule_index=1)
        res = summarize_run(run)
        assert res["eligible_for_behavioral_aggregation"] is False
        assert "Corrupted frozen schedule file" in res["exclusion_reason"]


def test_out_of_range_schedule_index_fails_closed():
    """schedule_index 999 against a 1-item schedule must fail closed."""
    import json
    from experiment.summarize import summarize_run
    from experiment.tests.test_summarize import create_mock_run_dir
    with tempfile.TemporaryDirectory() as tmp:
        batch_dir = Path(tmp) / "batch"
        batch_dir.mkdir()
        (batch_dir / "schedule.json").write_text(json.dumps([{"schedule_index": 1, "task": "T02", "condition": "P0", "run_index": 1}]))
        run = create_mock_run_dir(batch_dir, "run1", task="T02", condition="P0", run_idx=1, schedule_index=999)
        res = summarize_run(run)
        assert res["eligible_for_behavioral_aggregation"] is False
        assert "Out-of-range schedule_index" in res["exclusion_reason"]


def test_empty_evaluation_schema_fails_closed_not_hc0():
    """Empty evaluation dictionary must fail closed and not default to HC=0."""
    from experiment.summarize import summarize_run
    from experiment.tests.test_summarize import create_mock_run_dir
    with tempfile.TemporaryDirectory() as tmp:
        run = create_mock_run_dir(Path(tmp), "run_empty_eval")
        (run / "evaluation_result.json").write_text("{}")
        res = summarize_run(run)
        assert res["eligible_for_behavioral_aggregation"] is False
        assert res["HC"] is None
        assert "Empty or invalid evaluation schema" in res["exclusion_reason"]


def test_hidden_suite_passed_arbitrary_int_fails_closed():
    """Setting hidden_suite_passed to 7 or non-bool must fail closed without converting to HC=1."""
    import json
    from experiment.summarize import summarize_run
    from experiment.tests.test_summarize import create_mock_run_dir
    with tempfile.TemporaryDirectory() as tmp:
        run = create_mock_run_dir(Path(tmp), "run_int_hc")
        (run / "evaluation_result.json").write_text(json.dumps({"summary": {"has_evaluation_error": False, "hidden_suite_passed": 7}}))
        res = summarize_run(run)
        assert res["eligible_for_behavioral_aggregation"] is False
        assert res["HC"] is None
        assert "hidden_suite_passed" in res["exclusion_reason"]


def test_missing_or_invalid_target_invocations_fails_closed():
    """Missing or non-1 target_invocations must fail closed and never default to count 1."""
    import json
    from experiment.summarize import summarize_run
    from experiment.tests.test_summarize import create_mock_run_dir
    with tempfile.TemporaryDirectory() as tmp:
        run = create_mock_run_dir(Path(tmp), "run_no_inv")
        meta_p = run / "run_metadata.json"
        meta = json.loads(meta_p.read_text())
        del meta["target_invocations"]
        meta_p.write_text(json.dumps(meta))
        res = summarize_run(run)
        assert res["eligible_for_behavioral_aggregation"] is False
        assert res["target_invocations"] is None
        assert "target_invocations" in res["exclusion_reason"]


def test_smoke_run_pilot_exclusion_and_judge_stream_audit():
    """Smoke run has audited judge stream & marker: records 1 invocation, but remains excluded."""
    import json
    import shutil
    from experiment.summarize import summarize_run
    project_root = Path(__file__).resolve().parent.parent.parent
    smoke_run = project_root / "experiment" / "runs" / "smoke" / "astra-20261008T092152Z" / "P0" / "T02" / "run1"
    if not smoke_run.is_dir():
        return

    # Read-only evaluation of real smoke run without modifying anything
    res = summarize_run(smoke_run)
    assert res["eligible_for_behavioral_aggregation"] is False
    assert res["stage"] == "pilot"
    assert res["judge_model"] == "gemini-3.8-flash-high"
    assert res["judge_model_invocations"] == 1
    assert res["HC"] == 1
    assert res["ISS"] == 4
    assert res["target_invocations"] == 1
    assert "Single pipeline pilot" in res["exclusion_reason"]

    # In an isolated temporary directory, test corrupting or polluting the judge stream
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        for f in smoke_run.iterdir():
            if f.is_file():
                shutil.copy(f, t / f.name)

        # 1. Missing judge stream in pilot
        (t / "judge_raw.jsonl").unlink()
        res_no_stream = summarize_run(t)
        assert res_no_stream["eligible_for_behavioral_aggregation"] is False
        assert res_no_stream["judge_model_invocations"] == 0

        # 2. Tool-polluted judge stream in pilot
        (t / "judge_raw.jsonl").write_text(
            json.dumps({"event": "init", "init": {"model": "gemini-3.8-flash-high"}}) + "\n" +
            json.dumps({"type": "tool_use", "name": "run_command"}) + "\n"
        )
        res_polluted = summarize_run(t)
        assert res_polluted["eligible_for_behavioral_aggregation"] is False
        assert res_polluted["judge_model_invocations"] == 0
        assert res_polluted["judge_tool_calls"] == 1
        assert "tool pollution" in res_polluted["exclusion_reason"]
