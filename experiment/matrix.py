#!/usr/bin/env python3
"""Matrix orchestrator for Layer 1 experiments (9 tasks x 3 conditions x 3 repeats = 81 runs).

Responsibilities:
1. Generates fixed-seed random-shuffled schedule across (task, condition, run_index).
2. Executes run pipeline: Runner (Target) -> Evaluator -> Blind Gemini Judge -> Summarize.
3. Provides --dry-run (zero model calls, budget estimation) and --preflight (validates all fixtures without model calls).
4. Provides --execute for explicit user-authorized execution with workers <= 3 concurrency.
5. Provides safe --resume that skips fully completed runs without silently re-attempting failed runs or resuming sessions.
6. Streams live progress to progress.json and status.jsonl, and safely handles SIGINT/SIGTERM with process tree cleanup.
"""
from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent
TASKS = [f"T{i:02d}" for i in range(1, 10)]
CONDITIONS = ["P0", "P1", "P2"]
RUNS = [1, 2, 3]
TOTAL_RUNS = len(TASKS) * len(CONDITIONS) * len(RUNS)  # 81

# Active processes and run directories tracking for graceful cancellation
_ACTIVE_PROCS: set[subprocess.Popen] = set()
_ACTIVE_RUN_DIRS: set[Path] = set()
_OWNED_DESCENDANTS: set[int] = set()
_PROCS_LOCK = threading.Lock()


def register_proc(proc: subprocess.Popen, run_dir: Path | None = None) -> None:
    with _PROCS_LOCK:
        _ACTIVE_PROCS.add(proc)
        if run_dir:
            _ACTIVE_RUN_DIRS.add(run_dir)


def unregister_proc(proc: subprocess.Popen, run_dir: Path | None = None) -> None:
    with _PROCS_LOCK:
        _ACTIVE_PROCS.discard(proc)
        if run_dir:
            _ACTIVE_RUN_DIRS.discard(run_dir)


def get_all_descendant_pids(root_pids: set[int]) -> set[int]:
    """Return all descendant PIDs (children, grandchildren, etc.) of root_pids.
    Strictly non-heuristic; traverses parent-child process graph without process name matching.
    """
    if not root_pids:
        return set()
    try:
        out = subprocess.check_output(["/bin/ps", "-ax", "-o", "pid,ppid"], text=True)
    except Exception:
        return set()
    parent_to_children: dict[int, list[int]] = {}
    for line in out.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2:
            try:
                pid = int(parts[0])
                ppid = int(parts[1])
                parent_to_children.setdefault(ppid, []).append(pid)
            except ValueError:
                continue
    descendants: set[int] = set()
    queue = list(root_pids)
    while queue:
        curr = queue.pop(0)
        for ch in parent_to_children.get(curr, []):
            if ch not in descendants and ch not in root_pids:
                descendants.add(ch)
                queue.append(ch)
    return descendants


def kill_proc_tree(proc: subprocess.Popen, run_dir: Path | None = None) -> None:
    """Kill proc and all its owned descendants, strictly avoiding killing unrelated processes."""
    root_pid = proc.pid
    desc = get_all_descendant_pids({root_pid})
    with _PROCS_LOCK:
        desc.update(_OWNED_DESCENDANTS)
    if run_dir:
        for pid_name in ("target.pid", "judge_cli.pid", "active_target.pid"):
            pf = run_dir / pid_name
            if pf.is_file():
                try:
                    desc.add(int(pf.read_text(encoding="utf-8").strip()))
                except Exception:
                    pass
    # Kill descendants (leaves first) then root
    for pid in list(desc) + [root_pid]:
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            pass
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


def kill_active_procs() -> None:
    """Kill all tracked active processes and their owned descendants without affecting other system processes."""
    with _PROCS_LOCK:
        roots = list(_ACTIVE_PROCS)
        run_dirs = list(_ACTIVE_RUN_DIRS)
        root_pids = {p.pid for p in roots if p.poll() is None}
        desc = get_all_descendant_pids(root_pids)
        desc.update(_OWNED_DESCENDANTS)

        # Kill owned descendant processes and recorded PIDs
        for run_dir in list(_ACTIVE_RUN_DIRS):
            for pid_name in ("target.pid", "judge_cli.pid", "active_target.pid"):
                pid_file = run_dir / pid_name
                if pid_file.is_file():
                    try:
                        desc.add(int(pid_file.read_text(encoding="utf-8").strip()))
                    except Exception:
                        pass
                    pid_file.unlink(missing_ok=True)
        for pid in list(desc) + list(root_pids):
            try:
                os.killpg(pid, signal.SIGKILL)
            except Exception:
                pass
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
        for p in roots:
            try:
                p.kill()
            except Exception:
                pass
        _ACTIVE_PROCS.clear()
        _ACTIVE_RUN_DIRS.clear()
        _OWNED_DESCENDANTS.clear()


def generate_schedule(tasks: list[str] = TASKS,
                      conditions: list[str] = CONDITIONS,
                      runs: list[int] = RUNS,
                      seed: int = 42) -> list[dict]:
    """Generates a reproducible shuffled execution schedule."""
    items = [
        {"schedule_index": 0, "task": t, "condition": c, "run_index": r}
        for t in sorted(tasks)
        for c in sorted(conditions)
        for r in sorted(runs)
    ]
    rng = random.Random(seed)
    rng.shuffle(items)
    for idx, item in enumerate(items, 1):
        item["schedule_index"] = idx
    return items


