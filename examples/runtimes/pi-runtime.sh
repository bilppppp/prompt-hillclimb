#!/usr/bin/env bash
# Reference wrapper for Pi Coding Assistant CLI conforming to Runtime Contract
# Contract:
# - Read full prompt from stdin
# - Write final response ONLY to stdout
# - Write diagnostics/warnings to stderr
# - Exit 0 on success, non-zero on failure
# - Each run is fresh, stateless, and independent

set -euo pipefail

# 1. Check executable
if ! command -v pi >/dev/null 2>&1; then
  echo "Error: 'pi' executable not found in PATH" >&2
  exit 127
fi

# 2. Check for global context files and issue diagnostics to stderr
PI_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
if [[ -f "${PI_DIR}/SYSTEM.md" ]]; then
  echo "WARNING: Global system prompt detected at ${PI_DIR}/SYSTEM.md. Pi's --no-context-files does not disable SYSTEM.md and may affect evaluations." >&2
fi
if [[ -f "${PI_DIR}/APPEND_SYSTEM.md" ]]; then
  echo "WARNING: Global append system prompt detected at ${PI_DIR}/APPEND_SYSTEM.md. Pi's --no-context-files does not disable APPEND_SYSTEM.md and may affect evaluations." >&2
fi

# 3. Read prompt from stdin preserving trailing newlines and validate non-empty
PROMPT=""
IFS= read -r -d '' PROMPT || true
if [[ -z "${PROMPT//[[:space:]]/}" ]]; then
  echo "Error: stdin prompt is empty" >&2
  exit 1
fi

# 4. Create a fresh isolated temporary working directory
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/pi_runtime_XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$TMP_DIR"

# 5. Execute pi reading prompt from stdin in non-interactive mode
# -p: process prompt from stdin and print response
# --no-tools: disable built-in and extension tools
# --no-skills: disable skills discovery
# --no-context-files: disable AGENTS.md / CLAUDE.md discovery
# --no-extensions: disable extension discovery
# --no-session: ephemeral session, do not save
# --no-prompt-templates: disable prompt template discovery
# --no-themes: disable theme loading
# --no-approve: ignore project-local files
OUTPUT="$(printf '%s' "$PROMPT" | pi \
  -p \
  --no-tools \
  --no-skills \
  --no-context-files \
  --no-extensions \
  --no-session \
  --no-prompt-templates \
  --no-themes \
  --no-approve)"

if [[ -z "${OUTPUT//[[:space:]]/}" ]]; then
  echo "Error: Pi produced empty or whitespace-only output" >&2
  exit 1
fi

printf '%s\n' "$OUTPUT"
