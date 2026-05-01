#!/usr/bin/env bash
set -euo pipefail

# Assisted-study demo: launch Claude Code with the ColPack MCP server and
# agent skill loaded, prefilled with a one-line prompt that points the agent
# at the research program. The program (demo/specs/assisted_study_program.md)
# encodes the methodology; the agent picks composition, pressure range,
# order parameters, and writes the final summary plus plots.
#
# This intentionally bypasses eval/run_experiments (which uses the
# opencode_agent_sdk) — for a real Claude Code demo run we go through the
# native Claude Code CLI via run_colpack.sh's `claude` entry point so the
# agent has the production MCP + skill stack loaded exactly as a user would.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROGRAM_PATH="demo/specs/assisted_study_program.md"

INITIAL_QUERY="Read the research program at \`${PROGRAM_PATH}\` and execute it autonomously. Honor every methodology constraint exactly; the scientific choices it leaves open are yours to make. Run setup → plan → execute → analyze without asking for approval, iterate with a refinement sweep around P* once the coarse sweep brackets the transition, and produce the final summary plus plots in the format the program describes."

cd "$ROOT_DIR"
# --dangerously-skip-permissions: the autonomous research run calls many MCP
# tools (setup, plan, execute, analyze, file reads/writes for the summary
# and plots) and would otherwise pause on every permission prompt. The
# program is trusted (in-repo); skipping prompts is what makes "autonomous"
# actually autonomous.
#
# User-supplied flags ($@) precede the initial query so they're parsed as
# claude flags rather than appended to the query string.
exec "$ROOT_DIR/run_colpack.sh" claude --dangerously-skip-permissions "$@" "$INITIAL_QUERY"
