#!/bin/bash

# ColPack Agent Runner Script

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Activate the hoomd-env conda environment
CONDA_ENV_NAME="hoomd-env"
if command -v conda >/dev/null 2>&1; then
    CONDA_BASE="$(conda info --base 2>/dev/null)"
    if [[ -n "$CONDA_BASE" && -f "$CONDA_BASE/etc/profile.d/conda.sh" ]]; then
        # shellcheck disable=SC1091
        source "$CONDA_BASE/etc/profile.d/conda.sh"
        conda activate "$CONDA_ENV_NAME" || {
            echo "Error: Failed to activate conda environment '$CONDA_ENV_NAME'."
            exit 1
        }
    else
        echo "Error: Could not locate conda.sh to activate '$CONDA_ENV_NAME'."
        exit 1
    fi
else
    echo "Error: conda not found on PATH. Install conda or activate '$CONDA_ENV_NAME' manually."
    exit 1
fi

resolve_python_bin() {
    if [[ -n "${CONDA_PREFIX:-}" && -x "$CONDA_PREFIX/bin/python" ]]; then
        echo "$CONDA_PREFIX/bin/python"
        return
    fi
    if command -v python >/dev/null 2>&1; then
        command -v python
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return
    fi
    echo ""
}

PYTHON_BIN="$(resolve_python_bin)"
if [[ -z "$PYTHON_BIN" ]]; then
    echo "Error: Could not find a Python interpreter. Activate your environment first."
    exit 127
fi

HOOMD_ENV_BIN="$(dirname "$PYTHON_BIN")"

# Function to run as standalone agent (uses agent/app.py SDK runner)
run_standalone() {
    echo "Running standalone agent..."
    "$PYTHON_BIN" "$SCRIPT_DIR/agent/app.py" "${@:2}"
}

# Function to run with opencode (loads agent/opencode.json as project config)
run_with_opencode() {
    echo "Running with opencode..."
    PATH="$HOOMD_ENV_BIN:$PATH" \
    OPENCODE_CONFIG="$SCRIPT_DIR/agent/opencode.json" \
    OPENCODE_CONFIG_DIR="$SCRIPT_DIR/agent" \
    opencode
}

# Function to run with Claude Code
# - MCP:    agent/claude_mcp.json via --mcp-config
# - Agent:  agent/agents/colpack_agent.md injected as appended system prompt
# - Skill:  agent/skills/colpack/SKILL.md symlinked into ~/.claude/skills/ by 'setup'
run_with_claude() {
    echo "Running with Claude Code..."
    PATH="$HOOMD_ENV_BIN:$PATH" \
    claude --mcp-config "$SCRIPT_DIR/agent/claude_mcp.json" \
           --add-dir "$SCRIPT_DIR" \
           --append-system-prompt-file "$SCRIPT_DIR/agent/agents/colpack_agent.md"
}

# Function to run with Gemini CLI
# - MCP:    agent/.gemini/settings.json (mcpServers)
# - Agent:  agent/.gemini/settings.json (systemPrompt)
# - Skill:  agent/.gemini/skills/colpack -> agent/skills/colpack (linked by 'setup')
# Gemini reads .gemini/ from CWD, so we cd into agent/ and include the project root.
run_with_gemini() {
    echo "Running with Gemini CLI..."
    cd "$SCRIPT_DIR/agent" && \
    PATH="$HOOMD_ENV_BIN:$PATH" \
    /opt/homebrew/bin/gemini --include-directories "$SCRIPT_DIR"
}

# Function to run with Codex
# - MCP:    ~/.codex/config.toml (mcp_servers.colpack, registered by this script)
# - Agent:  agent/AGENTS.md (auto-read by Codex from CWD, so we cd into agent/)
# - Skill:  No native skill concept in Codex
run_with_codex() {
    echo "Running with Codex..."
    cd "$SCRIPT_DIR/agent" && \
    PATH="$HOOMD_ENV_BIN:$PATH" \
    codex
}

# One-time setup: register the colpack skill with Claude Code and Gemini CLI.
# Run this once after cloning or when the skill path changes.
setup_skills() {
    echo "Setting up ColPack skills and agents..."

    # Claude Code: symlink agent/skills/colpack into ~/.claude/skills/
    CLAUDE_SKILLS_DIR="$HOME/.claude/skills"
    mkdir -p "$CLAUDE_SKILLS_DIR"
    ln -sf "$SCRIPT_DIR/agent/skills/colpack" "$CLAUDE_SKILLS_DIR/colpack"
    echo "  ✓ Claude Code: ~/.claude/skills/colpack -> agent/skills/colpack"

    # Gemini: recreate system.md symlink (relative, points to ../agents/colpack_agent.md)
    ln -sf ../agents/colpack_agent.md "$SCRIPT_DIR/agent/.gemini/system.md"
    echo "  ✓ Gemini: agent/.gemini/system.md -> ../agents/colpack_agent.md"

    # Gemini: link skill so it appears in /skills list (absolute symlink into agent/.gemini/skills/)
    mkdir -p "$SCRIPT_DIR/agent/.gemini/skills"
    ln -sf "$SCRIPT_DIR/agent/skills/colpack" "$SCRIPT_DIR/agent/.gemini/skills/colpack"
    echo "  ✓ Gemini: agent/.gemini/skills/colpack -> agent/skills/colpack"

    # Codex: symlink agent/skills/colpack into ~/.codex/skills/
    CODEX_SKILLS_DIR="$HOME/.codex/skills"
    mkdir -p "$CODEX_SKILLS_DIR"
    ln -sf "$SCRIPT_DIR/agent/skills/colpack" "$CODEX_SKILLS_DIR/colpack"
    echo "  ✓ Codex: ~/.codex/skills/colpack -> agent/skills/colpack"

    echo "Done."
}

# Main menu
if [[ $# -eq 0 ]]; then
    echo "Usage: $0 [standalone|opencode|claude|gemini|codex|setup]"
    echo ""
    echo "Options:"
    echo "  standalone  - Run as standalone agent (app.py SDK runner)"
    echo "  opencode    - Run with opencode (agent/opencode.json)"
    echo "  claude      - Run with Claude Code (agent/claude_mcp.json)"
    echo "  gemini      - Run with Gemini CLI (.gemini/settings.json)"
    echo "  codex       - Run with Codex (~/.codex/config.toml)"
    echo "  setup       - One-time: register colpack skill with Claude Code, Gemini, and Codex"
    exit 1
fi

case "$1" in
    standalone)
        run_standalone
        ;;
    opencode)
        run_with_opencode
        ;;
    claude)
        run_with_claude
        ;;
    gemini)
        run_with_gemini
        ;;
    codex)
        run_with_codex
        ;;
    setup)
        setup_skills
        ;;
    *)
        echo "Invalid option: $1"
        exit 1
        ;;
esac