def validate_schedule(schedule_data: any) -> list[dict]:
    """Validate schedule structure, indices, and completeness. Fail closed."""
    if not isinstance(schedule_data, list) or not schedule_data:
        raise ValueError(f"Schedule must be a non-empty list of dicts, got {type(schedule_data)}")
    seen_cells = set()
    for idx, item in enumerate(schedule_data, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Schedule item {idx} must be a dict, got {type(item)}")
        sched_idx = item.get("schedule_index")
        if not isinstance(sched_idx, int) or isinstance(sched_idx, bool) or sched_idx != idx:
            raise ValueError(f"Schedule item at position {idx} has invalid schedule_index {sched_idx!r} (expected {idx})")
        task = item.get("task")
        if task not in TASKS:
            raise ValueError(f"Schedule item {idx} has invalid task {task!r}")
        cond = item.get("condition")
        if cond not in CONDITIONS:
            raise ValueError(f"Schedule item {idx} has invalid condition {cond!r}")
        run_i = item.get("run_index")
        if not isinstance(run_i, int) or isinstance(run_i, bool) or run_i not in RUNS:
            raise ValueError(f"Schedule item {idx} has invalid run_index {run_i!r}")
        cell = (task, cond, run_i)
        if cell in seen_cells:
            raise ValueError(f"Duplicate cell in schedule: {cell}")
        seen_cells.add(cell)
    return schedule_data


def resolve_repository_summary(task_id: str, manifest_data: dict) -> Path:
    """Resolve repository summary path strictly according to manifest contract. Fail closed."""
    if "repository_summary_relpath" in manifest_data and manifest_data["repository_summary_relpath"] is not None:
        relpath = str(manifest_data["repository_summary_relpath"]).strip()
        if not relpath:
            raise FileNotFoundError(f"Empty repository_summary_relpath specified for task {task_id}")
        p = ROOT / "evaluator" / relpath
        if not p.is_file():
            raise FileNotFoundError(f"Explicit repository_summary_relpath not found for task {task_id}: {p}")
        return p

    if task_id == "T02":
        p = ROOT / "evaluator" / "repository_summary.md"
        if p.is_file():
            return p
    candidates = [
        ROOT / "evaluator" / "manifests" / f"repository_summary_{task_id}.md",
        ROOT / "evaluator" / "manifests" / f"repository_summary_{task_id.upper()}.md",
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError(f"Missing repository summary for task {task_id}")


class StatusRecorder:
    """Thread-safe, append-only status recorder with fsync on every event."""

    def __init__(self, batch_dir: Path, batch_id: str, total_runs: int, schedule: list[dict], resume: bool = False):
        self.batch_dir = batch_dir
        self.batch_id = batch_id
        self.total_runs = total_runs
        self.schedule = schedule
        self.progress_file = batch_dir / "progress.json"
        self.status_file = batch_dir / "status.jsonl"
        self.lock = threading.Lock()
        self.start_time = datetime.now(timezone.utc).isoformat()
        loaded = False
        if resume and self.progress_file.is_file():
            try:
                prev = json.loads(self.progress_file.read_text(encoding="utf-8"))
                if not isinstance(prev, dict):
                    raise ValueError("progress.json is not a valid JSON object")
                if prev.get("batch_id") != batch_id:
                    raise ValueError(f"Conflicting batch_id in progress.json: expected {batch_id!r}, found {prev.get('batch_id')!r}")
                self.stats = prev
                self.stats["status"] = "resuming"
                loaded = True
            except Exception as exc:
                if not isinstance(exc, ValueError):
                    raise RuntimeError(f"Corrupted progress.json in {batch_dir}: {exc}") from exc
                raise

        if not loaded:
            self.stats = {
                "batch_id": batch_id,
                "experiment_stage": "layer1/runs",
                "status": "prepared",
                "total_runs": total_runs,
                "completed_runs": 0,
                "failed_runs": 0,
                "skipped_runs": 0,
                "pending_runs": total_runs,
                "target_invocations": 0,
                "judge_invocations": 0,
                "start_time": self.start_time,
                "end_time": None,
                "schedule_seed": 42,
            }
        self._write_progress()

    def reconcile_schedule(self, batch_dir: Path, schedule: list[dict]) -> None:
        """Reconcile verified ground truth status and accumulated invocations from run directories."""
        completed = 0
        failed = 0
        target_invocations = 0
        judge_invocations = 0
        for spec in schedule:
            run_dir = batch_dir / spec["condition"] / spec["task"] / f"run{spec['run_index']}"
            qual = check_run_qualification(run_dir)
            if qual["status"] == "completed":
                completed += 1
            elif qual["status"] in ("already_failed", "judge_failed"):
                failed += 1
            meta_path = run_dir / "run_metadata.json"
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    target_invocations += int(meta.get("target_invocations", 0))
                except Exception:
                    pass
            judge_att = run_dir / "judge_attempt.json"
            if judge_att.is_file():
                try:
                    j_meta = json.loads(judge_att.read_text(encoding="utf-8"))
                    judge_invocations += int(j_meta.get("judge_invocations", 1))
                except Exception:
                    judge_invocations += 1
        with self.lock:
            self.stats["completed_runs"] = max(self.stats.get("completed_runs", 0), completed)
            self.stats["failed_runs"] = max(self.stats.get("failed_runs", 0), failed)
            self.stats["target_invocations"] = max(self.stats.get("target_invocations", 0), target_invocations)
            self.stats["judge_invocations"] = max(self.stats.get("judge_invocations", 0), judge_invocations)
            accounted = self.stats["completed_runs"] + self.stats["failed_runs"]
            self.stats["pending_runs"] = max(0, self.total_runs - accounted)
            self._write_progress()

    def record_event(self, event: str, spec: dict, data: dict | None = None) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "schedule_index": spec.get("schedule_index"),
            "task": spec.get("task"),
            "condition": spec.get("condition"),
            "run_index": spec.get("run_index"),
        }
        if data:
            record["data"] = data

        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self.lock:
            with self.status_file.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

    def update_progress(self, status: str | None = None, delta_completed: int = 0,
                        delta_failed: int = 0, delta_skipped: int = 0,
                        delta_target: int = 0, delta_judge: int = 0) -> None:
        with self.lock:
            if status:
                self.stats["status"] = status
            self.stats["completed_runs"] += delta_completed
            self.stats["failed_runs"] += delta_failed
            self.stats["skipped_runs"] += delta_skipped
            self.stats["target_invocations"] += delta_target
            self.stats["judge_invocations"] += delta_judge
            accounted = self.stats["completed_runs"] + self.stats["failed_runs"]
            self.stats["pending_runs"] = max(0, self.total_runs - accounted)
            if status in ("completed", "interrupted", "paused", "stopped_on_error", "aggregation_error", "incomplete_with_failures"):
                self.stats["end_time"] = datetime.now(timezone.utc).isoformat()
            self._write_progress()

    def _write_progress(self) -> None:
        tmp = self.progress_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.stats, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.progress_file)


