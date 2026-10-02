#!/usr/bin/env bash
# Reference wrapper for OpenAI Codex CLI conforming to Runtime Contract
# Contract:
# - Read full prompt from stdin
# - Write final response ONLY to stdout
# - Write diagnostics/warnings to stderr
# - Exit 0 on success, non-zero on failure
# - Each run is fresh, stateless, and independent

set -euo pipefail

# 1. Check executable
if ! command -v codex >/dev/null 2>&1; then
  echo "Error: 'codex' executable not found in PATH" >&2
  exit 127
fi

# 2. Check for global context files and issue diagnostics to stderr
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
if [[ -f "${CODEX_HOME}/AGENTS.md" ]]; then
  echo "WARNING: Global instructions detected at ${CODEX_HOME}/AGENTS.md. Codex cannot completely disable global instructions and may affect evaluations." >&2
fi
if [[ -d "${CODEX_HOME}/skills" ]]; then
  echo "WARNING: Global skills directory detected at ${CODEX_HOME}/skills. Codex read-only sandbox restricts file writes, but does not disable tool discovery." >&2
fi

# 3. Read prompt from stdin preserving trailing newlines and validate non-empty
PROMPT=""
IFS= read -r -d '' PROMPT || true
if [[ -z "${PROMPT//[[:space:]]/}" ]]; then
  echo "Error: stdin prompt is empty" >&2
  exit 1
fi

# 4. Create a fresh isolated temporary working directory and switch to it
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/codex_runtime_XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$TMP_DIR"
OUTPUT_FILE="${TMP_DIR}/last_message.txt"

# 5. Execute codex exec reading prompt from stdin
# -C: isolated empty cwd
# --skip-git-repo-check: run outside repo bounds
# --ephemeral: do not persist session to disk
# --ignore-user-config: ignore user config.toml
# --ignore-rules: ignore custom rules
# -s read-only: sandbox read-only
# --color never: avoid ANSI color escape sequences
# -o: write last model message directly to file
# -: read initial instructions from stdin
# >&2: redirect codex process stdout to stderr so stdout receives ONLY the final response
printf '%s' "$PROMPT" | codex exec \
  -C "$TMP_DIR" \
  --skip-git-repo-check \
  --ephemeral \
  --ignore-user-config \
  --ignore-rules \
  -s read-only \
  --color never \
  -o "$OUTPUT_FILE" \
  - >&2

# 6. Validate output file
if [[ ! -f "$OUTPUT_FILE" ]]; then
  echo "Error: Codex last message output file was not created: ${OUTPUT_FILE}" >&2
  exit 1
fi

OUTPUT="$(cat "$OUTPUT_FILE")"
if [[ -z "${OUTPUT//[[:space:]]/}" ]]; then
  echo "Error: Codex produced empty or whitespace-only output" >&2
  exit 1
fi

# 7. Stream final answer to stdout
printf '%s\n' "$OUTPUT"
