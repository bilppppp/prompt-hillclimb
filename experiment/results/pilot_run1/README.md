# Pilot Run 1 Archive: P0 / T02 / run1

This directory contains the sanitized, tracked evidence and artifacts for the single pilot run **T02 / P0 / run1** (`gpt-6-astra` with reasoning effort `medium`).

> [!NOTE]
> The full, unredacted local execution logs remain preserved in the git-ignored directory `experiment/runs/layer1/P0/T02/run1/`.
> The files published in this directory are a sanitized copy where host-specific absolute paths (such as `/Users/...` and temporary macOS paths) have been replaced with standard placeholders (`<host-project>`, `<workspace>`, `<runtime>`, `<user-home>`, `<sandbox-tmp>`). Internal CLI session authentication logs (`judge_cli.log`) have been excluded. All scores, test outcomes, command traces, error sequences, and execution facts are preserved verbatim.

## Evidence Index

### Target Execution (Codex `gpt-6-astra`)
- [prompt.txt](prompt.txt): The initial prompt sent to the model.
- [final_response.txt](final_response.txt): The model's final response text upon completion.
- [transcript.txt](transcript.txt): Full textual transcript of the conversation and tool calls.
- [tool_trace.jsonl](tool_trace.jsonl): Machine-readable JSONL stream of all tool execution events.
- [diff.patch](diff.patch): Git unified diff of all changes made in the workspace.
- [changed_files.txt](changed_files.txt): List of files created or modified by the model.
- [codex_stderr.txt](codex_stderr.txt): Stderr output during the Codex execution.
- [run_metadata.json](run_metadata.json): Execution metadata including duration, command invocation, and sandbox permissions.

### Deterministic Evaluation
- [visible_tests.txt](visible_tests.txt): Evaluator test execution output for repo visible tests (5/5 passed).
- [hidden_tests.txt](hidden_tests.txt): Evaluator test execution output for external hidden tests (6/6 passed, 0 skipped, 0 error).
- [evaluation_result.json](evaluation_result.json): Initial deterministic evaluation record.
- [evaluation_result.patch](evaluation_result.patch): Initial diff patch.
- [evaluation_result_v2.json](evaluation_result_v2.json): Corrected deterministic evaluation record (excluding `xcrun_db` binary tool cache from source LOC).
- [evaluation_result_v2.patch](evaluation_result_v2.patch): Cleaned patch.
- [metrics.json](metrics.json): Computed metrics summary (ISS, HC, PE, EVC, UM, SD).

### Blind Judge Evaluation (Gemini 3.8 Flash High)
- [judge_prompt.txt](judge_prompt.txt): Blind prompt delivered to the judge (task + repo summary + diff + objective test facts + tool trace, excluding condition label, target prompt, and hidden test code).
- [judge_verdict.json](judge_verdict.json): The judge's structured verdict and rationale.
- [judge_raw.jsonl](judge_raw.jsonl): Native JSONL stream recorded from the judge session.
- [judge_stderr.txt](judge_stderr.txt): Judge stderr log.
- [judge_attempt.json](judge_attempt.json): Metadata for the successful judge run.
- [judge_attempt_cli_error.json](judge_attempt_cli_error.json): Pre-run CLI argument syntax error record (attempt 1).
- [judge_attempt_cli_error_2.json](judge_attempt_cli_error_2.json): Pre-run CLI argument syntax error record (attempt 2).
- [judge_cli_error_raw.jsonl](judge_cli_error_raw.jsonl) & [judge_cli_error_stderr.txt](judge_cli_error_stderr.txt): Stream and stderr for attempt 1.
- [judge_cli_error_2_raw.jsonl](judge_cli_error_2_raw.jsonl) & [judge_cli_error_2_stderr.txt](judge_cli_error_2_stderr.txt): Stream and stderr for attempt 2.

### Historical Middleware Snapshots
- [runner_at_execution.py](runner_at_execution.py): Snapshot of `runner.py` at the time of execution.
- [evaluator_at_execution.py](evaluator_at_execution.py): Snapshot of `evaluator.py` at the time of execution.
- [judge_at_execution.py](judge_at_execution.py): Snapshot of `judge.py` at the time of execution.
