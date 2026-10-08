#!/usr/bin/env python3
"""Unit tests for experiment/runner.py.

Verifies:
1. Deterministic workspace initial commit from fixture.
2. Read-only pytest runtime creation avoiding venv realpath resolution issues.
3. Accurate diff capturing both tracked changes and untracked new files.
4. Fixed model, reasoning effort, ephemeral, no-daemon, restricted permissions profile without dangerous bypasses.
5. Structured transcript formatting from JSONL event streams.
6. Dry-run and execution lifecycle ensuring zero model calls without explicit --execute.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from experiment.runner import (
    DISABLED,
    EFFORT,
    MODEL,
    PROFILE,
    codex_command,
    collect_diff,
    main,
    permission_config,
    prepare_runtime,
    prepare_workspace,
    transcript_from_events,
)


class TestRunnerWorkspace(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test-runner-workspace-"))
        self.fixture_dir = self.temp_dir / "fixture"
        self.fixture_dir.mkdir(parents=True)
        (self.fixture_dir / "README.md").write_text("# Test Fixture\n", encoding="utf-8")
        src_dir = self.fixture_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("def run():\n    return 42\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_prepare_workspace_commit_determinism(self):
        """Two workspaces prepared from the identical fixture produce the exact same commit SHA."""
        repo1, commit1 = prepare_workspace(self.fixture_dir)
        repo2, commit2 = prepare_workspace(self.fixture_dir)
        try:
            self.assertTrue(repo1.is_dir())
            self.assertTrue(repo2.is_dir())
            self.assertEqual(commit1, commit2)
            self.assertTrue((repo1 / ".git").is_dir())
            self.assertTrue((repo1 / ".git" / "info" / "exclude").exists())
            exclude_content = (repo1 / ".git" / "info" / "exclude").read_text(encoding="utf-8")
            self.assertIn("__pycache__/", exclude_content)
            self.assertIn(".pytest_cache/", exclude_content)
        finally:
            shutil.rmtree(repo1.parent, ignore_errors=True)
            shutil.rmtree(repo2.parent, ignore_errors=True)


class TestRunnerRuntime(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test-runner-runtime-"))
        self.repo = self.temp_dir / "work" / "repo"
        self.repo.mkdir(parents=True)
        self.mock_venv = self.temp_dir / "mock_venv"
        sp = self.mock_venv / "lib" / "python3.12" / "site-packages"
        sp.mkdir(parents=True)
        (sp / "pytest_mock.py").write_text("# mock pytest package\n", encoding="utf-8")
        bin_dir = self.mock_venv / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (bin_dir / "python").chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_prepare_runtime_creates_launchers_and_copies_site_packages(self):
        """Pure-Python dependencies are copied and direct system-python shell launchers created."""
        runtime = prepare_runtime(self.repo, self.mock_venv)
        self.assertEqual(runtime, self.repo.parent / "runtime")
        self.assertTrue((runtime / "bin").is_dir())
        self.assertTrue((runtime / "site-packages").is_dir())
        self.assertTrue((runtime / "site-packages" / "pytest_mock.py").exists())

        for name in ("python", "python3", "pytest"):
            launcher = runtime / "bin" / name
            self.assertTrue(launcher.is_file())
            self.assertTrue(os.access(str(launcher), os.X_OK))
            content = launcher.read_text(encoding="utf-8")
            self.assertIn("export PYTHONPATH=", content)
            self.assertIn(str(runtime / "site-packages"), content)
            if name == "pytest":
                self.assertIn("-m pytest", content)

    def test_prepare_runtime_fails_on_invalid_venv(self):
        empty_venv = self.temp_dir / "empty_venv"
        empty_venv.mkdir()
        with self.assertRaises(RuntimeError):
            prepare_runtime(self.repo, empty_venv)


class TestRunnerDiffCollection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test-runner-diff-"))
        self.fixture_dir = self.temp_dir / "fixture"
        self.fixture_dir.mkdir(parents=True)
        (self.fixture_dir / "existing.py").write_text("x = 1\n", encoding="utf-8")
        self.repo, self.initial_commit = prepare_workspace(self.fixture_dir)

    def tearDown(self):
        shutil.rmtree(self.repo.parent, ignore_errors=True)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_collect_diff_empty_initially(self):
        patch_text, changed_files = collect_diff(self.repo, self.initial_commit)
        self.assertEqual(patch_text, "")
        self.assertEqual(changed_files, [])

    def test_collect_diff_tracked_modifications(self):
        (self.repo / "existing.py").write_text("x = 2\n", encoding="utf-8")
        patch_text, changed_files = collect_diff(self.repo, self.initial_commit)
        self.assertIn("existing.py", changed_files)
        self.assertIn("-x = 1", patch_text)
        self.assertIn("+x = 2", patch_text)

    def test_collect_diff_untracked_new_files(self):
        (self.repo / "new_module.py").write_text("def brand_new(): pass\n", encoding="utf-8")
        patch_text, changed_files = collect_diff(self.repo, self.initial_commit)
        self.assertIn("new_module.py", changed_files)
        self.assertIn("brand_new", patch_text)
        self.assertIn("new_module.py", patch_text)

    def test_collect_diff_combined_tracked_and_untracked(self):
        (self.repo / "existing.py").write_text("x = 99\n", encoding="utf-8")
        (self.repo / "untracked.txt").write_text("untracked content\n", encoding="utf-8")
        patch_text, changed_files = collect_diff(self.repo, self.initial_commit)
        self.assertEqual(changed_files, ["existing.py", "untracked.txt"])
        self.assertIn("-x = 1", patch_text)
        self.assertIn("+x = 99", patch_text)
        self.assertIn("untracked content", patch_text)


class TestRunnerCommandAndSecurity(unittest.TestCase):
    def setUp(self):
        self.repo = Path("/private/tmp/mock-work/repo")
        self.artifacts = Path("/private/tmp/mock-work/artifacts")
        self.dependency = Path("/private/tmp/mock-work/runtime")

    def test_model_and_effort_fixed(self):
        self.assertEqual(MODEL, "gpt-6-astra")
        self.assertEqual(EFFORT, "medium")
        self.assertEqual(PROFILE, "astra_pilot")

    def test_command_flags_and_safety_invariants(self):
        cmd = codex_command(self.repo, self.artifacts, self.dependency)

        # Basic invocations
        self.assertEqual(cmd[0], "codex")
        self.assertIn("--no-daemon", cmd)
        self.assertIn("-a", cmd)
        a_idx = cmd.index("-a")
        self.assertEqual(cmd[a_idx + 1], "never")

        # Fixed target model and reasoning effort
        self.assertIn("-m", cmd)
        m_idx = cmd.index("-m")
        self.assertEqual(cmd[m_idx + 1], "gpt-6-astra")
        self.assertIn(f'model_reasoning_effort="{EFFORT}"', cmd)

        # Ephemeral and config hygiene
        self.assertIn("exec", cmd)
        self.assertIn("--ephemeral", cmd)
        self.assertIn("--ignore-user-config", cmd)
        self.assertIn("--ignore-rules", cmd)
        self.assertIn("--json", cmd)
        self.assertIn("-c", cmd)
        self.assertIn("project_doc_max_bytes=0", cmd)
        self.assertIn('web_search="disabled"', cmd)
        self.assertIn("--enable", cmd)
        self.assertIn("skip_host_skill_discovery", cmd)

        # Disabled unwanted features
        for feature in DISABLED:
            self.assertIn("--disable", cmd)
            self.assertIn(feature, cmd)

        # Output artifact destination
        self.assertIn("-o", cmd)
        o_idx = cmd.index("-o")
        self.assertEqual(cmd[o_idx + 1], str(self.artifacts / "final_response.txt"))

        # Target working directory
        self.assertIn("-C", cmd)
        c_idx = cmd.index("-C")
        self.assertEqual(cmd[c_idx + 1], str(self.repo))

        # Absolute prohibition of dangerous bypasses
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", cmd)
        self.assertNotIn("--dangerously-bypass-hook-trust", cmd)
        self.assertNotIn("danger-full-access", " ".join(cmd))
        self.assertNotIn("-s", cmd)  # avoid overriding default_permissions

    def test_permission_config_filesystem_table(self):
        perms = permission_config(self.repo, self.artifacts, self.dependency)
        self.assertIn("-c", perms)
        self.assertIn(f'default_permissions="{PROFILE}"', perms)

        # Find the filesystem table argument
        fs_arg = next(arg for arg in perms if f"permissions.{PROFILE}.filesystem=" in arg)
        table_json_str = fs_arg.split("=", 1)[1]

        # In TOML syntax: {"/"="read", ...}
        self.assertIn('"/"="read"', table_json_str)
        self.assertIn('"/Users"="deny"', table_json_str)
        self.assertIn('"/private/tmp"="deny"', table_json_str)
        self.assertIn('"/private/var/folders"="deny"', table_json_str)
        self.assertIn(f'"{self.artifacts}"="deny"', table_json_str)
        self.assertIn(f'"{self.repo.resolve()}"="write"', table_json_str)
        self.assertIn(f'"{self.dependency.resolve()}"="read"', table_json_str)


class TestRunnerTranscript(unittest.TestCase):
    def test_transcript_from_events(self):
        raw_events = (
            '{"type": "turn.start", "turn_id": "t1"}\n'
            '{"type": "message", "role": "assistant", "content": [{"text": "Hello"}]}\n'
            '{"type": "turn.completed"}\n'
        )
        formatted = transcript_from_events(raw_events)
        self.assertIn("EVENT 1 turn.start", formatted)
        self.assertIn("EVENT 2 message", formatted)
        self.assertIn("EVENT 3 turn.completed", formatted)
        self.assertIn('"role": "assistant"', formatted)


class TestRunnerMainLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test-runner-main-"))
        self.fixture_dir = self.temp_dir / "fixture"
        self.fixture_dir.mkdir(parents=True)
        (self.fixture_dir / "file.txt").write_text("hello\n", encoding="utf-8")

        self.task_file = self.temp_dir / "task.md"
        self.task_file.write_text("Do something specific.\n", encoding="utf-8")

        self.prompt_file = self.temp_dir / "P0.txt"
        self.prompt_file.write_text("Implement the requested change.\n", encoding="utf-8")

        self.run_dir = self.temp_dir / "runs" / "r1"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("experiment.runner.subprocess.check_output", return_value="codex-cli 0.160.0\n")
    @patch("experiment.runner.restricted_probe", return_value={"exit_code": 0, "stdout": "ok", "stderr": ""})
    @patch("experiment.runner.execute_once")
    def test_main_dry_run_zero_model_calls(self, mock_execute, mock_probe, mock_version):
        """--dry-run prepares artifacts, prompt, and metadata with zero model invocations."""
        with patch("sys.argv", [
            "runner.py",
            "--dry-run",
            "--fixture", str(self.fixture_dir),
            "--task", str(self.task_file),
            "--prompt", str(self.prompt_file),
            "--run-dir", str(self.run_dir),
        ]):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        mock_execute.assert_not_called()

        # Check prompt.txt was written outside tested cwd
        prompt_path = self.run_dir / "prompt.txt"
        self.assertTrue(prompt_path.exists())
        self.assertIn("Implement the requested change.", prompt_path.read_text(encoding="utf-8"))
        self.assertIn("Do something specific.", prompt_path.read_text(encoding="utf-8"))

        # Check metadata
        meta_path = self.run_dir / "run_metadata.json"
        self.assertTrue(meta_path.exists())
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "prepared")
        self.assertEqual(metadata["target_invocations"], 0)
        self.assertEqual(metadata["target_model"], "gpt-6-astra")
        self.assertEqual(metadata["reasoning_effort"], "medium")
        self.assertEqual(metadata["codex_version"], "codex-cli 0.160.0")
        self.assertIn("runtime_dependency", metadata)
        self.assertTrue(Path(metadata["runtime_dependency"]).is_dir())

    @patch("experiment.runner.subprocess.check_output", return_value="codex-cli 0.160.0\n")
    @patch("experiment.runner.restricted_probe", return_value={"exit_code": 0, "stdout": "ok", "stderr": ""})
    @patch("experiment.runner.execute_once")
    def test_main_execute_once_lifecycle(self, mock_execute, mock_probe, mock_version):
        """--execute authorizes exactly one model invocation and records artifacts."""
        def fake_execute(command, prompt, repo, artifacts, dependency, timeout):
            (artifacts / "final_response.txt").write_text("I have fixed it.\n", encoding="utf-8")
            events = [
                json.dumps({"type": "turn.start"}),
                json.dumps({"type": "turn.completed"}),
            ]
            (artifacts / "tool_trace.jsonl").write_text("\n".join(events) + "\n", encoding="utf-8")
            return 0, False, 1.25

        mock_execute.side_effect = fake_execute

        with patch("sys.argv", [
            "runner.py",
            "--execute",
            "--fixture", str(self.fixture_dir),
            "--task", str(self.task_file),
            "--prompt", str(self.prompt_file),
            "--run-dir", str(self.run_dir),
        ]):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        mock_execute.assert_called_once()

        meta_path = self.run_dir / "run_metadata.json"
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "completed")
        self.assertEqual(metadata["target_invocations"], 1)
        self.assertEqual(metadata["exit_code"], 0)
        self.assertFalse(metadata["timed_out"])

        # Check artifacts saved outside tested cwd
        self.assertTrue((self.run_dir / "final_response.txt").exists())
        self.assertTrue((self.run_dir / "transcript.txt").exists())
        self.assertTrue((self.run_dir / "tool_trace.jsonl").exists())
        self.assertTrue((self.run_dir / "diff.patch").exists())
        self.assertTrue((self.run_dir / "changed_files.txt").exists())

    @patch("experiment.runner.subprocess.check_output", return_value="codex-cli 0.160.0\n")
    @patch("experiment.runner.restricted_probe", return_value={"exit_code": 0, "stdout": "ok", "stderr": ""})
    @patch("experiment.runner.execute_once", return_value=(1, False, 0.5))
    def test_main_execution_error_recorded(self, mock_execute, mock_probe, mock_version):
        """CLI failures or missing outputs are categorized as execution_error, not behavioral failure."""
        with patch("sys.argv", [
            "runner.py",
            "--execute",
            "--fixture", str(self.fixture_dir),
            "--task", str(self.task_file),
            "--prompt", str(self.prompt_file),
            "--run-dir", str(self.run_dir),
        ]):
            exit_code = main()

        self.assertEqual(exit_code, 1)
        meta_path = self.run_dir / "run_metadata.json"
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "execution_error")
        self.assertIn("error", metadata)

    def test_main_mutually_exclusive_flags(self):
        with patch("sys.argv", ["runner.py", "--execute", "--dry-run"]):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
