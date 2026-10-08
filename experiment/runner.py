#!/usr/bin/env python3
"""One fresh, filesystem-restricted Codex engineering run. No hillclimb."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import shlex
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent
MODEL = "gpt-6-astra"
EFFORT = "medium"
PROFILE = "astra_pilot"
DISABLED = ("shell_snapshot", "plugins", "hooks", "apps", "multi_agent",
            "browser_use", "browser_use_external", "computer_use", "memories")


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_AUTHOR_NAME="Fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
               GIT_COMMITTER_NAME="Fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid",
               GIT_AUTHOR_DATE="2020-01-01T00:00:00Z", GIT_COMMITTER_DATE="2020-01-01T00:00:00Z")
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, env=env, check=check)


def prepare_workspace(fixture: Path) -> tuple[Path, str]:
    base = Path(tempfile.mkdtemp(prefix="astra-work-", dir="/private/tmp")).resolve()
    repo = base / "repo"
    shutil.copytree(fixture, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    git(repo, "init", "-q", "--initial-branch=main")
    (repo / ".git" / "info" / "exclude").write_text("__pycache__/\n.pytest_cache/\n*.pyc\n")
    git(repo, "add", ".")
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Initial fixture")
    return repo, git(repo, "rev-parse", "HEAD").stdout.strip()


def prepare_runtime(repo: Path, source_venv: Path) -> Path:
    """Read-only pytest runtime using a system interpreter, not a venv symlink.

    CPython's venv realpath discovery needs ancestor metadata denied by Seatbelt.
    Pure-Python dependencies plus small launchers avoid widening host read access.
    """
    runtime = repo.parent / "runtime"
    (runtime / "bin").mkdir(parents=True)
    packages = list(source_venv.glob("lib/python*/site-packages"))
    if len(packages) != 1:
        raise RuntimeError("Expected one pinned pytest environment")
    shutil.copytree(packages[0], runtime / "site-packages", symlinks=True)
    python = (source_venv / "bin" / "python").resolve(strict=True)
    for name, extra in (("python", ""), ("python3", ""), ("pytest", "-m pytest ")):
        file = runtime / "bin" / name
        file.write_text("#!/bin/sh\nexport PYTHONPATH=" + shlex.quote(str(runtime / "site-packages")) +
                        "\nexec " + shlex.quote(str(python)) + " -B " + extra + '"$@"\n')
        file.chmod(0o755)
    # /usr/bin/git is an xcrun shim on macOS; its cache otherwise lands in
    # TMPDIR and looks like agent-created permanent machinery in the diff.
    git_path = shutil.which("git")
    if git_path == "/usr/bin/git" and shutil.which("xcrun"):
        git_path = subprocess.check_output(["xcrun", "--find", "git"], text=True).strip()
    if not git_path:
        raise RuntimeError("Git executable not available")
    launcher = runtime / "bin" / "git"
    launcher.write_text("#!/bin/sh\nexec " + shlex.quote(git_path) + ' "$@"\n')
    launcher.chmod(0o755)
    return runtime


def permission_config(repo: Path, artifacts: Path, dependency: Path) -> list[str]:
    # Codex applies this kernel-enforced profile to model tool commands. Parent
    # host reads needed for CLI authentication are not exposed as shell access.
    fs = {"/": "read", "/Users": "deny", "/private/tmp": "deny",
          "/private/var/folders": "deny", str(ROOT.parent): "deny",
          str(artifacts): "deny", str(dependency.resolve()): "read",
          str(repo.resolve()): "write"}
    table = "{" + ",".join(json.dumps(k) + "=" + json.dumps(v) for k, v in fs.items()) + "}"
    return ["-c", f'default_permissions="{PROFILE}"', "-c", f"permissions.{PROFILE}.filesystem={table}"]


def restricted_probe(repo: Path, artifacts: Path, dependency: Path) -> dict:
    sentinel = repo.parent / "private-sentinel.txt"
    sentinel.write_text("outside-workspace")
    hidden = ROOT / "evaluator" / "hidden_tests" / "test_parser_hidden.py"
    script = """import json, pathlib, sys
repo=pathlib.Path(sys.argv[1]); denied={}
for name in sys.argv[2:]:
    try: pathlib.Path(name).read_bytes(); denied[name]=False
    except PermissionError: denied[name]=True