def check_run_qualification(run_dir: Path) -> dict:
    """Rigorous check of run archival and progress qualification:
    - 'completed': fully qualified and complete
    - 'target_completed_needs_eval': target completed; needs evaluator
    - 'target_completed_needs_judge': target and eval completed; needs judge
    - 'target_completed_needs_summary': judge completed; needs summarize
    - 'already_failed': target previously attempted and failed / disqualified
    - 'judge_failed': judge previously attempted and failed
    - 'prepared_needs_execute': prepared in zero-model dry-run
    - 'preparing_interrupted': interrupted during preparation
    - 'unattempted': no attempt recorded
    """
    if not run_dir.is_dir():
        return {"status": "unattempted"}
    meta_path = run_dir / "run_metadata.json"
    if not meta_path.is_file():
        if any(run_dir.iterdir()):
            return {"status": "already_failed", "reason": "untracked_directory_exists"}
        return {"status": "unattempted"}

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "already_failed", "reason": "corrupt_metadata"}

    if meta.get("status") == "execution_error":
        return {"status": "already_failed", "error": meta.get("error", "Execution error")}

    # Existing attempts, running states, or interruptions must fail closed!
    if meta.get("target_invocations", 0) > 0 and meta.get("status") != "completed":
        return {"status": "already_failed", "reason": "interrupted_or_unresolved_target_attempt",
                "error": meta.get("error", "Target invocation already attempted")}

    if meta.get("status") in ("running", "interrupted"):
        return {"status": "already_failed", "reason": f"target_{meta.get('status')}",
                "error": meta.get("error", meta.get("status"))}

    if meta.get("status") == "preparing":
        return {"status": "already_failed", "reason": "interrupted_during_preparation",
                "error": meta.get("error", "Interrupted during preparation")}

    if meta.get("status") == "prepared" and meta.get("target_invocations", 0) == 0:
        return {"status": "prepared_needs_execute"}

    if meta.get("status") != "completed":
        return {"status": "already_failed", "reason": f"unrecognized_status_{meta.get('status')}"}

    final_resp = run_dir / "final_response.txt"
    if not final_resp.is_file() or not final_resp.read_text(encoding="utf-8").strip():
        return {"status": "already_failed", "reason": "empty_or_missing_final_response"}

    trace_file = run_dir / "tool_trace.jsonl"
    if not trace_file.is_file() or trace_file.stat().st_size == 0:
        return {"status": "already_failed", "reason": "missing_or_empty_tool_trace"}
    try:
        events = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not any(e.get("type") == "turn.completed" for e in events) or any(e.get("type") in ("error", "turn.failed") for e in events):
            return {"status": "already_failed", "reason": "invalid_tool_trace"}
    except Exception:
        return {"status": "already_failed", "reason": "corrupt_tool_trace"}

    # Target is successfully verified and completed
    diff_patch = run_dir / "diff.patch"
    if not diff_patch.is_file():
        return {"status": "already_failed", "reason": "missing_diff_patch"}

    eval_res_file = (run_dir / "evaluation_result_v2.json" if (run_dir / "evaluation_result_v2.json").is_file()
                     else run_dir / "evaluation_result.json")
    if not eval_res_file.is_file():
        return {"status": "target_completed_needs_eval"}
    try:
        eval_data = json.loads(eval_res_file.read_text(encoding="utf-8"))
        if eval_data.get("summary", {}).get("has_evaluation_error"):
            return {"status": "already_failed", "reason": "evaluation_infra_error"}
    except Exception:
        return {"status": "already_failed", "reason": "corrupt_evaluation_result"}

    # Check Judge
    judge_att_file = run_dir / "judge_attempt.json"
    judge_raw = run_dir / "judge_raw.jsonl"
    judge_verdict = run_dir / "judge_verdict.json"

    # If any judge attempt or artifact exists, verify strictly or fail closed (never re-judge)
    if judge_att_file.is_file() or judge_raw.is_file() or judge_verdict.is_file():
        if judge_att_file.is_file():
            try:
                j_att = json.loads(judge_att_file.read_text(encoding="utf-8"))
            except Exception:
                return {"status": "judge_failed", "reason": "corrupt_judge_attempt"}
            if not isinstance(j_att, dict):
                return {"status": "judge_failed", "reason": "invalid_judge_attempt"}
            if j_att.get("status") != "completed":
                return {"status": "judge_failed", "error": j_att.get("error", "judge_incomplete")}

        # Judge was attempted: stream and verdict MUST exist and be valid
        if not judge_raw.is_file() or not judge_raw.read_text(encoding="utf-8").strip():
            return {"status": "judge_failed", "reason": "judge_stream_missing_or_empty"}
        if not judge_verdict.is_file():
            return {"status": "judge_failed", "reason": "judge_verdict_missing"}
        try:
            verdict_data = json.loads(judge_verdict.read_text(encoding="utf-8"))
            if not isinstance(verdict_data, dict):
                return {"status": "judge_failed", "reason": "invalid_judge_verdict"}
        except Exception:
            return {"status": "judge_failed", "reason": "corrupt_judge_verdict"}
        # Validate judge stream JSON lines
        try:
            lines = [json.loads(l) for l in judge_raw.read_text(encoding="utf-8").splitlines() if l.strip()]
            if not lines:
                return {"status": "judge_failed", "reason": "empty_judge_stream"}
        except Exception:
            return {"status": "judge_failed", "reason": "corrupt_judge_stream"}
    else:
        # No judge attempt was ever made
        return {"status": "target_completed_needs_judge"}

    # Check Summary / Metrics & Qualification
    metrics_file = run_dir / "metrics.json"
    if not metrics_file.is_file():
        return {"status": "target_completed_needs_summary"}
    try:
        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "target_completed_needs_summary"}

    # Must be non-empty dict with full evidence qualification
    if not isinstance(metrics, dict) or not metrics:
        return {"status": "target_completed_needs_summary"}

    # Audit raw evidence through summarize.check_run_eligibility
    from experiment.summarize import check_run_eligibility
    try:
        elig = check_run_eligibility(run_dir)
        if not elig.get("is_eligible"):
            return {
                "status": "already_failed",
                "reason": "disqualified_evidence",
                "error": elig.get("exclusion_reason", "Disqualified evidence"),
            }
    except Exception as exc:
        return {
            "status": "already_failed",
            "reason": "eligibility_audit_error",
            "error": str(exc),
        }

    if not metrics.get("eligible_for_behavioral_aggregation", False):
        return {"status": "already_failed", "reason": "disqualified_evidence",
                "error": metrics.get("exclusion_reason", "Disqualified evidence")}

    # Validate essential p3 qualification keys
    for k in ("task", "condition", "stage", "target_model", "reasoning_effort", "judge_model", "HC"):
        if k not in metrics or metrics[k] is None:
            return {"status": "target_completed_needs_summary"}
        if k == "judge_model" and metrics[k] == "missing":
            return {"status": "already_failed", "reason": "judge_model_missing"}

    return {"status": "completed"}


