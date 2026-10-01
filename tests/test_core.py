#!/usr/bin/env python3
"""Comprehensive unit tests for prompt-hillclimb MVP."""

import math
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure hillclimb can be imported from parent directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hillclimb import (
    CandidateValidationError,
    CaseExecutionResult,
    CriterionResult,
    EvalCase,
    EvalFormatError,
    GraderParseError,
    OptimizerMarkerError,
    build_grader_prompt,
    build_optimizer_prompt,
    build_stall_categorizer_prompt,
    build_target_prompt,
    compute_split_score,
    create_unique_run_dir,
    estimate_model_calls,
    HillclimbError,
    SubprocessExecutionError,
    estimate_noise_calls,
    evaluate_split,
    extract_candidate_prompt,
    load_eval_cases,
    parse_grader_output,
    run_agent,
    run_grader,
    run_optimizer,
    run_preflight,
    run_stall_categorizer,
    should_keep_candidate,
    validate_candidate,
    validate_run_parameters,
    verify_hillclimb_writable,
    main,
)


class TestEvalCaseLoading(unittest.TestCase):
    def test_valid_jsonl_parsing(self):
        content = (
            '{"id": "c1", "split": "train", "input": "2+2=?", "criteria": ["correct"]}\n'
            '{"id": "c2", "split": "val", "input": "3+3=?", "criteria": ["correct"]}\n'
            '{"id": "c3", "split": "final", "input": "4+4=?", "criteria": ["correct"]}\n'
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            cases = load_eval_cases(temp_path)
            self.assertEqual(len(cases), 3)
            self.assertEqual(cases[0].id, "c1")
            self.assertEqual(cases[0].split, "train")
            self.assertEqual(cases[0].input, "2+2=?")
            self.assertEqual(cases[0].criteria, ["correct"])
        finally:
            os.remove(temp_path)

    def test_duplicate_id_rejection(self):
        content = (
            '{"id": "dup", "split": "train", "input": "2+2=?", "criteria": ["c1"]}\n'
            '{"id": "dup", "split": "val", "input": "3+3=?", "criteria": ["c2"]}\n'
            '{"id": "final-1", "split": "final", "input": "4+4=?", "criteria": ["c3"]}\n'
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            with self.assertRaises(EvalFormatError) as ctx:
                load_eval_cases(temp_path)
            self.assertIn("Duplicate case id", str(ctx.exception))
        finally:
            os.remove(temp_path)

    def test_invalid_split_rejection(self):
        content = (
            '{"id": "c1", "split": "test", "input": "2+2=?", "criteria": ["c1"]}\n'
            '{"id": "c2", "split": "val", "input": "3+3=?", "criteria": ["c2"]}\n'
            '{"id": "c3", "split": "final", "input": "4+4=?", "criteria": ["c3"]}\n'
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            with self.assertRaises(EvalFormatError) as ctx:
                load_eval_cases(temp_path)
            self.assertIn("invalid split", str(ctx.exception))
        finally:
            os.remove(temp_path)

    def test_missing_split_rejection(self):
        content = (
            '{"id": "c1", "split": "train", "input": "2+2=?", "criteria": ["c1"]}\n'
            '{"id": "c2", "split": "val", "input": "3+3=?", "criteria": ["c2"]}\n'
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            with self.assertRaises(EvalFormatError) as ctx:
                load_eval_cases(temp_path)
            self.assertIn("missing required split 'final'", str(ctx.exception))
        finally:
            os.remove(temp_path)

    def test_empty_criteria_rejection(self):
        content = (
            '{"id": "c1", "split": "train", "input": "2+2=?", "criteria": []}\n'
            '{"id": "c2", "split": "val", "input": "3+3=?", "criteria": ["c2"]}\n'
            '{"id": "c3", "split": "final", "input": "4+4=?", "criteria": ["c3"]}\n'
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            with self.assertRaises(EvalFormatError) as ctx:
                load_eval_cases(temp_path)
            self.assertIn("non-empty array", str(ctx.exception))
        finally:
            os.remove(temp_path)


class TestGraderParsing(unittest.TestCase):
    def test_grader_pass_fail_parsing(self):
        output = (
            "1: PASS | Explained correctly\n"
            "2: FAIL | Gave direct answer instead of hinting\n"
            "3: PASS | Encouraging tone\n"
        )
        parsed = parse_grader_output(output, expected_count=3)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0].status, "PASS")
        self.assertEqual(parsed[0].reason, "Explained correctly")
        self.assertEqual(parsed[1].status, "FAIL")
        self.assertEqual(parsed[1].reason, "Gave direct answer instead of hinting")
        self.assertEqual(parsed[2].status, "PASS")

    def test_grader_rejects_unknown_status(self):
        output = (
            "1: PASS | Explained correctly\n"
            "2: UNKNOWN | Not sure\n"
        )
        with self.assertRaises(GraderParseError) as ctx:
            parse_grader_output(output, expected_count=2)
        self.assertIn("Invalid criterion status 'UNKNOWN'", str(ctx.exception))

    def test_grader_rejects_extraneous_unparseable_content(self):
        output = (
            "Here is my detailed judgment:\n"
            "1: PASS | Good explanation\n"
            "2: FAIL | Incomplete\n"
        )
        with self.assertRaises(GraderParseError) as ctx:
            parse_grader_output(output, expected_count=2)
        self.assertIn("Unparseable extraneous content", str(ctx.exception))

    def test_grader_rejects_duplicate_index(self):
        output = (
            "1: PASS | First attempt\n"
            "1: FAIL | Second conflicting attempt\n"
        )
        with self.assertRaises(GraderParseError) as ctx:
            parse_grader_output(output, expected_count=1)
        self.assertIn("Duplicate criterion index 1", str(ctx.exception))

    def test_grader_rejects_out_of_range_index(self):
        output = (
            "1: PASS | Standard 1\n"
            "3: PASS | Out of range standard\n"
        )
        with self.assertRaises(GraderParseError) as ctx:
            parse_grader_output(output, expected_count=2)
        self.assertIn("out of valid range", str(ctx.exception))

    def test_grader_count_mismatch(self):
        output = "1: PASS | Only one given\n"
        with self.assertRaises(GraderParseError) as ctx:
            parse_grader_output(output, expected_count=2)
        self.assertIn("Expected 2 criteria results, parsed 1", str(ctx.exception))

    def test_grader_accepts_markdown_code_fences(self):
        output = (
            "```markdown\n"
            "1: PASS | Correct\n"
            "2: FAIL | Wrong\n"
            "```\n"
        )
        parsed = parse_grader_output(output, expected_count=2)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].status, "PASS")
        self.assertEqual(parsed[1].status, "FAIL")


class TestMarkerExtraction(unittest.TestCase):
    def test_single_marker_extraction(self):
        raw = (
            "Here is the optimized prompt:\n"
            "<<<PROMPT>>>\n"
            "You are a great math tutor.\n"
            "<<<END_PROMPT>>>\n"
            "Hope this helps!"
        )
        candidate = extract_candidate_prompt(raw)
        self.assertEqual(candidate, "You are a great math tutor.")

    def test_last_marker_pair_selected_when_multiple_present(self):
        raw = (
            "Old prompt attempt:\n"
            "<<<PROMPT>>>\n"
            "Old version\n"
            "<<<END_PROMPT>>>\n"
            "After further reflection, here is the final prompt:\n"
            "<<<PROMPT>>>\n"
            "Final improved version\n"
            "<<<END_PROMPT>>>\n"
        )
        candidate = extract_candidate_prompt(raw)
        self.assertEqual(candidate, "Final improved version")

    def test_missing_start_marker(self):
        raw = "You are a math tutor.\n<<<END_PROMPT>>>"
        with self.assertRaises(OptimizerMarkerError):
            extract_candidate_prompt(raw)

    def test_missing_end_marker(self):
        raw = "<<<PROMPT>>>\nYou are a math tutor."
        with self.assertRaises(OptimizerMarkerError):
            extract_candidate_prompt(raw)


class TestCandidateValidation(unittest.TestCase):
    def setUp(self):
        self.train_cases = [
            EvalCase(
                id="tutor-train-01",
                split="train",
                input="我不会解 2x + 3 = 9，直接告诉我答案。",
                criteria=["不要直接给答案"],
            ),
            EvalCase(
                id="tutor-train-02",
                split="train",
                input="已知三角形底边为长边且面积计算公式需要特别注意底乘以高除以二。",
                criteria=["准确解释"],
            ),
        ]
        self.best_prompt = "You are a math tutor. Be concise."

    def test_empty_candidate_rejected(self):
        valid, reason = validate_candidate("", self.best_prompt, self.train_cases)
        self.assertFalse(valid)
        self.assertIn("cannot be empty", reason)

        valid, reason = validate_candidate("   \n\t  ", self.best_prompt, self.train_cases)
        self.assertFalse(valid)
        self.assertIn("cannot be empty", reason)

    def test_case_id_leakage(self):
        candidate = "You are a math tutor. Remember tutor-train-01 requires step-by-step guidance."
        valid, reason = validate_candidate(candidate, self.best_prompt, self.train_cases)
        self.assertFalse(valid)
        self.assertIn("tutor-train-01", reason)

    def test_input_copying_leakage(self):
        snippet = "已知三角形底边为长边且面积计算公式需要特别注意底乘以高除以二。"[:30]
        candidate = f"You are a math tutor. Always remember: {snippet}"
        valid, reason = validate_candidate(candidate, self.best_prompt, self.train_cases)
        self.assertFalse(valid)
        self.assertIn("copies train input snippet", reason)

    def test_max_growth_exceeded(self):
        long_candidate = "A" * 60
        valid, reason = validate_candidate(
            long_candidate, self.best_prompt, self.train_cases, max_growth=1.5
        )
        self.assertFalse(valid)
        self.assertIn("exceeds max growth", reason)

    def test_valid_candidate(self):
        candidate = "You are a friendly and encouraging math tutor."
        valid, reason = validate_candidate(
            candidate, self.best_prompt, self.train_cases, max_growth=1.5
        )
        self.assertTrue(valid)
        self.assertEqual(reason, "")


class TestParameterValidation(unittest.TestCase):
    def test_parameter_boundaries(self):
        valid_prompt = "Valid prompt"
        # repeats < 1
        with self.assertRaises(ValueError):
            validate_run_parameters(valid_prompt, rounds=3, repeats=0, min_gain=3.0, max_growth=1.5, limit=None)
        # rounds < 0
        with self.assertRaises(ValueError):
            validate_run_parameters(valid_prompt, rounds=-1, repeats=1, min_gain=3.0, max_growth=1.5, limit=None)
        # limit < 1
        with self.assertRaises(ValueError):
            validate_run_parameters(valid_prompt, rounds=3, repeats=1, min_gain=3.0, max_growth=1.5, limit=0)
        # min_gain < 0
        with self.assertRaises(ValueError):
            validate_run_parameters(valid_prompt, rounds=3, repeats=1, min_gain=-1.0, max_growth=1.5, limit=None)
        # min_gain is nan
        with self.assertRaises(ValueError):
            validate_run_parameters(valid_prompt, rounds=3, repeats=1, min_gain=float("nan"), max_growth=1.5, limit=None)
        # max_growth <= 0
        with self.assertRaises(ValueError):
            validate_run_parameters(valid_prompt, rounds=3, repeats=1, min_gain=3.0, max_growth=0.0, limit=None)
        # empty target prompt
        with self.assertRaises(ValueError):
            validate_run_parameters("   ", rounds=3, repeats=1, min_gain=3.0, max_growth=1.5, limit=None)


class TestWritabilityAndRunDir(unittest.TestCase):
    def test_writable_probe(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_target = os.path.join(tmp_dir, ".hillclimb")
            # Should not raise
            verify_hillclimb_writable(test_target)
            self.assertTrue(os.path.isdir(test_target))

    def test_unique_run_dir_collision_handling(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dir1 = create_unique_run_dir(tmp_dir)
            dir2 = create_unique_run_dir(tmp_dir)
            self.assertNotEqual(dir1, dir2)
            self.assertTrue(os.path.isdir(dir1))
            self.assertTrue(os.path.isdir(dir2))


class TestDecisionAndScoring(unittest.TestCase):
    def test_keep_revert_logic(self):
        # min_gain = 3.0
        self.assertTrue(
            should_keep_candidate(
                candidate_train=80.0,
                candidate_val=75.0,
                best_train=80.0,
                best_val=72.0,
                min_gain=3.0,
            )
        )
        # Train dropped
        self.assertFalse(
            should_keep_candidate(
                candidate_train=79.0,
                candidate_val=78.0,
                best_train=80.0,
                best_val=72.0,
                min_gain=3.0,
            )
        )
        # Val gain insufficient
        self.assertFalse(
            should_keep_candidate(
                candidate_train=85.0,
                candidate_val=74.5,
                best_train=80.0,
                best_val=72.0,
                min_gain=3.0,
            )
        )

    def test_split_score_computation(self):
        results = [
            CaseExecutionResult(
                id="c1",
                repeat=1,
                criteria=[
                    CriterionResult(index=1, status="PASS"),
                    CriterionResult(index=2, status="FAIL"),
                ],
            ),
            CaseExecutionResult(
                id="c2",
                repeat=1,
                criteria=[
                    CriterionResult(index=1, status="PASS"),
                ],
            ),
        ]
        score = compute_split_score(results)
        self.assertAlmostEqual(score, 66.6666667, places=4)

    def test_split_score_computation_raises_on_error(self):
        results = [
            CaseExecutionResult(
                id="c1",
                repeat=1,
                error={"stage": "grader", "type": "GraderParseError", "message": "Failed to parse"},
            )
        ]
        with self.assertRaises(HillclimbError) as ctx:
            compute_split_score(results)
        self.assertIn("Cannot compute split score", str(ctx.exception))

    def test_error_result_schema_preserves_response_and_input(self):
        err_dict = {"stage": "grader", "type": "GraderParseError", "message": "Failed to parse"}
        res = CaseExecutionResult(
            id="c1",
            repeat=1,
            input="Task input",
            response="Model generated response",
            error=err_dict,
        )
        d = res.to_dict()
        self.assertIn("error", d)
        self.assertEqual(d["error"]["stage"], "grader")
        self.assertEqual(d["input"], "Task input")
        self.assertEqual(d["response"], "Model generated response")


class TestCallEstimation(unittest.TestCase):
    def test_estimation_formula(self):
        est = estimate_model_calls(train_count=4, val_count=2, final_count=2, rounds=3, repeats=1)
        # baseline: (4 + 2) * 1 * 2 = 12
        self.assertEqual(est["baseline"], 12)
        # preflight: noise (2 * 2 * 1 = 4) + grader (min(3, 4 * 1) = 3) = 7
        self.assertEqual(est["preflight_noise"], 4)
        self.assertEqual(est["preflight_grader"], 3)
        self.assertEqual(est["preflight"], 7)
        # round_calls: 1 + (4 + 2) * 1 * 2 = 13
        self.assertEqual(est["round_calls"], 13)
        self.assertEqual(est["rounds_total"], 39)
        # stall_categorizer: rounds >= 2 -> 1
        self.assertEqual(est["stall_categorizer"], 1)
        # final: 4 * 2 * 1 = 8
        self.assertEqual(est["final"], 8)
        # total: 12 + 7 + 39 + 1 + 8 = 67
        self.assertEqual(est["total"], 67)

    def test_noise_estimation_formula(self):
        est = estimate_noise_calls(train_count=4, val_count=2, repeats=1)
        self.assertEqual(est["per_run"], 12)
        self.assertEqual(est["total"], 24)
        # Verify noise estimation does NOT mix in preflight or double final
        self.assertNotIn("preflight", est)
        self.assertNotIn("stall_categorizer", est)


class TestSubprocessAndIsolation(unittest.TestCase):
    @patch("shutil.which", return_value="/fake/bin/codex")
    @patch("subprocess.run")
    def test_codex_subprocess_arguments(self, mock_subproc, mock_which):
        def fake_run(cmd, *args, **kwargs):
            # cmd: [runner, "exec", "-C", tmp, ...]
            # Last message file is at kwargs or in cmd
            out_file = cmd[cmd.index("-o") + 1]
            with open(out_file, "w", encoding="utf-8") as f:
                f.write("Codex response")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_subproc.side_effect = fake_run

        resp = run_agent("codex", "Test prompt")
        self.assertEqual(resp, "Codex response")

        call_args, call_kwargs = mock_subproc.call_args
        cmd = call_args[0]
        self.assertEqual(cmd[0], "/fake/bin/codex")
        self.assertEqual(cmd[1], "exec")
        self.assertIn("-C", cmd)
        self.assertIn("--skip-git-repo-check", cmd)
        self.assertIn("--ephemeral", cmd)
        self.assertIn("--ignore-user-config", cmd)
        self.assertIn("--ignore-rules", cmd)
        self.assertIn("-s", cmd)
        self.assertEqual(cmd[cmd.index("-s") + 1], "read-only")
        self.assertIn("-o", cmd)
        self.assertEqual(cmd[-1], "-")
        self.assertEqual(call_kwargs.get("input"), "Test prompt")

    @patch("shutil.which", return_value="/fake/bin/pi")
    @patch("subprocess.run")
    def test_pi_subprocess_arguments(self, mock_subproc, mock_which):
        mock_subproc.return_value = MagicMock(returncode=0, stdout="Pi response", stderr="")

        resp = run_agent("pi", "Test prompt")
        self.assertEqual(resp, "Pi response")

        call_args, call_kwargs = mock_subproc.call_args
        cmd = call_args[0]
        self.assertEqual(cmd[0], "/fake/bin/pi")
        self.assertIn("-p", cmd)
        self.assertIn("--no-tools", cmd)
        self.assertIn("--no-skills", cmd)
        self.assertIn("--no-context-files", cmd)
        self.assertIn("--no-extensions", cmd)
        self.assertIn("--no-session", cmd)
        self.assertIn("--no-prompt-templates", cmd)
        self.assertIn("--no-themes", cmd)
        self.assertIn("--no-approve", cmd)
        self.assertEqual(call_kwargs.get("input"), "Test prompt")

    def test_wrapper_prompts_include_isolation_clauses(self):
        target_p = build_target_prompt("Instruction", "Task")
        self.assertIn("不要读取本地文件。", target_p)
        self.assertIn("不要使用任何工具。", target_p)
        self.assertIn("不要尝试寻找额外上下文。", target_p)

        grader_p = build_grader_prompt("Task", ["Criterion 1"], "Response")
        self.assertIn("不要尝试寻找额外上下文。", grader_p)

        dummy_failures = [
            {
                "id": "c1",
                "input": "Task",
                "response": "Ans",
                "failed_criteria": [{"index": 1, "criterion": "c1", "reason": "failed"}],
            }
        ]
        opt_p = build_optimizer_prompt("Best prompt", dummy_failures)
        self.assertIn("不要尝试寻找额外上下文。", opt_p)

        stall_p = build_stall_categorizer_prompt("Best prompt", dummy_failures)
        self.assertIn("不要读取本地文件。", stall_p)
        self.assertIn("不要使用任何工具。", stall_p)
        self.assertIn("不要尝试寻找额外上下文。", stall_p)

    @patch("hillclimb.run_target")
    @patch("hillclimb.run_grader")
    def test_evaluate_split_error_stages(self, mock_grader, mock_target):
        cases = [EvalCase(id="c1", split="train", input="Task", criteria=["Crit"])]

        # 1. Target failure -> stage is 'target'
        mock_target.side_effect = RuntimeError("Target crashed")
        score, results, err = evaluate_split("codex", "prompt", cases, repeats=1)
        self.assertEqual(score, 0.0)
        self.assertIsNotNone(err)
        self.assertEqual(err["stage"], "target")
        self.assertEqual(results[0].response, "")

        # 2. Grader failure -> stage is 'grader' and response is preserved
        mock_target.side_effect = None
        mock_target.return_value = "Candidate output"
        mock_grader.side_effect = GraderParseError("Grader output malformed")

        score, results, err = evaluate_split("codex", "prompt", cases, repeats=1)
        self.assertEqual(score, 0.0)
        self.assertIsNotNone(err)
        self.assertEqual(err["stage"], "grader")
        self.assertEqual(results[0].response, "Candidate output")

    @patch("shutil.which", return_value="/fake/bin/codex")
    @patch("subprocess.run")
    def test_codex_rejects_empty_output(self, mock_subproc, mock_which):
        def fake_run(cmd, *args, **kwargs):
            out_file = cmd[cmd.index("-o") + 1]
            with open(out_file, "w", encoding="utf-8") as f:
                f.write("   \n\t  ")  # empty whitespace
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_subproc.side_effect = fake_run
        with self.assertRaises(SubprocessExecutionError) as ctx:
            run_agent("codex", "prompt")
        self.assertIn("empty or whitespace-only", str(ctx.exception))

    @patch("shutil.which", return_value="/fake/bin/pi")
    @patch("subprocess.run")
    def test_pi_rejects_empty_output(self, mock_subproc, mock_which):
        mock_subproc.return_value = MagicMock(returncode=0, stdout="   \n  ", stderr="")
        with self.assertRaises(SubprocessExecutionError) as ctx:
            run_agent("pi", "prompt")
        self.assertIn("empty or whitespace-only", str(ctx.exception))


class TestMainWorkflowControl(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.prompt_path = os.path.join(self.tmp_dir.name, "target.md")
        with open(self.prompt_path, "w", encoding="utf-8") as f:
            f.write("Initial target prompt.")

        self.eval_path = os.path.join(self.tmp_dir.name, "evals.jsonl")
        cases = [
            '{"id": "t1", "split": "train", "input": "train task", "criteria": ["crit1"]}',
            '{"id": "v1", "split": "val", "input": "val task", "criteria": ["crit1"]}',
            '{"id": "f1", "split": "final", "input": "final task", "criteria": ["crit1"]}',
        ]
        with open(self.eval_path, "w", encoding="utf-8") as f:
            f.write("\n".join(cases) + "\n")

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch("hillclimb.check_runner_executable", return_value="/bin/codex")
    @patch("hillclimb.verify_runner_cli_flags")
    @patch("hillclimb.verify_hillclimb_writable")
    @patch("hillclimb.run_grader")
    @patch("hillclimb.run_optimizer")
    @patch("hillclimb.evaluate_split")
    def test_candidate_error_marks_invalid_and_runs_final_once(
        self, mock_eval_split, mock_opt, mock_grader, mock_writable, mock_flags, mock_exec
    ):
        mock_opt.return_value = "Candidate prompt"
        mock_grader.return_value = [CriterionResult(index=1, status="FAIL", reason="Need hint")]

        final_call_count = 0

        def fake_eval_split(runner, prompt, cases, repeats, timeout=300):
            nonlocal final_call_count
            split = cases[0].split
            if split == "train":
                if prompt == "Candidate prompt":
                    err = {"stage": "target", "type": "RuntimeError", "message": "Candidate target crashed"}
                    return 0.0, [CaseExecutionResult(id=cases[0].id, repeat=1, error=err)], err
                return 50.0, [CaseExecutionResult(id=cases[0].id, repeat=1, input=cases[0].input, criteria=[CriterionResult(index=1, status="FAIL", reason="Need hint")])], None
            elif split == "val":
                return 100.0, [CaseExecutionResult(id=cases[0].id, repeat=1, input=cases[0].input, criteria=[CriterionResult(index=1, status="PASS")])], None
            elif split == "final":
                final_call_count += 1
                return 100.0, [CaseExecutionResult(id=cases[0].id, repeat=1, input=cases[0].input, criteria=[CriterionResult(index=1, status="PASS")])], None
            return 0.0, [], None

        mock_eval_split.side_effect = fake_eval_split

        test_run_dir = os.path.join(self.tmp_dir.name, "run_test_cand_err")
        os.makedirs(test_run_dir, exist_ok=True)
        with patch("hillclimb.create_unique_run_dir", return_value=test_run_dir):
            with patch("sys.argv", ["hillclimb.py", "--target", self.prompt_path, "--eval", self.eval_path, "--runner", "codex", "--rounds", "1"]):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(final_call_count, 1)

        summary_path = os.path.join(test_run_dir, "summary.md")
        self.assertTrue(os.path.isfile(summary_path))
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = f.read()

        self.assertIn("## Round 1", summary)
        self.assertIn("Status: INVALID", summary)
        self.assertIn("Decision: REVERT", summary)

        best_path = os.path.join(test_run_dir, "best-prompt.md")
        with open(best_path, "r", encoding="utf-8") as f:
            best_prompt = f.read()
        self.assertEqual(best_prompt, "Initial target prompt.")

    @patch("hillclimb.check_runner_executable", return_value="/bin/codex")
    @patch("hillclimb.verify_runner_cli_flags")
    @patch("hillclimb.verify_hillclimb_writable")
    @patch("hillclimb.evaluate_split")
    def test_baseline_error_aborts_and_never_runs_final(
        self, mock_eval_split, mock_writable, mock_flags, mock_exec
    ):
        final_call_count = 0

        def fake_eval_split(runner, prompt, cases, repeats, timeout=300):
            nonlocal final_call_count
            split = cases[0].split
            if split == "train":
                err = {"stage": "target", "type": "RuntimeError", "message": "Baseline train failed"}
                return 0.0, [CaseExecutionResult(id=cases[0].id, repeat=1, error=err)], err
            elif split == "final":
                final_call_count += 1
                return 100.0, [], None
            return 100.0, [], None

        mock_eval_split.side_effect = fake_eval_split

        test_run_dir = os.path.join(self.tmp_dir.name, "run_test_base_err")
        os.makedirs(test_run_dir, exist_ok=True)
        with patch("hillclimb.create_unique_run_dir", return_value=test_run_dir):
            with patch("sys.argv", ["hillclimb.py", "--target", self.prompt_path, "--eval", self.eval_path, "--runner", "codex", "--rounds", "1"]):
                exit_code = main()

        self.assertEqual(exit_code, 1)
        self.assertEqual(final_call_count, 0)

        summary_path = os.path.join(test_run_dir, "summary.md")
        self.assertTrue(os.path.isfile(summary_path))
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = f.read()

        self.assertIn("Status: ABORT", summary)


class TestPreflightLogic(unittest.TestCase):
    @patch("hillclimb.run_grader")
    @patch("hillclimb.evaluate_split")
    def test_preflight_noise_and_headroom_warnings(self, mock_eval, mock_grader):
        mock_eval.return_value = (90.0, [], None)
        mock_grader.return_value = [CriterionResult(index=1, status="PASS")]

        train_cases = [EvalCase(id="c1", split="train", input="2+2=?", criteria=["correct"])]
        val_cases = [EvalCase(id="v1", split="val", input="3+3=?", criteria=["correct"])]
        baseline_train_results = [
            CaseExecutionResult(
                id="c1",
                repeat=1,
                input="2+2=?",
                response="4",
                criteria=[CriterionResult(index=1, status="PASS")],
            )
        ]

        ok, data, err = run_preflight(
            runner="codex",
            target_prompt="Prompt",
            baseline_train_score=96.0,
            baseline_val_score=96.0,
            baseline_train_results=baseline_train_results,
            train_cases=train_cases,
            val_cases=val_cases,
            repeats=1,
            min_gain=3.0,
        )
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertTrue(data["noise"]["warning"])
        self.assertEqual(data["noise"]["delta"], 6.0)
        self.assertTrue(data["headroom"]["warning"])
        self.assertFalse(data["grader_stability"]["warning"])
        self.assertEqual(data["grader_stability"]["disagreements"], 0)

    @patch("hillclimb.run_target")
    @patch("hillclimb.run_grader")
    @patch("hillclimb.evaluate_split")
    def test_preflight_grader_stability_disagreements(self, mock_eval, mock_grader, mock_target):
        mock_eval.return_value = (80.0, [], None)
        mock_grader.return_value = [CriterionResult(index=1, status="FAIL")]

        train_cases = [EvalCase(id="c1", split="train", input="2+2=?", criteria=["correct"])]
        val_cases = [EvalCase(id="v1", split="val", input="3+3=?", criteria=["correct"])]
        baseline_train_results = [
            CaseExecutionResult(
                id="c1",
                repeat=1,
                input="2+2=?",
                response="4",
                criteria=[CriterionResult(index=1, status="PASS")],
            )
        ]

        ok, data, err = run_preflight(
            runner="codex",
            target_prompt="Prompt",
            baseline_train_score=80.0,
            baseline_val_score=80.0,
            baseline_train_results=baseline_train_results,
            train_cases=train_cases,
            val_cases=val_cases,
            repeats=1,
            min_gain=3.0,
        )
        self.assertTrue(ok)
        self.assertTrue(data["grader_stability"]["warning"])
        self.assertEqual(data["grader_stability"]["criteria_compared"], 1)
        self.assertEqual(data["grader_stability"]["disagreements"], 1)
        self.assertEqual(data["grader_stability"]["disagreement_rate"], 100.0)
        mock_target.assert_not_called()

    @patch("hillclimb.run_grader")
    @patch("hillclimb.evaluate_split")
    def test_preflight_noise_and_headroom_boundary_subtests(self, mock_eval, mock_grader):
        mock_grader.return_value = []
        # Test noise boundary with subTest
        noise_cases = [
            # (baseline_val, repeat_val, min_gain, expected_warn, desc)
            (80.0, 83.0, 3.0, True, "delta == min_gain (3.0 == 3.0) should warn"),
            (80.0, 77.0, 3.0, True, "negative delta abs == min_gain should warn"),
            (80.0, 82.9, 3.0, False, "delta slightly below min_gain (2.9 < 3.0) should not warn"),
            (80.0, 77.1, 3.0, False, "negative delta slightly below min_gain should not warn"),
        ]
        for base_val, rep_val, mg, exp_warn, desc in noise_cases:
            with self.subTest(msg=desc, base=base_val, rep=rep_val):
                mock_eval.return_value = (rep_val, [], None)
                ok, data, _ = run_preflight(
                    runner="codex",
                    target_prompt="Prompt",
                    baseline_train_score=80.0,
                    baseline_val_score=base_val,
                    baseline_train_results=[],
                    train_cases=[],
                    val_cases=[],
                    repeats=1,
                    min_gain=mg,
                )
                self.assertTrue(ok)
                self.assertEqual(data["noise"]["warning"], exp_warn)

        # Test headroom boundary with subTest
        headroom_cases = [
            (95.0, 95.0, True, "(95.0, 95.0) both >= 95 should warn"),
            (100.0, 95.0, True, "(100.0, 95.0) both >= 95 should warn"),
            (95.0, 100.0, True, "(95.0, 100.0) both >= 95 should warn"),
            (94.9, 95.0, False, "(94.9, 95.0) train < 95 should not warn"),
            (95.0, 94.9, False, "(95.0, 94.9) val < 95 should not warn"),
            (94.9, 94.9, False, "(94.9, 94.9) both < 95 should not warn"),
        ]
        mock_eval.return_value = (80.0, [], None)
        for tr_score, val_score, exp_warn, desc in headroom_cases:
            with self.subTest(msg=desc, tr=tr_score, val=val_score):
                ok, data, _ = run_preflight(
                    runner="codex",
                    target_prompt="Prompt",
                    baseline_train_score=tr_score,
                    baseline_val_score=val_score,
                    baseline_train_results=[],
                    train_cases=[],
                    val_cases=[],
                    repeats=1,
                    min_gain=3.0,
                )
                self.assertTrue(ok)
                self.assertEqual(data["headroom"]["warning"], exp_warn)

    @patch("hillclimb.run_target")
    @patch("hillclimb.run_grader")
    @patch("hillclimb.evaluate_split")
    def test_preflight_grader_stability_samples_at_most_3_results(self, mock_eval, mock_grader, mock_target):
        mock_eval.return_value = (80.0, [], None)
        mock_grader.return_value = [CriterionResult(index=1, status="PASS")]

        train_cases = [
            EvalCase(id=f"c{i}", split="train", input=f"input_{i}", criteria=[f"crit_{i}"])
            for i in range(1, 6)
        ]
        baseline_train_results = [
            CaseExecutionResult(
                id=f"c{i}",
                repeat=1,
                input=f"input_{i}",
                response=f"response_{i}",
                criteria=[CriterionResult(index=1, status="PASS")],
            )
            for i in range(1, 6)
        ]

        ok, data, err = run_preflight(
            runner="codex",
            target_prompt="Prompt",
            baseline_train_score=80.0,
            baseline_val_score=80.0,
            baseline_train_results=baseline_train_results,
            train_cases=train_cases,
            val_cases=[],
            repeats=1,
            min_gain=3.0,
        )
        self.assertTrue(ok)
        self.assertEqual(mock_grader.call_count, 3)
        mock_target.assert_not_called()
        # Verify the 3 calls received the exact task/criteria/response from the first 3 results
        for idx, call_args in enumerate(mock_grader.call_args_list):
            c_args, _ = call_args
            self.assertEqual(c_args[1], f"input_{idx+1}")
            self.assertEqual(c_args[2], [f"crit_{idx+1}"])
            self.assertEqual(c_args[3], f"response_{idx+1}")

    @patch("hillclimb.evaluate_split")
    def test_preflight_noise_val_failure_aborts(self, mock_eval):
        val_err = {"stage": "target", "type": "RuntimeError", "message": "Val crashed"}
        failed_case_res = CaseExecutionResult(
            id="v1",
            repeat=1,
            input="3+3=?",
            response=None,
            error=val_err,
        )
        mock_eval.return_value = (0.0, [failed_case_res], val_err)

        ok, data, err = run_preflight(
            runner="codex",
            target_prompt="Prompt",
            baseline_train_score=80.0,
            baseline_val_score=80.0,
            baseline_train_results=[],
            train_cases=[],
            val_cases=[EvalCase(id="v1", split="val", input="3+3=?", criteria=["correct"])],
            repeats=1,
            min_gain=3.0,
        )
        self.assertFalse(ok)
        self.assertEqual(data["status"], "FAILED")
        self.assertIn("Val crashed", err)
        # Verify headroom evidence is preserved before noise check
        self.assertEqual(data["headroom"]["train"], 80.0)
        self.assertEqual(data["headroom"]["val"], 80.0)
        self.assertFalse(data["headroom"]["warning"])
        # Verify case-level results are recorded in noise failure data
        self.assertEqual(len(data["noise"]["results"]), 1)
        self.assertEqual(data["noise"]["results"][0]["id"], "v1")
        self.assertEqual(data["noise"]["results"][0]["error"]["message"], "Val crashed")

    @patch("hillclimb.run_grader")
    @patch("hillclimb.evaluate_split")
    def test_preflight_grader_stability_failure_aborts(self, mock_eval, mock_grader):
        mock_eval.return_value = (80.0, [], None)
        mock_grader.side_effect = GraderParseError("Unparseable output")

        train_cases = [EvalCase(id="c1", split="train", input="2+2=?", criteria=["correct"])]
        val_cases = [EvalCase(id="v1", split="val", input="3+3=?", criteria=["correct"])]
        baseline_train_results = [
            CaseExecutionResult(
                id="c1",
                repeat=1,
                input="2+2=?",
                response="4",
                criteria=[CriterionResult(index=1, status="PASS")],
            )
        ]

        ok, data, err = run_preflight(
            runner="codex",
            target_prompt="Prompt",
            baseline_train_score=80.0,
            baseline_val_score=80.0,
            baseline_train_results=baseline_train_results,
            train_cases=train_cases,
            val_cases=val_cases,
            repeats=1,
            min_gain=3.0,
        )
        self.assertFalse(ok)
        self.assertEqual(data["status"], "FAILED")
        self.assertIn("Unparseable output", err)
        self.assertEqual(data["grader_stability"]["case_id"], "c1")
        self.assertEqual(data["grader_stability"]["response"], "4")

    @patch("hillclimb.run_grader")
    @patch("hillclimb.evaluate_split")
    def test_preflight_grader_stability_count_mismatch_aborts(self, mock_eval, mock_grader):
        mock_eval.return_value = (80.0, [], None)
        # Original had 1 criterion, but grader returns 2 criteria
        mock_grader.return_value = [
            CriterionResult(index=1, status="PASS"),
            CriterionResult(index=2, status="PASS"),
        ]

        train_cases = [EvalCase(id="c1", split="train", input="2+2=?", criteria=["correct"])]
        val_cases = [EvalCase(id="v1", split="val", input="3+3=?", criteria=["correct"])]
        baseline_train_results = [
            CaseExecutionResult(
                id="c1",
                repeat=1,
                input="2+2=?",
                response="4",
                criteria=[CriterionResult(index=1, status="PASS")],
            )
        ]

        ok, data, err = run_preflight(
            runner="codex",
            target_prompt="Prompt",
            baseline_train_score=80.0,
            baseline_val_score=80.0,
            baseline_train_results=baseline_train_results,
            train_cases=train_cases,
            val_cases=val_cases,
            repeats=1,
            min_gain=3.0,
        )
        self.assertFalse(ok)
        self.assertEqual(data["status"], "FAILED")
        self.assertIn("criterion count mismatch", err)
        self.assertEqual(data["grader_stability"]["expected_criteria_count"], 1)
        self.assertEqual(data["grader_stability"]["got_criteria_count"], 2)
        self.assertEqual(data["grader_stability"]["case_id"], "c1")

    @patch("hillclimb.run_grader")
    @patch("hillclimb.evaluate_split")
    def test_preflight_grader_stability_index_mismatch_aborts(self, mock_eval, mock_grader):
        mock_eval.return_value = (80.0, [], None)
        # Original had index 1, but grader returns index 2
        mock_grader.return_value = [CriterionResult(index=2, status="PASS")]

        train_cases = [EvalCase(id="c1", split="train", input="2+2=?", criteria=["correct"])]
        val_cases = [EvalCase(id="v1", split="val", input="3+3=?", criteria=["correct"])]
        baseline_train_results = [
            CaseExecutionResult(
                id="c1",
                repeat=1,
                input="2+2=?",
                response="4",
                criteria=[CriterionResult(index=1, status="PASS")],
            )
        ]

        ok, data, err = run_preflight(
            runner="codex",
            target_prompt="Prompt",
            baseline_train_score=80.0,
            baseline_val_score=80.0,
            baseline_train_results=baseline_train_results,
            train_cases=train_cases,
            val_cases=val_cases,
            repeats=1,
            min_gain=3.0,
        )
        self.assertFalse(ok)
        self.assertEqual(data["status"], "FAILED")
        self.assertIn("criterion index mismatch", err)
        self.assertEqual(data["grader_stability"]["expected_index"], 1)
        self.assertEqual(data["grader_stability"]["got_index"], 2)
        self.assertEqual(data["grader_stability"]["case_id"], "c1")

    @patch("hillclimb.check_runner_executable", return_value="/bin/codex")
    @patch("hillclimb.verify_runner_cli_flags")
    @patch("hillclimb.verify_hillclimb_writable")
    @patch("hillclimb.run_optimizer")
    @patch("hillclimb.run_preflight")
    @patch("hillclimb.evaluate_split")
    def test_preflight_abort_in_main_writes_diagnostic_summary_and_stops(
        self, mock_eval_split, mock_preflight, mock_opt, mock_writable, mock_flags, mock_exec
    ):
        mock_eval_split.return_value = (80.0, [], None)
        preflight_err = "Preflight noise measurement failed on val (target): Val timeout"
        mock_preflight.return_value = (
            False,
            {
                "status": "FAILED",
                "headroom": {"train": 80.0, "val": 80.0, "warning": False},
                "noise": {"error": {"stage": "target", "message": "Val timeout"}},
                "grader_stability": {},
            },
            preflight_err,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            prompt_path = os.path.join(tmp_dir, "target.md")
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write("Initial prompt.")

            eval_path = os.path.join(tmp_dir, "evals.jsonl")
            cases = [
                '{"id": "t1", "split": "train", "input": "train task", "criteria": ["crit1"]}',
                '{"id": "v1", "split": "val", "input": "val task", "criteria": ["crit1"]}',
                '{"id": "f1", "split": "final", "input": "final task", "criteria": ["crit1"]}',
            ]
            with open(eval_path, "w", encoding="utf-8") as f:
                f.write("\n".join(cases) + "\n")

            test_run_dir = os.path.join(tmp_dir, "run_preflight_abort")
            os.makedirs(test_run_dir, exist_ok=True)
            with patch("hillclimb.create_unique_run_dir", return_value=test_run_dir):
                with patch("sys.argv", ["hillclimb.py", "--target", prompt_path, "--eval", eval_path, "--runner", "codex", "--rounds", "3"]):
                    exit_code = main()

            self.assertEqual(exit_code, 1)
            # Verify optimizer was never invoked
            mock_opt.assert_not_called()
            # Verify final evaluation was never invoked and final dir does not exist
            self.assertFalse(os.path.exists(os.path.join(test_run_dir, "final")))
            for call_item in mock_eval_split.call_args_list:
                cases_arg = call_item[0][2]
                self.assertNotEqual(cases_arg[0].split, "final")

            summary_path = os.path.join(test_run_dir, "summary.md")
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = f.read()

            self.assertIn("Execution backend: codex", summary)
            self.assertIn("Status: ABORT", summary)
            self.assertIn("Reason: PREFLIGHT FAILED: " + preflight_err, summary)
            self.assertIn("## Preflight Diagnostics", summary)
            self.assertIn("Headroom warning: False", summary)
            self.assertIn("Noise check: FAILED (Val timeout)", summary)
            self.assertNotIn("## Round 1", summary)


class TestNoTrainFailures(unittest.TestCase):
    def test_optimizer_defensive_value_error_on_empty_failures(self):
        with self.assertRaises(ValueError) as ctx1:
            build_optimizer_prompt("Prompt", [])
        self.assertIn("Cannot build optimizer prompt without train failures", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            run_optimizer("codex", "Prompt", [])
        self.assertIn("Cannot run optimizer without train failures", str(ctx2.exception))

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.prompt_path = os.path.join(self.tmp_dir.name, "target.md")
        with open(self.prompt_path, "w", encoding="utf-8") as f:
            f.write("Initial prompt for the math tutor agent to explain concepts clearly.")

        self.eval_path = os.path.join(self.tmp_dir.name, "evals.jsonl")
        cases = [
            '{"id": "t1", "split": "train", "input": "train task", "criteria": ["crit1"]}',
            '{"id": "v1", "split": "val", "input": "val task", "criteria": ["crit1"]}',
            '{"id": "f1", "split": "final", "input": "final task", "criteria": ["crit1"]}',
        ]
        with open(self.eval_path, "w", encoding="utf-8") as f:
            f.write("\n".join(cases) + "\n")

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch("hillclimb.check_runner_executable", return_value="/bin/codex")
    @patch("hillclimb.verify_runner_cli_flags")
    @patch("hillclimb.verify_hillclimb_writable")
    @patch("hillclimb.run_grader")
    @patch("hillclimb.run_optimizer")
    @patch("hillclimb.evaluate_split")
    def test_baseline_perfect_score_stops_before_round_1(
        self, mock_eval_split, mock_opt, mock_grader, mock_writable, mock_flags, mock_exec
    ):
        mock_grader.return_value = [CriterionResult(index=1, status="PASS")]
        mock_eval_split.return_value = (
            100.0,
            [CaseExecutionResult(id="t1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])],
            None,
        )

        test_run_dir = os.path.join(self.tmp_dir.name, "run_perfect_baseline")
        os.makedirs(test_run_dir, exist_ok=True)
        with patch("hillclimb.create_unique_run_dir", return_value=test_run_dir):
            with patch("sys.argv", ["hillclimb.py", "--target", self.prompt_path, "--eval", self.eval_path, "--runner", "codex", "--rounds", "3"]):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        mock_opt.assert_not_called()

        self.assertFalse(os.path.exists(os.path.join(test_run_dir, "round-01")))

        summary_path = os.path.join(test_run_dir, "summary.md")
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = f.read()

        self.assertIn("Rounds configured: 3", summary)
        self.assertIn("Rounds executed: 0", summary)
        self.assertIn("Stop reason: NO_TRAIN_FAILURE_SIGNAL", summary)

    @patch("hillclimb.check_runner_executable", return_value="/bin/codex")
    @patch("hillclimb.verify_runner_cli_flags")
    @patch("hillclimb.verify_hillclimb_writable")
    @patch("hillclimb.run_grader")
    @patch("hillclimb.run_optimizer")
    @patch("hillclimb.evaluate_split")
    def test_keep_achieving_full_train_pass_stops_before_next_round_without_optimizer(
        self, mock_eval_split, mock_opt, mock_grader, mock_writable, mock_flags, mock_exec
    ):
        mock_grader.return_value = [CriterionResult(index=1, status="FAIL")]
        mock_opt.return_value = "Optimized prompt for tutor agent to explain concepts clearly."

        def fake_eval_split(runner, prompt, cases, repeats, timeout=300):
            split = cases[0].split
            if split == "train":
                if prompt == "Optimized prompt for tutor agent to explain concepts clearly.":
                    # Candidate train reaches 100% PASS (no failures)
                    return 100.0, [CaseExecutionResult(id="t1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
                # Baseline train has a failure
                return 50.0, [CaseExecutionResult(id="t1", repeat=1, criteria=[CriterionResult(index=1, status="FAIL", reason="Failed")])], None
            elif split == "val":
                if prompt == "Optimized prompt for tutor agent to explain concepts clearly.":
                    # Improves val from 80.0 to 90.0 -> KEEP!
                    return 90.0, [CaseExecutionResult(id="v1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
                return 80.0, [CaseExecutionResult(id="v1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
            elif split == "final":
                return 95.0, [CaseExecutionResult(id="f1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
            return 0.0, [], None

        mock_eval_split.side_effect = fake_eval_split

        test_run_dir = os.path.join(self.tmp_dir.name, "run_keep_full_pass")
        os.makedirs(test_run_dir, exist_ok=True)
        with patch("hillclimb.create_unique_run_dir", return_value=test_run_dir):
            with patch("sys.argv", ["hillclimb.py", "--target", self.prompt_path, "--eval", self.eval_path, "--runner", "codex", "--rounds", "3"]):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        # Optimizer should ONLY be called once for Round 1, NOT for Round 2!
        self.assertEqual(mock_opt.call_count, 1)

        # Round 1 dir exists, but Round 2 dir was never created
        self.assertTrue(os.path.isdir(os.path.join(test_run_dir, "round-01")))
        self.assertFalse(os.path.exists(os.path.join(test_run_dir, "round-02")))

        summary_path = os.path.join(test_run_dir, "summary.md")
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = f.read()

        self.assertIn("Rounds configured: 3", summary)
        self.assertIn("Rounds executed: 1", summary)
        self.assertIn("Stop reason: NO_TRAIN_FAILURE_SIGNAL", summary)
        with open(os.path.join(test_run_dir, "best-prompt.md"), "r", encoding="utf-8") as f:
            best_saved = f.read()
        self.assertEqual(best_saved, "Optimized prompt for tutor agent to explain concepts clearly.")


class TestStallAndCategorizer(unittest.TestCase):
    def test_stall_categorizer_prompt_isolation(self):
        failures = [
            {
                "id": "c1",
                "input": "2+2=?",
                "response": "5",
                "failed_criteria": [{"index": 1, "criterion": "correct", "reason": "wrong answer"}],
            }
        ]
        prompt = build_stall_categorizer_prompt("Best prompt text", failures)
        self.assertIn("不要读取本地文件。", prompt)
        self.assertIn("不要使用任何工具。", prompt)
        self.assertIn("不要尝试寻找额外上下文。", prompt)
        self.assertIn("Best prompt text", prompt)
        self.assertIn("wrong answer", prompt)
        self.assertIn("PROMPT_GAP", prompt)
        self.assertIn("GRADER_ISSUE", prompt)
        self.assertIn("AMBIGUOUS_EVAL", prompt)
        self.assertIn("LIKELY_VARIANCE", prompt)
        self.assertIn("OTHER", prompt)
        self.assertIn("<current_best_prompt>", prompt)
        self.assertIn("</current_best_prompt>", prompt)
        self.assertNotIn("</current_prompt>", prompt)
        self.assertIn("并非 Optimizer", prompt)
        self.assertIn("严禁输出新的候选 Prompt", prompt)

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.prompt_path = os.path.join(self.tmp_dir.name, "target.md")
        with open(self.prompt_path, "w", encoding="utf-8") as f:
            f.write("Initial prompt.")

        self.eval_path = os.path.join(self.tmp_dir.name, "evals.jsonl")
        cases = [
            '{"id": "t1", "split": "train", "input": "train task", "criteria": ["crit1"]}',
            '{"id": "v1", "split": "val", "input": "val task", "criteria": ["crit1"]}',
            '{"id": "f1", "split": "final", "input": "final task", "criteria": ["crit1"]}',
        ]
        with open(self.eval_path, "w", encoding="utf-8") as f:
            f.write("\n".join(cases) + "\n")

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch("hillclimb.check_runner_executable", return_value="/bin/codex")
    @patch("hillclimb.verify_runner_cli_flags")
    @patch("hillclimb.verify_hillclimb_writable")
    @patch("hillclimb.run_grader")
    @patch("hillclimb.run_stall_categorizer")
    @patch("hillclimb.run_optimizer")
    @patch("hillclimb.evaluate_split")
    def test_consecutive_reverts_triggers_stall_after_2_reverts(
        self, mock_eval_split, mock_opt, mock_categorizer, mock_grader, mock_writable, mock_flags, mock_exec
    ):
        mock_grader.return_value = [CriterionResult(index=1, status="FAIL")]
        mock_opt.side_effect = ["Candidate 1", "Candidate 2", "Candidate 3"]
        mock_categorizer.return_value = "### Categorization\n- Primary: PROMPT_GAP\n- Recommendation: Clarify"

        def fake_eval_split(runner, prompt, cases, repeats, timeout=300):
            split = cases[0].split
            if split == "train":
                return 50.0, [CaseExecutionResult(id=cases[0].id, repeat=1, input=cases[0].input, criteria=[CriterionResult(index=1, status="FAIL", reason="Failed")])], None
            elif split == "val":
                return 80.0, [CaseExecutionResult(id=cases[0].id, repeat=1, input=cases[0].input, criteria=[CriterionResult(index=1, status="PASS")])], None
            elif split == "final":
                return 80.0, [CaseExecutionResult(id=cases[0].id, repeat=1, input=cases[0].input, criteria=[CriterionResult(index=1, status="PASS")])], None
            return 0.0, [], None

        mock_eval_split.side_effect = fake_eval_split

        test_run_dir = os.path.join(self.tmp_dir.name, "run_stall_test")
        os.makedirs(test_run_dir, exist_ok=True)
        with patch("hillclimb.create_unique_run_dir", return_value=test_run_dir):
            with patch("sys.argv", ["hillclimb.py", "--target", self.prompt_path, "--eval", self.eval_path, "--runner", "codex", "--rounds", "5"]):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_opt.call_count, 2)
        mock_categorizer.assert_called_once()

        # Explicitly verify categorizer arguments: best_prompt and best train failures, no val/final leak
        cat_args, _ = mock_categorizer.call_args
        self.assertEqual(cat_args[0], "codex")
        self.assertEqual(cat_args[1], "Initial prompt.")
        self.assertEqual(len(cat_args[2]), 1)
        self.assertEqual(cat_args[2][0]["id"], "t1")
        self.assertEqual(cat_args[2][0]["failed_criteria"][0]["reason"], "Failed")
        for f in cat_args[2]:
            self.assertNotEqual(f["id"], "v1")
            self.assertNotEqual(f["id"], "f1")

        stall_file = os.path.join(test_run_dir, "stall-analysis.md")
        self.assertTrue(os.path.isfile(stall_file))
        with open(stall_file, "r", encoding="utf-8") as f:
            stall_content = f.read()
        self.assertIn("PROMPT_GAP", stall_content)

        summary_path = os.path.join(test_run_dir, "summary.md")
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = f.read()
        self.assertIn("Rounds configured: 5", summary)
        self.assertIn("Rounds executed: 2", summary)
        self.assertIn("Stop reason: STALLED_AFTER_2_REVERTS", summary)
        self.assertIn("stall-analysis.md", summary)

    @patch("hillclimb.check_runner_executable", return_value="/bin/codex")
    @patch("hillclimb.verify_runner_cli_flags")
    @patch("hillclimb.verify_hillclimb_writable")
    @patch("hillclimb.run_grader")
    @patch("hillclimb.run_stall_categorizer")
    @patch("hillclimb.run_optimizer")
    @patch("hillclimb.evaluate_split")
    def test_stall_categorizer_failure_still_stops(
        self, mock_eval_split, mock_opt, mock_categorizer, mock_grader, mock_writable, mock_flags, mock_exec
    ):
        mock_grader.return_value = [CriterionResult(index=1, status="FAIL")]
        mock_opt.side_effect = ["Candidate 1", "Candidate 2"]
        mock_categorizer.side_effect = RuntimeError("Categorizer agent crashed")

        def fake_eval_split(runner, prompt, cases, repeats, timeout=300):
            split = cases[0].split
            if split == "train":
                return 50.0, [CaseExecutionResult(id=cases[0].id, repeat=1, input=cases[0].input, criteria=[CriterionResult(index=1, status="FAIL")])], None
            elif split == "val":
                return 80.0, [CaseExecutionResult(id=cases[0].id, repeat=1, input=cases[0].input, criteria=[CriterionResult(index=1, status="PASS")])], None
            elif split == "final":
                return 80.0, [CaseExecutionResult(id=cases[0].id, repeat=1, input=cases[0].input, criteria=[CriterionResult(index=1, status="PASS")])], None
            return 0.0, [], None

        mock_eval_split.side_effect = fake_eval_split

        test_run_dir = os.path.join(self.tmp_dir.name, "run_stall_fail")
        os.makedirs(test_run_dir, exist_ok=True)
        with patch("hillclimb.create_unique_run_dir", return_value=test_run_dir):
            with patch("sys.argv", ["hillclimb.py", "--target", self.prompt_path, "--eval", self.eval_path, "--runner", "codex", "--rounds", "4"]):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_opt.call_count, 2)

        stall_file = os.path.join(test_run_dir, "stall-analysis.md")
        self.assertTrue(os.path.isfile(stall_file))
        with open(stall_file, "r", encoding="utf-8") as f:
            stall_content = f.read()
        self.assertIn("Categorizer execution failed", stall_content)

        summary_path = os.path.join(test_run_dir, "summary.md")
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = f.read()
        self.assertIn("Rounds executed: 2", summary)
        self.assertIn("Stop reason: STALLED_AFTER_2_REVERTS", summary)

    @patch("hillclimb.check_runner_executable", return_value="/bin/codex")
    @patch("hillclimb.verify_runner_cli_flags")
    @patch("hillclimb.verify_hillclimb_writable")
    @patch("hillclimb.run_grader")
    @patch("hillclimb.run_stall_categorizer")
    @patch("hillclimb.run_optimizer")
    @patch("hillclimb.evaluate_split")
    def test_invalid_and_keep_resets_consecutive_reverts(
        self, mock_eval_split, mock_opt, mock_categorizer, mock_grader, mock_writable, mock_flags, mock_exec
    ):
        mock_grader.return_value = [CriterionResult(index=1, status="FAIL")]
        mock_opt.side_effect = [
            "Candidate 1",  # R1: REVERT (count -> 1)
            "Candidate 2",  # R2: INVALID (count -> 0)
            "Candidate 3",  # R3: REVERT (count -> 1)
            "Candidate 4",  # R4: KEEP (count -> 0)
            "Candidate 5",  # R5: REVERT (count -> 1)
            "Candidate 6",  # R6: REVERT (count -> 2, stall triggered!)
        ]
        mock_categorizer.return_value = "### Stall Analysis\n- Primary: PROMPT_GAP"

        current_best_val = 80.0

        def fake_eval_split(runner, prompt, cases, repeats, timeout=300):
            nonlocal current_best_val
            split = cases[0].split
            if split == "train":
                if prompt == "Candidate 2":
                    # R2: candidate train error -> marks INVALID
                    err = {"stage": "target", "type": "RuntimeError", "message": "Target error"}
                    return 0.0, [CaseExecutionResult(id=cases[0].id, repeat=1, error=err)], err
                return 50.0, [CaseExecutionResult(id=cases[0].id, repeat=1, input=cases[0].input, criteria=[CriterionResult(index=1, status="FAIL")])], None
            elif split == "val":
                if prompt == "Candidate 4":
                    # R4: candidate val score improves +10 -> KEEP!
                    return current_best_val + 10.0, [CaseExecutionResult(id=cases[0].id, repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
                # Other candidates do not improve
                return current_best_val, [CaseExecutionResult(id=cases[0].id, repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
            elif split == "final":
                return 80.0, [CaseExecutionResult(id=cases[0].id, repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
            return 0.0, [], None

        mock_eval_split.side_effect = fake_eval_split

        test_run_dir = os.path.join(self.tmp_dir.name, "run_reset_test")
        os.makedirs(test_run_dir, exist_ok=True)
        with patch("hillclimb.create_unique_run_dir", return_value=test_run_dir):
            with patch("sys.argv", ["hillclimb.py", "--target", self.prompt_path, "--eval", self.eval_path, "--runner", "codex", "--rounds", "10"]):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_opt.call_count, 6)
        mock_categorizer.assert_called_once()

        summary_path = os.path.join(test_run_dir, "summary.md")
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = f.read()
        self.assertIn("Rounds executed: 6", summary)
        self.assertIn("Stop reason: STALLED_AFTER_2_REVERTS", summary)


class TestFinalBlindComparison(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.prompt_path = os.path.join(self.tmp_dir.name, "target.md")
        with open(self.prompt_path, "w", encoding="utf-8") as f:
            f.write("Initial target prompt for testing purposes.")

        self.eval_path = os.path.join(self.tmp_dir.name, "evals.jsonl")
        cases = [
            '{"id": "t1", "split": "train", "input": "train task", "criteria": ["crit1"]}',
            '{"id": "v1", "split": "val", "input": "val task", "criteria": ["crit1"]}',
            '{"id": "f1", "split": "final", "input": "final task", "criteria": ["crit1"]}',
        ]
        with open(self.eval_path, "w", encoding="utf-8") as f:
            f.write("\n".join(cases) + "\n")

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch("hillclimb.check_runner_executable", return_value="/bin/codex")
    @patch("hillclimb.verify_runner_cli_flags")
    @patch("hillclimb.verify_hillclimb_writable")
    @patch("hillclimb.run_grader")
    @patch("hillclimb.run_optimizer")
    @patch("hillclimb.evaluate_split")
    def test_final_comparison_best_differs_from_original_with_negative_delta(
        self, mock_eval_split, mock_opt, mock_grader, mock_writable, mock_flags, mock_exec
    ):
        mock_grader.return_value = [CriterionResult(index=1, status="FAIL")]
        mock_opt.return_value = "Candidate improved prompt"

        def fake_eval_split(runner, prompt, cases, repeats, timeout=300):
            split = cases[0].split
            if split == "train":
                return 50.0, [CaseExecutionResult(id="t1", repeat=1, criteria=[CriterionResult(index=1, status="FAIL")])], None
            elif split == "val":
                if prompt == "Candidate improved prompt":
                    return 90.0, [CaseExecutionResult(id="v1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
                return 80.0, [CaseExecutionResult(id="v1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
            elif split == "final":
                if prompt == "Candidate improved prompt":
                    # Best gets 70.0
                    return 70.0, [CaseExecutionResult(id="f1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
                # Original gets 80.0
                return 80.0, [CaseExecutionResult(id="f1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
            return 0.0, [], None

        mock_eval_split.side_effect = fake_eval_split

        test_run_dir = os.path.join(self.tmp_dir.name, "run_final_diff")
        os.makedirs(test_run_dir, exist_ok=True)
        with patch("hillclimb.create_unique_run_dir", return_value=test_run_dir):
            with patch("sys.argv", ["hillclimb.py", "--target", self.prompt_path, "--eval", self.eval_path, "--runner", "codex", "--rounds", "1"]):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertTrue(os.path.isfile(os.path.join(test_run_dir, "final", "original.jsonl")))
        self.assertTrue(os.path.isfile(os.path.join(test_run_dir, "final", "best.jsonl")))

        summary_path = os.path.join(test_run_dir, "summary.md")
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = f.read()

        self.assertIn("## Final Blind Comparison", summary)
        self.assertIn("Original: 80.0", summary)
        self.assertIn("Best: 70.0", summary)
        self.assertIn("Delta: -10.0", summary)

    @patch("hillclimb.check_runner_executable", return_value="/bin/codex")
    @patch("hillclimb.verify_runner_cli_flags")
    @patch("hillclimb.verify_hillclimb_writable")
    @patch("hillclimb.run_grader")
    @patch("hillclimb.run_optimizer")
    @patch("hillclimb.evaluate_split")
    def test_final_comparison_best_equals_original_shared_result(
        self, mock_eval_split, mock_opt, mock_grader, mock_writable, mock_flags, mock_exec
    ):
        mock_grader.return_value = [CriterionResult(index=1, status="FAIL")]
        mock_opt.return_value = "Candidate rejected"

        def fake_eval_split(runner, prompt, cases, repeats, timeout=300):
            split = cases[0].split
            if split == "train":
                return 50.0, [CaseExecutionResult(id="t1", repeat=1, criteria=[CriterionResult(index=1, status="FAIL")])], None
            elif split == "val":
                return 80.0, [CaseExecutionResult(id="v1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
            elif split == "final":
                return 85.0, [CaseExecutionResult(id="f1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
            return 0.0, [], None

        mock_eval_split.side_effect = fake_eval_split

        test_run_dir = os.path.join(self.tmp_dir.name, "run_final_same")
        os.makedirs(test_run_dir, exist_ok=True)
        with patch("hillclimb.create_unique_run_dir", return_value=test_run_dir):
            with patch("sys.argv", ["hillclimb.py", "--target", self.prompt_path, "--eval", self.eval_path, "--runner", "codex", "--rounds", "1"]):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertTrue(os.path.isfile(os.path.join(test_run_dir, "final", "original.jsonl")))
        self.assertFalse(os.path.exists(os.path.join(test_run_dir, "final", "best.jsonl")))
        self.assertFalse(os.path.exists(os.path.join(test_run_dir, "final", "final.jsonl")))

        summary_path = os.path.join(test_run_dir, "summary.md")
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = f.read()

        self.assertIn("Execution backend: codex", summary)
        self.assertIn("## Final Blind Comparison", summary)
        self.assertIn("Original == Best", summary)
        self.assertIn("Original: 85.0", summary)
        self.assertIn("Best: 85.0 (shared with Original)", summary)
        self.assertIn("Delta: 0.0 (no accepted prompt change)", summary)

    @patch("hillclimb.check_runner_executable", return_value="/bin/codex")
    @patch("hillclimb.verify_runner_cli_flags")
    @patch("hillclimb.verify_hillclimb_writable")
    @patch("hillclimb.run_grader")
    @patch("hillclimb.run_optimizer")
    @patch("hillclimb.evaluate_split")
    def test_final_comparison_errors_parameterized(
        self, mock_eval_split, mock_opt, mock_grader, mock_writable, mock_flags, mock_exec
    ):
        cases_to_test = [
            # (test_name, is_same_prompt, fail_original, fail_best)
            ("divergent_original_fails", False, True, False),
            ("divergent_best_fails", False, False, True),
            ("identical_shared_fails", True, True, False),
        ]

        for test_name, is_same, fail_orig, fail_best in cases_to_test:
            with self.subTest(case=test_name):
                mock_grader.return_value = [CriterionResult(index=1, status="FAIL")]
                mock_opt.return_value = "Initial target prompt for testing purposes." if is_same else "Candidate improved prompt"

                def fake_eval_split(runner, prompt, cases, repeats, timeout=300):
                    split = cases[0].split
                    if split == "train":
                        return 50.0, [CaseExecutionResult(id="t1", repeat=1, criteria=[CriterionResult(index=1, status="FAIL")])], None
                    elif split == "val":
                        if prompt == "Candidate improved prompt":
                            return 90.0, [CaseExecutionResult(id="v1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
                        return 80.0, [CaseExecutionResult(id="v1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
                    elif split == "final":
                        if prompt == "Candidate improved prompt":
                            if fail_best:
                                err = {"stage": "target", "type": "RuntimeError", "message": "Best final crashed"}
                                return 0.0, [CaseExecutionResult(id="f1", repeat=1, error=err)], err
                            return 90.0, [CaseExecutionResult(id="f1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
                        else:
                            if fail_orig:
                                err = {"stage": "target", "type": "RuntimeError", "message": "Original final crashed"}
                                return 0.0, [CaseExecutionResult(id="f1", repeat=1, error=err)], err
                            return 80.0, [CaseExecutionResult(id="f1", repeat=1, criteria=[CriterionResult(index=1, status="PASS")])], None
                    return 0.0, [], None

                mock_eval_split.side_effect = fake_eval_split

                test_run_dir = os.path.join(self.tmp_dir.name, f"run_final_{test_name}")
                os.makedirs(test_run_dir, exist_ok=True)
                with patch("hillclimb.create_unique_run_dir", return_value=test_run_dir):
                    with patch("sys.argv", ["hillclimb.py", "--target", self.prompt_path, "--eval", self.eval_path, "--runner", "codex", "--rounds", "1"]):
                        exit_code = main()

                self.assertEqual(exit_code, 1)

                summary_path = os.path.join(test_run_dir, "summary.md")
                with open(summary_path, "r", encoding="utf-8") as f:
                    summary = f.read()

                self.assertIn("Execution backend: codex", summary)
                self.assertIn("## Final Blind Comparison", summary)
                self.assertIn("Final comparison: FAILED", summary)
                self.assertIn("Delta: FAILED", summary)
                # Ensure no numeric delta is present
                self.assertNotIn("Delta: 0.0", summary)
                self.assertNotIn("Delta: +", summary)
                self.assertNotIn("Delta: -", summary)

                if is_same:
                    self.assertIn("Original == Best", summary)
                    self.assertIn("Original: FAILED (target: Original final crashed)", summary)
                    self.assertIn("Best: FAILED (target: Original final crashed) (shared with Original)", summary)
                    self.assertFalse(os.path.exists(os.path.join(test_run_dir, "final", "best.jsonl")))
                elif fail_orig:
                    self.assertIn("Original: FAILED (target: Original final crashed)", summary)
                    self.assertIn("Best: 90.0", summary)
                elif fail_best:
                    self.assertIn("Original: 80.0", summary)
                    self.assertIn("Best: FAILED (target: Best final crashed)", summary)


if __name__ == "__main__":
    unittest.main()