p=repo/'probe-write.tmp'; p.write_text('ok'); p.unlink()
import pytest
print(json.dumps({'write_ok':True,'pytest':pytest.__version__,'denied':denied}))
sys.exit(0 if all(denied.values()) else 1)
"""
    command = ["codex", "sandbox", "-P", PROFILE, *permission_config(repo, artifacts, dependency),
               "-C", str(repo), "--", str(dependency / "bin" / "python"), "-B", "-c", script,
               str(repo), str(sentinel), str(hidden), str(ROOT / "README.md"),
               str(Path.home() / ".codex" / "AGENTS.md")]
    env = runtime_environment(repo, dependency)
    proc = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env)
    sentinel.unlink(missing_ok=True)
    result = {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    if proc.returncode != 0:
        raise RuntimeError("Filesystem isolation/dependency probe failed: " + json.dumps(result))
    evidence = json.loads(proc.stdout)
    if not evidence.get("write_ok") or not all(evidence.get("denied", {}).values()):
        raise RuntimeError("Filesystem isolation probe did not prove restricted access")
    # Importing pytest alone is insufficient: actual collection must work.
    # This pristine bug fixture must fail its assertion, not fail to collect.
    prefix = ["codex", "sandbox", "-P", PROFILE, *permission_config(repo, artifacts, dependency),
              "-C", str(repo), "--"]
    baseline = subprocess.run(prefix + [str(dependency / "bin" / "pytest"), "-q",
                              "-p", "no:cacheprovider",
                              "tests/test_parser.py::test_parse_header_with_none_value"],
                              capture_output=True, text=True, timeout=30, env=env)
    result["baseline_target_test"] = {"exit_code": baseline.returncode,
                                       "stdout": baseline.stdout, "stderr": baseline.stderr}
    if baseline.returncode != 1 or "AttributeError" not in baseline.stdout or "1 failed" not in baseline.stdout:
        raise RuntimeError("Targeted validation preflight did not reach the known baseline assertion")
    git_probe = subprocess.run(prefix + [str(dependency / "bin" / "git"), "status", "--short"],
                               capture_output=True, text=True, timeout=30, env=env)
    if git_probe.returncode or git_probe.stdout.strip():
        raise RuntimeError("Git preflight produced an error or polluted the pristine workspace")
    result["git_status_clean"] = True
    return result


def codex_command(repo: Path, artifacts: Path, dependency: Path) -> list[str]:
    command = ["codex", "--no-daemon", "-a", "never", *permission_config(repo, artifacts, dependency),
               "-c", "project_doc_max_bytes=0", "-c", f'model_reasoning_effort="{EFFORT}"',
               "-c", 'web_search="disabled"', "--enable", "skip_host_skill_discovery"]
    for feature in DISABLED:
        command += ["--disable", feature]
    return command + ["exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
                      "--json", "--color", "never", "-m", MODEL, "-C", str(repo),
                      "-o", str(artifacts / "final_response.txt"), "-"]


def collect_diff(repo: Path, initial_commit: str) -> tuple[str, list[str]]:
    patch = git(repo, "diff", "--binary", initial_commit, "--").stdout
    changed = set(git(repo, "diff", "--name-only", initial_commit, "--").stdout.splitlines())
    new_files = git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")
    for file in filter(None, new_files):
        proc = git(repo, "diff", "--no-index", "--binary", "--", "/dev/null", file, check=False)
        if proc.returncode not in (0, 1):
            raise RuntimeError(f"Cannot capture added-file diff: {file}")
        patch += proc.stdout
        changed.add(file)
    return patch, sorted(changed)


def transcript_from_events(raw: str) -> str:
    lines = []
    for index, line in enumerate(raw.splitlines(), 1):
        event = json.loads(line)
        lines.append(f"EVENT {index} {event.get('type', 'unknown')}\n{json.dumps(event, ensure_ascii=False, indent=2)}")
    return "\n\n".join(lines) + "\n"


def runtime_environment(repo: Path, dependency: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("HERDR_", "PI_", "PYTHONPATH", "PYTHONSTARTUP", "PYTEST_"))}
    env.update(PATH=str(dependency / "bin") + os.pathsep + env.get("PATH", ""),
               PWD=str(repo), TMPDIR=str(repo), PYTHONDONTWRITEBYTECODE="1",
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_CONFIG_NOSYSTEM="1",
               PYTEST_ADDOPTS="--confcutdir=" + str(repo / "tests") + " --import-mode=importlib")
    return env


def execute_once(command: list[str], prompt: str, repo: Path, artifacts: Path,
                 dependency: Path, timeout: int) -> tuple[int, bool, float]:
    env = runtime_environment(repo, dependency)
    # Exact runtime settings are in metadata; do not change task-level instructions.
    start = time.monotonic()
    with (artifacts / "tool_trace.jsonl").open("w") as out, (artifacts / "codex_stderr.txt").open("w") as err:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                cwd=repo, env=env, text=True, start_new_session=True)
        timed_out = False
        try:
            proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
    return proc.returncode, timed_out, round(time.monotonic() - start, 3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "fixtures/core/T02/repo")
    parser.add_argument("--task", type=Path, default=ROOT / "fixtures/core/T02/task.md")
    parser.add_argument("--prompt", type=Path, default=ROOT / "prompts/P0.txt")
    parser.add_argument("--dependency", type=Path, default=ROOT / ".venv")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--execute", action="store_true", help="Authorize exactly one target invocation")
    parser.add_argument("--dry-run", "--prepare-only", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if args.execute and args.dry_run:
        parser.error("--execute and --dry-run are mutually exclusive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    artifacts = (args.run_dir or ROOT / "runs/layer1/P0/T02" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")).resolve()
    artifacts.mkdir(parents=True, exist_ok=False)
    prompt = args.prompt.read_text().strip() + "\n\n" + args.task.read_text().strip() + "\n"
    (artifacts / "prompt.txt").write_text(prompt)
    metadata = {"status": "preparing", "condition": "P0", "task": "T02", "target_model": MODEL,
                "reasoning_effort": EFFORT, "target_invocations": 0,
                "codex_version": subprocess.check_output(["codex", "--version"], text=True).strip(),
                "limitations": ["Single pilot is not evidence of a stable model preference.",
                                 "Host runtime binaries remain readable; task, evaluator and history are isolated."]}
    repo = None
    try:
        repo, commit = prepare_workspace(args.fixture)
        metadata.update(workspace=str(repo), initial_commit=commit)
        dependency = prepare_runtime(repo, args.dependency.resolve())
        metadata["runtime_dependency"] = str(dependency)
        metadata["validation_environment"] = {"PYTEST_ADDOPTS": runtime_environment(repo, dependency)["PYTEST_ADDOPTS"],
                                               "git_launcher": str(dependency / "bin" / "git")}
        metadata["isolation_probe"] = restricted_probe(repo, artifacts, dependency)
        command = codex_command(repo, artifacts, dependency)
        metadata["command"] = command
        if not args.execute:
            metadata["status"] = "prepared"
            print(json.dumps({"status": "prepared", "run_dir": str(artifacts), "workspace": str(repo), "target_invocations": 0}))
            return 0
        metadata["target_invocations"] = 1
        metadata["status"] = "running"
        (artifacts / "run_metadata.json").write_text(json.dumps(metadata, indent=2))
        code, timed_out, seconds = execute_once(command, prompt, repo, artifacts, dependency, args.timeout)
        metadata.update(exit_code=code, timed_out=timed_out, duration_seconds=seconds)
        final = artifacts / "final_response.txt"
        raw = (artifacts / "tool_trace.jsonl").read_text()
        if timed_out or code != 0 or not final.exists() or not final.read_text().strip():
            raise RuntimeError(f"Target execution error: exit={code}, timed_out={timed_out}, final_response={final.exists()}")
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if not any(event.get("type") == "turn.completed" for event in events):
            raise RuntimeError("Target trace lacks a completed turn")
        if any(event.get("type") in ("error", "turn.failed") for event in events):
            raise RuntimeError("Target trace contains an execution failure")
        (artifacts / "transcript.txt").write_text(transcript_from_events(raw))
        metadata["status"] = "completed"
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        metadata.update(status="execution_error", error=str(exc))
        print(f"execution_error: {exc}")
    finally:
        if repo is not None:
            patch, files = collect_diff(repo, metadata["initial_commit"])
            (artifacts / "diff.patch").write_text(patch)
            (artifacts / "changed_files.txt").write_text("\n".join(files) + ("\n" if files else ""))
            raw_path = artifacts / "tool_trace.jsonl"
            if raw_path.exists() and not (artifacts / "transcript.txt").exists():
                (artifacts / "transcript.txt").write_text(raw_path.read_text())
        (artifacts / "run_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    if metadata["status"] == "completed":
        print(json.dumps({"status": "completed", "run_dir": str(artifacts), "workspace": str(repo), "target_invocations": 1}))
    return 0 if metadata["status"] in ("prepared", "completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
