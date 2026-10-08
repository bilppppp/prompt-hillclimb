#!/usr/bin/env python3
"""Join objective results and the blind verdict, without calling any model."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re

from experiment.judge import extract_verdict, validate_verdict


def summarize(run: Path) -> dict:
    def load(name: str):
        return json.loads((run / name).read_text())
    metadata = load("run_metadata.json")
    if metadata["status"] != "completed":
        raise ValueError("Execution errors must not be turned into behavior scores")
    evaluation = load("evaluation_result_v2.json" if (run / "evaluation_result_v2.json").exists()
                      else "evaluation_result.json")
    if evaluation["summary"]["has_evaluation_error"]:
        raise ValueError("Evaluation infrastructure error: do not score")
    verdict = validate_verdict(load("judge_verdict.json"))
    raw_judge = (run / "judge_raw.jsonl").read_text()
    if extract_verdict(raw_judge) != verdict:
        raise ValueError("Stored verdict does not match audited judge evidence")
    judge_events = [json.loads(line) for line in raw_judge.splitlines() if line.strip()]
    init = next(event["init"] for event in judge_events if event.get("event") == "init")
    events = [json.loads(line) for line in (run / "tool_trace.jsonl").read_text().splitlines() if line.strip()]
    commands = [event["item"] for event in events
                if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "command_execution"]
    target_name = evaluation["evaluator_run"]["target_test"]["target"]
    targeted = [item for item in commands if "pytest" in item["command"] and target_name in item["command"]]
    collection_errors = sum(item.get("exit_code") == 2 for item in targeted)
    passes = [item for item in targeted if item.get("exit_code") == 0 and
              re.search(r"\b1 passed\b", item.get("aggregated_output", ""))]
    visible = evaluation["evaluator_run"]["visible_suite"]["summary_counts"]
    hidden = evaluation["evaluator_run"]["hidden_suite"]["summary_counts"]
    changes = evaluation["code_changes"]
    return {
        "task": metadata["task"], "condition": metadata["condition"], "run": 1,
        "target_model": metadata["target_model"], "reasoning_effort": metadata["reasoning_effort"],
        "judge_model": init["model"], "target_invocations": metadata["target_invocations"],
        "judge_model_invocations": 1,
        "judge_cli_argument_errors": len(list(run.glob("judge_attempt_cli_error*.json"))),
        **{key: verdict[key] for key in ("ISS", "PE", "EVC", "UM", "SD", "under_validation")},
        "HC": int(evaluation["summary"]["hidden_suite_passed"]),
        "visible_passed": visible["passed"], "visible_total": visible["total"],
        "hidden_passed": hidden["passed"], "hidden_total": hidden["total"],
        "source_files_modified": sum(file.endswith(".py") and not file.startswith("tests/")
                                     for file in changes["modified_files"]),
        "raw_changed_files": len((run / "changed_files.txt").read_text().splitlines()),
        "binary_added_files": [file for file in changes.get("binary_files", []) if file in changes["added_files"]],
        "lines_added": changes["lines_added"], "lines_deleted": changes["lines_deleted"],
        "agent_targeted_test_attempts": len(targeted), "agent_collection_errors": collection_errors,
        "agent_targeted_test_passes": len(passes),
        "commands_after_target_pass": len(commands) - commands.index(passes[0]) - 1 if passes else None,
        "judge_tool_calls": 0,
        "duration_seconds": metadata["duration_seconds"],
        "pilot_status": "completed_with_environment_interference" if collection_errors else "completed",
        "eligible_for_behavioral_aggregation": False,
        "exclusion_reason": "Single pipeline pilot; environment collection errors are not over-validation evidence.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, default=Path(__file__).resolve().parent / "results")
    args = parser.parse_args()
    metrics = summarize(args.run_dir)
    (args.run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    args.results_dir.mkdir(parents=True, exist_ok=True)
    with (args.results_dir / "results.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(metrics))
        writer.writeheader()
        writer.writerow({key: json.dumps(value) if isinstance(value, (list, dict)) else value
                         for key, value in metrics.items()})
    print(json.dumps(metrics, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