def is_run_completed(run_dir: Path) -> bool:
    """Return True if run_dir has all required artifacts and completed cleanly."""
    return check_run_qualification(run_dir)["status"] == "completed"


def is_run_attempted(run_dir: Path) -> tuple[bool, str | None]:
    """Return (True, status) if run was attempted, else (False, None)."""
    meta_path = run_dir / "run_metadata.json"
    if not meta_path.is_file():
        return False, None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        status = meta.get("status")
        return bool(status), status
    except Exception:
        return True, "corrupt_metadata"


def execute_subprocess(cmd: list[str], cwd: Path | None = None,
                       env: dict[str, str] | None = None,
                       timeout: int = 300,
                       run_dir: Path | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    register_proc(proc, run_dir)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        kill_proc_tree(proc, run_dir)
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)
    finally:
        unregister_proc(proc, run_dir)


def run_single_pipeline(spec: dict, batch_dir: Path, execute: bool, timeout: int,
                        recorder: StatusRecorder, resume: bool = False,
                        judge_semaphore: threading.Semaphore | None = None,
                        dependency: Path | None = None) -> dict:
    """Executes the full pipeline for one cell: Target Runner -> Evaluator -> Blind Gemini Judge -> Summarize."""
    task_id = spec["task"]
    condition = spec["condition"]
    run_index = spec["run_index"]
    run_dir = batch_dir / condition / task_id / f"run{run_index}"

    from experiment.runner import resolve_manifest
    manifest_path, manifest_data = resolve_manifest(task_id)
    if not manifest_path or not manifest_data:
        recorder.record_event("manifest_missing", spec, {"task": task_id})
        recorder.update_progress(delta_failed=1)
        return {"status": "manifest_missing", "is_infra_error": True}

    # Verify repository summary existence early
    try:
        summary_file = resolve_repository_summary(task_id, manifest_data)
    except Exception as exc:
        recorder.record_event("summary_file_missing", spec, {"error": str(exc)})
        recorder.update_progress(delta_failed=1)
        return {"status": "summary_missing", "is_infra_error": True}

    target_needed = True
    eval_needed = True
    judge_needed = True
    summary_needed = True

    if resume:
        qual = check_run_qualification(run_dir)
        q_status = qual["status"]
        if q_status == "completed":
            recorder.record_event("run_skipped_already_completed", spec, {"run_dir": str(run_dir)})
            recorder.update_progress(delta_skipped=1)
            return {"status": "skipped_completed", "run_dir": str(run_dir)}
        elif q_status == "already_failed":
            # Never silently re-invoke failed model calls
            recorder.record_event("run_skipped_already_failed_no_silent_retry", spec,
                                  {"run_dir": str(run_dir), "reason": qual.get("reason"), "error": qual.get("error")})
            recorder.update_progress(delta_skipped=1)
            return {"status": "skipped_failed", "run_dir": str(run_dir), "is_infra_error": False}
        elif q_status == "judge_failed":
            recorder.record_event("judge_attempt_failed_needs_authorization", spec,
                                  {"run_dir": str(run_dir), "error": qual.get("error")})
            recorder.update_progress(delta_skipped=1)
            return {"status": "judge_failed", "run_dir": str(run_dir), "is_infra_error": False}
        elif q_status == "prepared_needs_execute":
            if not execute:
                recorder.record_event("run_skipped_already_prepared", spec, {"run_dir": str(run_dir)})
                recorder.update_progress(delta_completed=1)
                return {"status": "skipped_prepared", "run_dir": str(run_dir)}
            # If execute=True, proceed with fresh target execution
        elif q_status == "target_completed_needs_eval":
            target_needed = False
        elif q_status == "target_completed_needs_judge":
            target_needed = False
            eval_needed = False
        elif q_status == "target_completed_needs_summary":
            target_needed = False
            eval_needed = False
            judge_needed = False

    # 1. Target Runner Stage
    if target_needed:
        recorder.record_event("target_start", spec, {"run_dir": str(run_dir)})
        runner_cmd = [
            sys.executable, "-m", "experiment.runner",
            "--task-id", task_id,
            "--condition", condition,
            "--run-index", str(run_index),
            "--batch-id", recorder.batch_id,
            "--schedule-index", str(spec.get("schedule_index", 0)),
            "--experiment-stage", "layer1/runs",
            "--run-dir", str(run_dir),
            "--timeout", str(timeout),
        ]
        if dependency:
            runner_cmd.extend(["--dependency", str(dependency)])
        if execute:
            runner_cmd.append("--execute")
        else:
            runner_cmd.append("--dry-run")

        try:
            proc = execute_subprocess(runner_cmd, timeout=timeout + 30, run_dir=run_dir)
            if proc.returncode != 0:
                # Read actual target attempts if recorded in metadata
                meta_path = run_dir / "run_metadata.json"
                target_invoked = 0
                if meta_path.is_file():
                    try:
                        target_invoked = json.loads(meta_path.read_text(encoding="utf-8")).get("target_invocations", 0)
                    except Exception:
                        pass
                recorder.record_event("target_failed", spec, {"exit_code": proc.returncode, "stderr": proc.stderr})
                recorder.update_progress(delta_failed=1, delta_target=target_invoked)
                return {"status": "target_failed", "exit_code": proc.returncode, "stderr": proc.stderr, "is_infra_error": True}
        except Exception as exc:
            recorder.record_event("target_error", spec, {"error": str(exc)})
            recorder.update_progress(delta_failed=1)
            return {"status": "target_error", "error": str(exc), "is_infra_error": True}

        if not execute:
            recorder.record_event("target_prepared", spec, {"run_dir": str(run_dir)})
            recorder.update_progress(delta_completed=1)
            return {"status": "prepared", "run_dir": str(run_dir)}

        recorder.record_event("target_completed", spec, {"run_dir": str(run_dir)})
        recorder.update_progress(delta_target=1)

    meta_path = run_dir / "run_metadata.json"
    if not meta_path.is_file():
        recorder.record_event("metadata_missing", spec)
        recorder.update_progress(delta_failed=1)
        return {"status": "metadata_missing", "is_infra_error": True}
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    workspace = Path(meta["workspace"])

    # 2. Evaluator Stage
    eval_res_file = (run_dir / "evaluation_result_v2.json" if (run_dir / "evaluation_result_v2.json").is_file()
                     else run_dir / "evaluation_result.json")
    if eval_needed:
        recorder.record_event("evaluator_start", spec)
        evaluator_cmd = [
            sys.executable, "-m", "experiment.evaluator",
            "--repo", str(workspace),
            "--artifact", str(run_dir),
            "--manifest", str(manifest_path),
        ]
        fixture_repo = ROOT / "fixtures/core" / task_id / "repo"
        if fixture_repo.is_dir():
            evaluator_cmd.extend(["--baseline", str(fixture_repo)])

        try:
            eval_proc = execute_subprocess(evaluator_cmd, timeout=60, run_dir=run_dir)
            # Evaluator returncode: exit 0 or 1 is normal (1 is assertion failure), exit 2 is infrastructure error
            if eval_proc.returncode not in (0, 1):
                recorder.record_event("evaluator_error_exit", spec, {"exit_code": eval_proc.returncode, "stderr": eval_proc.stderr})
                recorder.update_progress(delta_failed=1)
                return {"status": "evaluator_error", "exit_code": eval_proc.returncode, "is_infra_error": True}

            eval_res_file = (run_dir / "evaluation_result_v2.json" if (run_dir / "evaluation_result_v2.json").is_file()
                             else run_dir / "evaluation_result.json")
            if not eval_res_file.is_file():
                recorder.record_event("evaluator_missing_result", spec)
                recorder.update_progress(delta_failed=1)
                return {"status": "evaluator_missing_result", "is_infra_error": True}

            eval_data = json.loads(eval_res_file.read_text(encoding="utf-8"))
            if eval_data.get("summary", {}).get("has_evaluation_error"):
                recorder.record_event("evaluator_infrastructure_error", spec, {"errors": eval_data.get("summary", {}).get("evaluation_errors")})
                recorder.update_progress(delta_failed=1)
                return {"status": "evaluator_infrastructure_error", "is_infra_error": True}

            recorder.record_event("evaluator_completed", spec, {"exit_code": eval_proc.returncode})
        except Exception as exc:
            recorder.record_event("evaluator_error", spec, {"error": str(exc)})
            recorder.update_progress(delta_failed=1)
            return {"status": "evaluator_error", "error": str(exc), "is_infra_error": True}

    # 3. Blind Gemini Judge Stage
    if judge_needed:
        recorder.record_event("judge_start", spec)
        task_file = ROOT / "fixtures/core" / task_id / "task.md"
        if not task_file.is_file():
            task_file = ROOT / "fixtures/core" / task_id / "task.txt"

        judge_cmd = [
            sys.executable, "-m", "experiment.judge",
            "--run-dir", str(run_dir),
            "--task", str(task_file),
            "--summary", str(summary_file),
            "--test-results", str(eval_res_file),
            "--workspace", str(workspace),
            "--execute",
            "--timeout", str(timeout),
        ]

        judge_acquired = False
        if judge_semaphore:
            judge_semaphore.acquire()
            judge_acquired = True

        try:
            judge_proc = execute_subprocess(judge_cmd, timeout=timeout + 30, run_dir=run_dir)
            recorder.update_progress(delta_judge=1)
            if judge_proc.returncode != 0:
                recorder.record_event("judge_failed", spec, {"exit_code": judge_proc.returncode, "stderr": judge_proc.stderr})
                recorder.update_progress(delta_failed=1)
                return {"status": "judge_failed", "exit_code": judge_proc.returncode, "is_infra_error": True}
            recorder.record_event("judge_completed", spec)
        except Exception as exc:
            recorder.record_event("judge_error", spec, {"error": str(exc)})
            recorder.update_progress(delta_failed=1)
            return {"status": "judge_error", "error": str(exc), "is_infra_error": True}
        finally:
            if judge_acquired and judge_semaphore:
                judge_semaphore.release()

    # 4. Summarize Stage
    if summary_needed:
        summarize_py = ROOT / "summarize.py"
        if summarize_py.is_file():
            recorder.record_event("summarize_start", spec)
            env = dict(os.environ, PYTHONPATH=str(ROOT.parent))
            sum_cmd = [
                sys.executable, str(summarize_py),
                "--run-dir", str(run_dir),
            ]
            try:
                sum_proc = execute_subprocess(sum_cmd, env=env, timeout=30, run_dir=run_dir)
                if sum_proc.returncode != 0:
                    recorder.record_event("summarize_error", spec, {"exit_code": sum_proc.returncode, "stderr": sum_proc.stderr})
                    recorder.update_progress(delta_failed=1)
                    return {"status": "summarize_error", "exit_code": sum_proc.returncode, "is_infra_error": True}
                recorder.record_event("summarize_completed", spec, {"exit_code": sum_proc.returncode})
            except Exception as exc:
                recorder.record_event("summarize_error", spec, {"error": str(exc)})
                recorder.update_progress(delta_failed=1)
                return {"status": "summarize_error", "error": str(exc), "is_infra_error": True}

            # Verify metrics & evidence qualification immediately after summarize!
            metrics_file = run_dir / "metrics.json"
            if not metrics_file.is_file():
                recorder.record_event("summarize_missing_metrics", spec)
                recorder.update_progress(delta_failed=1)
                return {"status": "summarize_error", "reason": "missing_metrics", "is_infra_error": True}
            try:
                metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            except Exception as exc:
                recorder.record_event("summarize_corrupt_metrics", spec, {"error": str(exc)})
                recorder.update_progress(delta_failed=1)
                return {"status": "summarize_error", "reason": "corrupt_metrics", "is_infra_error": True}

            if not isinstance(metrics, dict) or not metrics:
                recorder.record_event("summarize_empty_metrics", spec)
                recorder.update_progress(delta_failed=1)
                return {"status": "summarize_error", "reason": "empty_metrics", "is_infra_error": True}

            if not metrics.get("eligible_for_behavioral_aggregation", False):
                reason = metrics.get("exclusion_reason", "Disqualified evidence")
                recorder.record_event("run_disqualified_evidence", spec, {"exclusion_reason": reason})
                recorder.update_progress(delta_failed=1)
                return {"status": "disqualified_evidence", "error": reason, "is_infra_error": True}

            for k in ("task", "condition", "stage", "target_model", "reasoning_effort", "judge_model", "HC"):
                if k not in metrics or metrics[k] is None:
                    recorder.record_event("summarize_incomplete_metrics", spec, {"missing_key": k})
                    recorder.update_progress(delta_failed=1)
                    return {"status": "summarize_error", "reason": f"missing_key_{k}", "is_infra_error": True}
            if metrics.get("judge_model") == "missing":
                recorder.record_event("summarize_missing_judge_model", spec)
                recorder.update_progress(delta_failed=1)
                return {"status": "summarize_error", "reason": "judge_model_missing", "is_infra_error": True}

    recorder.record_event("run_completed", spec)
    recorder.update_progress(delta_completed=1)
    return {"status": "completed", "run_dir": str(run_dir), "is_infra_error": False}


