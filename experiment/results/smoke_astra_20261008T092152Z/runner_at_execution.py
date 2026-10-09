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
import sys
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
    if not fixture.is_dir():
        raise FileNotFoundError(f"Fixture directory not found: {fixture}")
    base = Path(tempfile.mkdtemp(prefix="astra-work-", dir="/private/tmp")).resolve()
    repo = base / "repo"
    shutil.copytree(fixture, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    git(repo, "init", "-q", "--initial-branch=main")
    (repo / ".git" / "info" / "exclude").write_text("__pycache__/\n.pytest_cache/\n*.pyc\npytest-of-*/\n")
    git(repo, "add", ".")
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Initial fixture")
    return repo, git(repo, "rev-parse", "HEAD").stdout.strip()


def prepare_runtime(repo: Path, source_venv: Path) -> Path:
    """Read-only pytest runtime using a system interpreter, not a venv symlink.

    CPython's venv realpath discovery needs ancestor metadata denied by Seatbelt.
    Pure-Python dependencies plus small launchers avoid widening host read access.
    """
    runtime = repo.parent / "runtime"
    (runtime / "bin").mkdir(parents=True, exist_ok=True)
    packages = list(source_venv.glob("lib/python*/site-packages"))
    if len(packages) != 1:
        raise RuntimeError("Expected one pinned pytest environment")
    if not (runtime / "site-packages").exists():
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


def resolve_manifest(task_id: str, manifest_path: Path | None = None) -> tuple[Path | None, dict]:
    if manifest_path:
        p = Path(manifest_path).resolve()
        if p.is_file():
            try:
                return p, json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValueError(f"Corrupt manifest file {p}: {exc}")
        raise FileNotFoundError(f"Specified manifest not found: {p}")
    for cand in (
        ROOT / "evaluator" / "manifests" / f"{task_id}_manifest.json",
        ROOT / "evaluator" / "manifests" / f"{task_id}.json",
        ROOT / "evaluator" / "manifests" / f"{task_id.upper()}_manifest.json",
        ROOT / "evaluator" / "manifests" / f"{task_id.upper()}.json",
    ):
        if cand.is_file():
            try:
                return cand, json.loads(cand.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValueError(f"Corrupt manifest file {cand}: {exc}")
    return None, {}


def restricted_probe(repo: Path, artifacts: Path, dependency: Path,
                     manifest: dict | None = None, task_id: str = "T02") -> dict:
    sentinel = repo.parent / "private-sentinel.txt"
    sentinel.write_text("outside-workspace")

    # Resolve hidden test path from manifest
    vdefs = (manifest or {}).get("verification_definitions", {})
    hidden_rel = vdefs.get("hidden_test_suite_relpath")
    if hidden_rel and (ROOT / "evaluator" / hidden_rel).exists():
        hidden = ROOT / "evaluator" / hidden_rel
    elif (ROOT / "evaluator" / "hidden_tests" / f"test_{task_id.lower()}_hidden.py").exists():
        hidden = ROOT / "evaluator" / "hidden_tests" / f"test_{task_id.lower()}_hidden.py"
    elif (ROOT / "evaluator" / "hidden_tests" / f"test_{task_id.upper()}_hidden.py").exists():
        hidden = ROOT / "evaluator" / "hidden_tests" / f"test_{task_id.upper()}_hidden.py"
    elif (ROOT / "evaluator" / "hidden_tests" / task_id / f"test_hidden_{task_id.lower()}.py").exists():
        hidden = ROOT / "evaluator" / "hidden_tests" / task_id / f"test_hidden_{task_id.lower()}.py"
    elif (ROOT / "evaluator" / "hidden_tests" / "test_parser_hidden.py").exists():
        hidden = ROOT / "evaluator" / "hidden_tests" / "test_parser_hidden.py"
    else:
        hidden = ROOT / "evaluator" / "hidden_tests"

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

    # Baseline target test preflight: read expected original exit (0 or 1) from manifest
    target_test = vdefs.get("target_test") or (manifest or {}).get("target_test") or "tests/test_parser.py::test_parse_header_with_none_value"
    expected_failing = vdefs.get("expected_initial_failing_visible", [])
    expected_passing = vdefs.get("expected_initial_passing_visible", [])

    preflight_def = vdefs.get("preflight", {})
    if "baseline_target_exit_code" in preflight_def:
        expected_exit = int(preflight_def["baseline_target_exit_code"])
    elif "expected_initial_target_exit" in vdefs:
        expected_exit = int(vdefs["expected_initial_target_exit"])
    elif target_test in expected_failing:
        expected_exit = 1
    elif target_test in expected_passing:
        expected_exit = 0
    else:
        expected_exit = 1 if expected_failing else (0 if expected_passing else 1)

    prefix = ["codex", "sandbox", "-P", PROFILE, *permission_config(repo, artifacts, dependency),
              "-C", str(repo), "--"]
    baseline = subprocess.run(prefix + [str(dependency / "bin" / "pytest"), "-q",
                              "-p", "no:cacheprovider", target_test],
                              capture_output=True, text=True, timeout=30, env=env)
    result["baseline_target_test"] = {"exit_code": baseline.returncode,
                                       "stdout": baseline.stdout, "stderr": baseline.stderr,
                                       "expected_exit": expected_exit}

    # Verify no collection errors or skips occurred
    has_collection_error = (
        "ERROR collecting" in baseline.stdout or
        "CollectionError" in baseline.stdout or
        ("errors" in baseline.stdout.lower() and "error:" in baseline.stdout.lower()) or
        "no tests ran" in baseline.stdout or
        "no tests collected" in baseline.stdout.lower() or
        "collected 0 items" in baseline.stdout or
        "0 items collected" in baseline.stdout.lower()
    )
    if has_collection_error:
        raise RuntimeError(f"Targeted validation preflight failed collection for {target_test}: {baseline.stdout} {baseline.stderr}")

    if baseline.returncode != expected_exit:
        raise RuntimeError(f"Targeted validation preflight exit {baseline.returncode} != expected {expected_exit} for {target_test}")

    if expected_exit == 1 and not ("failed" in baseline.stdout or "1 failed" in baseline.stdout or baseline.returncode == 1):
        raise RuntimeError("Expected targeted test failure did not occur")
    if expected_exit == 0 and not ("passed" in baseline.stdout or "1 passed" in baseline.stdout or baseline.returncode == 0):
        raise RuntimeError("Expected targeted test pass did not occur")

    for pdir in repo.glob("pytest-of-*"):
        shutil.rmtree(pdir, ignore_errors=True)

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
    start = time.monotonic()
    pid_file = artifacts / "target.pid"
    with (artifacts / "tool_trace.jsonl").open("w") as out, (artifacts / "codex_stderr.txt").open("w") as err:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                cwd=repo, env=env, text=True, start_new_session=True)
        pid_file.write_text(str(proc.pid), encoding="utf-8")
        timed_out = False

        def kill_proc():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        old_sigint = signal.getsignal(signal.SIGINT)
        old_sigterm = signal.getsignal(signal.SIGTERM)

        def forward_signal(sig, frame):
            kill_proc()
            sys.exit(128 + sig)

        signal.signal(signal.SIGINT, forward_signal)
        signal.signal(signal.SIGTERM, forward_signal)
        try:
            proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_proc()
            proc.communicate()
        finally:
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)
            pid_file.unlink(missing_ok=True)
    return proc.returncode, timed_out, round(time.monotonic() - start, 3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", default="T02", help="Task ID (T01...T09)")
    parser.add_argument("--condition", default="P0", choices=["P0", "P1", "P2"], help="Prompt condition")
    parser.add_argument("--run-index", type=int, default=1, help="Run repeat index (1...3)")
    parser.add_argument("--batch-id", default=None, help="Batch identifier")
    parser.add_argument("--schedule-index", type=int, default=None, help="Index in execution schedule")
    parser.add_argument("--experiment-stage", default="layer1/runs", help="Formal experiment stage")
    parser.add_argument("--manifest", type=Path, help="Explicit path to manifest json")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--prompt", type=Path)
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

    manifest_path, manifest_data = resolve_manifest(args.task_id, args.manifest)
    if not manifest_path or not manifest_data:
        raise FileNotFoundError(f"Manifest not found or invalid for task {args.task_id}")

    if args.fixture:
        fixture_path = args.fixture.resolve()
        if not fixture_path.is_dir():
            raise FileNotFoundError(f"Fixture repo not found: {fixture_path}")
    else:
        candidate_fixture = ROOT / "fixtures/core" / args.task_id / "repo"
        if not candidate_fixture.is_dir():
            raise FileNotFoundError(f"Fixture repo not found for task {args.task_id}: {candidate_fixture}")
        fixture_path = candidate_fixture.resolve()

    if args.task:
        task_path = args.task.resolve()
        if not task_path.is_file():
            raise FileNotFoundError(f"Task file not found: {task_path}")
    else:
        candidates = [
            ROOT / "fixtures/core" / args.task_id / "task.md",
            ROOT / "fixtures/core" / args.task_id / "task.txt",
        ]
        task_path = next((c.resolve() for c in candidates if c.is_file()), None)
        if not task_path:
            raise FileNotFoundError(f"Task instruction file not found for task {args.task_id}")

    if args.prompt:
        prompt_path = args.prompt.resolve()
    else:
        prompt_path = (ROOT / "prompts" / f"{args.condition}.txt").resolve()
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt file not found for condition {args.condition}: {prompt_path}")

    if args.run_dir:
        artifacts = args.run_dir.resolve()
    else:
        artifacts = (ROOT / "runs/layer1" / args.condition / args.task_id / f"run{args.run_index}" /
                     datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")).resolve()

    if artifacts.is_dir():
        meta_file = artifacts / "run_metadata.json"
        if meta_file.is_file():
            try:
                existing_meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                raise RuntimeError(f"Run directory already exists with unreadable metadata: {artifacts}")
            if existing_meta.get("target_invocations", 0) > 0 or existing_meta.get("status") != "prepared":
                raise RuntimeError(
                    f"Run directory already contains an attempted, completed, or interrupted run "
                    f"(status={existing_meta.get('status')}, target_invocations={existing_meta.get('target_invocations')}): {artifacts}"
                )
            # Clean safe zero-model prepared files for fresh execution
            for item in artifacts.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
        elif any(artifacts.iterdir()):
            raise RuntimeError(f"Run directory already exists and contains untracked files: {artifacts}")
    else:
        artifacts.mkdir(parents=True, exist_ok=True)

    prompt = prompt_path.read_text().strip() + "\n\n" + task_path.read_text().strip() + "\n"
    (artifacts / "prompt.txt").write_text(prompt)
    metadata = {
        "experiment_stage": args.experiment_stage,
        "batch_id": args.batch_id,
        "schedule_index": args.schedule_index,
        "status": "preparing",
        "condition": args.condition,
        "task": args.task_id,
        "run_index": args.run_index,
        "target_model": MODEL,
        "reasoning_effort": EFFORT,
        "target_invocations": 0,
        "codex_version": subprocess.check_output(["codex", "--version"], text=True).strip(),
        "manifest": str(manifest_path) if manifest_path else None,
        "execution_parameters": {
            "timeout": args.timeout,
            "task_id": args.task_id,
            "condition": args.condition,
            "run_index": args.run_index,
            "batch_id": args.batch_id,
            "schedule_index": args.schedule_index,
            "experiment_stage": args.experiment_stage,
        },
        "limitations": [
            "Host runtime binaries remain readable; task, evaluator and history are isolated."
        ],
    }
    repo = None
    try:
        repo, commit = prepare_workspace(fixture_path)
        metadata.update(workspace=str(repo), initial_commit=commit)
        dependency = prepare_runtime(repo, args.dependency.resolve())
        metadata["runtime_dependency"] = str(dependency)
        metadata["validation_environment"] = {
            "PYTEST_ADDOPTS": runtime_environment(repo, dependency)["PYTEST_ADDOPTS"],
            "git_launcher": str(dependency / "bin" / "git"),
        }
        metadata["isolation_probe"] = restricted_probe(repo, artifacts, dependency, manifest=manifest_data, task_id=args.task_id)
        command = codex_command(repo, artifacts, dependency)
        metadata["command"] = command
        if not args.execute:
            metadata["status"] = "prepared"
            (artifacts / "run_metadata.json").write_text(json.dumps(metadata, indent=2))
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