def run_preflight(tasks: list[str], dependency: Path) -> int:
    """Validates all fixtures, manifests, summaries, runtime launchers, baseline tests,
    and isolation probes with zero model calls.
    Fails closed: if any task is missing or fails, returns exit code 1.
    """
    print("=" * 70)
    print("RUNNING ZERO-MODEL PREFLIGHT CHECK FOR FIXTURES")
    print("=" * 70)

    from experiment.runner import prepare_workspace, prepare_runtime, restricted_probe, resolve_manifest

    failed = 0
    passed = 0
    for task_id in sorted(tasks):
        manifest_path, manifest_data = resolve_manifest(task_id)
        if not manifest_path or not manifest_data:
            print(f"[{task_id}] FAIL - manifest missing or corrupt for task {task_id}")
            failed += 1
            continue

        fixture_repo = ROOT / "fixtures/core" / task_id / "repo"
        if not fixture_repo.is_dir():
            print(f"[{task_id}] FAIL - fixture repo not found: {fixture_repo}")
            failed += 1
            continue

        try:
            summary_file = resolve_repository_summary(task_id, manifest_data)
            if not summary_file.is_file():
                print(f"[{task_id}] FAIL - repository summary not found: {summary_file}")
                failed += 1
                continue
        except Exception as exc:
            print(f"[{task_id}] FAIL - repository summary error: {exc}")
            failed += 1
            continue

        temp_artifacts = Path(tempfile.mkdtemp(prefix=f"preflight-{task_id}-artifacts-"))
        repo = None
        try:
            repo, commit = prepare_workspace(fixture_repo)
            runtime_dep = prepare_runtime(repo, dependency.resolve())
            probe_result = restricted_probe(repo, temp_artifacts, runtime_dep,
                                            manifest=manifest_data, task_id=task_id)
            print(f"[{task_id}] PASS - commit={commit[:8]}, probe_exit={probe_result['exit_code']}, "
                  f"baseline_exit={probe_result.get('baseline_target_test', {}).get('exit_code')}")
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"[{task_id}] FAIL - {exc}")
        finally:
            shutil.rmtree(temp_artifacts, ignore_errors=True)
            if repo and repo.parent.is_dir():
                shutil.rmtree(repo.parent, ignore_errors=True)

    print("=" * 70)
    if failed == 0 and passed == len(tasks):
        print(f"ALL {passed} PREFLIGHT CHECKS PASSED (Zero Model Invocations)")
        return 0
    else:
        print(f"PREFLIGHT FAILED: {failed} fixture(s) failed / missing, {passed} passed")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", default=None,
                        help="Unique batch ID (defaults to timestamp or existing progress.json batch_id)")
    parser.add_argument("--batch-dir", type=Path, help="Override root directory for this batch")
    parser.add_argument("--tasks", nargs="+", default=TASKS, help="Task IDs to include")
    parser.add_argument("--conditions", nargs="+", default=CONDITIONS, help="Conditions to include (P0, P1, P2)")
    parser.add_argument("--runs", nargs="+", type=int, default=RUNS, help="Run repeat indices (1..3)")
    parser.add_argument("--seed", type=int, default=42, help="Fixed random seed for schedule shuffle")
    parser.add_argument("--workers", type=int, default=3, help="Max parallel target workers (<= 3)")
    parser.add_argument("--judge-concurrency", type=int, default=1, help="Max concurrent judge invocations")
    parser.add_argument("--timeout", type=int, default=300, help="Per-run timeout in seconds")
    parser.add_argument("--dependency", type=Path, default=ROOT / ".venv", help="Path to base .venv")
    parser.add_argument("--preflight", action="store_true", help="Run zero-model preflight on all fixtures")
    parser.add_argument("--dry-run", "--prepare-only", action="store_true", help="Prepare schedule and dirs with zero model calls")
    parser.add_argument("--execute", action="store_true", help="Authorize execution of model calls")
    parser.add_argument("--resume", action="store_true", help="Skip already completed runs without re-invoking failed ones")
    args = parser.parse_args()

    if args.preflight:
        return run_preflight(args.tasks, args.dependency)

    if args.execute and args.dry_run:
        parser.error("--execute and --dry-run are mutually exclusive")

    # Enforce workers constraint
    workers = min(max(1, args.workers), 3)

    explicit_batch_id = args.batch_id is not None
    if args.batch_dir:
        batch_dir = args.batch_dir.resolve()
    else:
        temp_bid = args.batch_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        batch_dir = (ROOT / "runs/layer1" / temp_bid).resolve()
    batch_dir.mkdir(parents=True, exist_ok=True)

    progress_file = batch_dir / "progress.json"
    batch_id: str
    frozen_id: str | None = None
    if progress_file.is_file():
        try:
            prev = json.loads(progress_file.read_text(encoding="utf-8"))
            if not isinstance(prev, dict):
                raise ValueError("progress.json content is not a dict")
            frozen_id = prev.get("batch_id")
            if not frozen_id or not isinstance(frozen_id, str):
                raise ValueError("Missing or invalid batch_id in progress.json")
        except Exception as exc:
            raise RuntimeError(f"Corrupted progress.json in {batch_dir}: {exc}") from exc
    elif args.resume or not explicit_batch_id:
        for meta_p in sorted(batch_dir.rglob("run_metadata.json")):
            try:
                meta_data = json.loads(meta_p.read_text(encoding="utf-8"))
                bid = meta_data.get("batch_id")
                if bid and isinstance(bid, str) and bid.strip():
                    frozen_id = bid.strip()
                    break
            except Exception:
                pass

    if frozen_id:
        if explicit_batch_id and args.batch_id != frozen_id:
            raise ValueError(f"Conflicting --batch-id '{args.batch_id}' with existing batch_id '{frozen_id}' in {batch_dir}")
        batch_id = frozen_id
    else:
        batch_id = args.batch_id if explicit_batch_id else datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    schedule_file = batch_dir / "schedule.json"
    if schedule_file.is_file():
        try:
            raw_sched = json.loads(schedule_file.read_text(encoding="utf-8"))
            schedule = validate_schedule(raw_sched)
        except Exception as exc:
            raise RuntimeError(f"Corrupted or invalid schedule in {schedule_file}: {exc}") from exc
    else:
        schedule = generate_schedule(tasks=args.tasks, conditions=args.conditions,
                                     runs=args.runs, seed=args.seed)
        validate_schedule(schedule)
        schedule_file.write_text(json.dumps(schedule, indent=2), encoding="utf-8")

    recorder = StatusRecorder(batch_dir, batch_id, len(schedule), schedule, resume=args.resume)
    if args.resume:
        recorder.reconcile_schedule(batch_dir, schedule)

    # Signal handlers for clean cancellation
    stop_event = threading.Event()

    def handle_signal(sig, frame):
        print(f"\nCaught signal {sig}, terminating all active processes and preserving evidence...")
        stop_event.set()
        kill_active_procs()
        recorder.update_progress(status="interrupted")
        sys.exit(130)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if not args.execute:
        # Dry-run mode: zero model calls
        codex_budget = len(schedule)
        judge_budget = len(schedule)
        total_model_budget = codex_budget + judge_budget

        print("=" * 70)
        print("MATRIX DRY-RUN SCHEDULE PREPARED (Zero Model Invocations)")
        print("=" * 70)
        print(f"Batch ID:         {batch_id}")
        print(f"Batch Directory:  {batch_dir}")
        print(f"Tasks:            {', '.join(sorted(set(s['task'] for s in schedule)))} ({len(set(s['task'] for s in schedule))})")
        print(f"Conditions:       {', '.join(sorted(set(s['condition'] for s in schedule)))} ({len(set(s['condition'] for s in schedule))})")
        print(f"Total Runs:       {len(schedule)}")
        print(f"Schedule Seed:    {args.seed}")
        print(f"Max Workers:      {workers}")
        print("-" * 70)
        print(f"Codex Invocations: {codex_budget}")
        print(f"Judge Invocations: up to {judge_budget}")
        print(f"Total Max Calls:   {total_model_budget}")
        print("=" * 70)
        print("Status written to progress.json and schedule.json.")
        print("To authorize formal execution, pass --execute.")
        return 0

    # Execute mode: first ensure preflight on requested tasks passes!
    preflight_code = run_preflight(args.tasks, args.dependency)
    if preflight_code != 0:
        print("Preflight checks failed! Execution halted before calling any models.")
        recorder.update_progress(status="preflight_failed")
        return 1

    recorder.update_progress(status="running")
    judge_sem = threading.Semaphore(max(1, args.judge_concurrency))

    print(f"Starting execution of {len(schedule)} runs with workers={workers} (batch={batch_id})...")

    schedule_iter = iter(schedule)
    active_futures: dict[Future, dict] = {}
    infra_error_occurred = threading.Event()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        while not stop_event.is_set():
            # If infra error occurred, stop dispatching new tasks!
            if not infra_error_occurred.is_set():
                while len(active_futures) < workers:
                    try:
                        spec = next(schedule_iter)
                    except StopIteration:
                        break
                    fut = executor.submit(
                        run_single_pipeline, spec, batch_dir, args.execute,
                        args.timeout, recorder, args.resume, judge_sem, args.dependency
                    )
                    active_futures[fut] = spec

            if not active_futures:
                break

            # Wait for at least one in-flight task to finish
            done, _ = wait(active_futures.keys(), return_when=FIRST_COMPLETED)
            for fut in done:
                spec = active_futures.pop(fut)
                try:
                    res = fut.result()
                    if res.get("is_infra_error"):
                        print(f"Infrastructure error in task {spec.get('task')}_{spec.get('condition')}_run{spec.get('run_index')}: {res}")
                        infra_error_occurred.set()
                except Exception as exc:
                    print(f"Worker exception in task {spec.get('task')}_{spec.get('condition')}_run{spec.get('run_index')}: {exc}")
                    infra_error_occurred.set()
                    recorder.record_event("worker_exception", spec, {"error": str(exc)})
                    recorder.update_progress(delta_failed=1)

    if infra_error_occurred.is_set():
        recorder.update_progress(status="paused")
        print(f"Batch paused due to infrastructure error. See {batch_dir / 'progress.json'}.")
        return 1

    # End of batch: call summarize aggregation
    summarize_py = ROOT / "summarize.py"
    if not summarize_py.is_file():
        recorder.record_event("batch_aggregation_failed", {}, {"error": f"summarize.py not found at {summarize_py}"})
        recorder.update_progress(status="aggregation_error")
        print(f"Batch aggregation failed: summarize.py not found at {summarize_py}")
        return 1

    out_dir = batch_dir / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT.parent))
    agg_cmd = [
        sys.executable, str(summarize_py),
        "--batch-dir", str(batch_dir),
        "--batch-id", recorder.batch_id,
        "--output-dir", str(out_dir),
    ]
    agg_proc = execute_subprocess(agg_cmd, env=env, timeout=60)
    if agg_proc.returncode != 0:
        recorder.record_event("batch_aggregation_failed", {}, {"exit_code": agg_proc.returncode, "stderr": agg_proc.stderr})
        recorder.update_progress(status="aggregation_error")
        print(f"Batch aggregation failed. See stderr: {agg_proc.stderr}")
        return 1

    summary_file = out_dir / "summary.json"
    if not summary_file.is_file():
        recorder.record_event("batch_aggregation_summary_missing", {}, {"error": f"summary.json not found at {summary_file}"})
        recorder.update_progress(status="aggregation_error")
        print(f"Batch aggregation failed: summary.json not found at {summary_file}")
        return 1

    try:
        summary_data = json.loads(summary_file.read_text(encoding="utf-8"))
    except Exception as exc:
        recorder.record_event("batch_aggregation_summary_corrupt", {}, {"error": str(exc)})
        recorder.update_progress(status="aggregation_error")
        print(f"Batch aggregation failed: corrupted summary.json: {exc}")
        return 1

    if not isinstance(summary_data, dict):
        recorder.record_event("batch_aggregation_summary_invalid", {}, {
            "error": f"summary.json must be a JSON object, got {type(summary_data).__name__}"
        })
        recorder.update_progress(status="aggregation_error")
        print(f"Batch aggregation failed: summary.json is not a dict: {type(summary_data).__name__}")
        return 1

    # Final Reconciliation against scheduled runs
    total_scheduled = len(schedule)
    verified_completed = 0
    failures = []
    seen_cells = set()
    for spec in schedule:
        cell_key = (spec["task"], spec["condition"], spec["run_index"])
        if cell_key in seen_cells:
            failures.append({"cell": list(cell_key), "reason": "duplicate_cell_in_schedule"})
            continue
        seen_cells.add(cell_key)

        r_dir = batch_dir / spec["condition"] / spec["task"] / f"run{spec['run_index']}"
        qual = check_run_qualification(r_dir)
        if qual["status"] == "completed":
            verified_completed += 1
        else:
            failures.append({
                "cell": list(cell_key),
                "status": qual["status"],
                "reason": qual.get("reason") or qual.get("error") or qual["status"],
            })

    # Validate against actual summary.json
    summary_failed = False
    summary_failure_reasons = []
    agg_batch_id = summary_data.get("batch_id")
    if agg_batch_id != recorder.batch_id:
        summary_failed = True
        summary_failure_reasons.append(f"batch_id mismatch ({agg_batch_id} != {recorder.batch_id})")

    eligible_count = summary_data.get("eligible_runs_count", 0)
    if eligible_count != total_scheduled:
        summary_failed = True
        summary_failure_reasons.append(f"eligible_runs_count mismatch ({eligible_count} != {total_scheduled})")

    excluded_count = summary_data.get("excluded_runs_count", 0)
    if excluded_count > 0:
        summary_failed = True
        summary_failure_reasons.append(f"excluded_runs_count is {excluded_count} > 0")

    matrix_rec = summary_data.get("matrix_reconciliation", {})
    if not isinstance(matrix_rec, dict):
        matrix_rec = {}
    dup_count = matrix_rec.get("duplicate_count", 0)
    if dup_count > 0:
        summary_failed = True
        summary_failure_reasons.append(f"duplicate_count is {dup_count} > 0")

    if total_scheduled == TOTAL_RUNS:
        if summary_data.get("readiness_for_formal_analysis") != "READY":
            summary_failed = True
            summary_failure_reasons.append(f"readiness_for_formal_analysis is {summary_data.get('readiness_for_formal_analysis')} (expected 'READY')")
        if summary_data.get("batch_completion_status") != "COMPLETE":
            summary_failed = True
            summary_failure_reasons.append(f"batch_completion_status is {summary_data.get('batch_completion_status')} (expected 'COMPLETE')")

    if failures or verified_completed != total_scheduled or summary_failed:
        recorder.record_event("batch_reconciliation_failed", {}, {
            "verified_completed": verified_completed,
            "total_scheduled": total_scheduled,
            "failures": failures,
            "summary_failures": summary_failure_reasons,
        })
        recorder.update_progress(status="incomplete_with_failures")
        print(f"Batch {recorder.batch_id} reconciliation failed: {verified_completed}/{total_scheduled} verified completed. Failures: {len(failures)}, Summary failures: {summary_failure_reasons}. See {batch_dir / 'progress.json'}.")
        return 1

    recorder.update_progress(status="completed")
    print(f"Batch {recorder.batch_id} completed successfully ({verified_completed}/{total_scheduled} runs verified). See {batch_dir / 'progress.json'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
