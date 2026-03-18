Here is the complete, end-to-end blueprint for building the **ColPackAgent** using the v2 "Smart Package" architecture.

This guide covers everything from the foundational physics code to the MCP-powered AI interface, ensuring your system is robust, portable, and framework-agnostic.

---

## 🏗️ The ColPackAgent Blueprint: v2 "Smart Package" Architecture

**Goal:** A multi-agent system for soft matter simulations that ships as a single, intelligent Python package. It contains the core physics engine for human scientists and an embedded MCP server for AI agents, all orchestrated by portable Markdown skills.

### 🌳 The Monorepo File System

This structure embeds the CLI tools directly into the Python package while keeping the agent's "brain" (the skills) completely portable.

```text
ColPackAgent/
├── README.md                  # Main repository instructions
├── .gitignore
│
├── src/                       # 📦 DOMAIN 1 & 2: Physics + Native AI Interface
│   ├── pyproject.toml         # Defines 'colpack' AND the 'colpack-mcp' command
│   ├── README.md              # Package description for PyPI
│   └── colpack/
│       ├── __init__.py
│       ├── device.py          # Core physics & hardware abstraction
│       ├── init.py            # HPMC shape mapping & state creation
│       ├── compress.py        # System compression logic
│       ├── thermalize.py      # NVT/NPT logic
│       ├── production.py      # High-performance sampling loops
│       ├── planning.py        # Parameter grid generators
│       ├── analysis.py        # Dataframes & Plotting
│       │
│       └── mcp/             # 🔌 THE AI ADAPTER: MCP Server lives here
│           ├── __init__.py
│           └── server.py      # FastMCP implementation & Pydantic schemas
│
├── agent/                     # 🧠 DOMAIN 3: Pure Agent Intelligence
│   └── skills/
│       └── colpack/
│           ├── SKILL.md       # The Master Orchestrator (with installation rules)
│           └── references/    # Optional: Sub-skills for long workflows
│               ├── 0_bootstrap.md
│               ├── 1_setup.md
│               └── 2_compress.md
│
├── data/                      # 🗄️ The Data Lake (The Agent's Working Directory)
│   └── 2026_test_run/         # Isolated workspace for specific runs
│
└── tests/                     # Unit tests for the physics engine

```

---

## 📅 The 5-Step Implementation Guide

### Step 1: Build the Independent Scientific Package (`src/colpack`)

Before an agent can do anything, the underlying physics logic must be sound. You build this exactly as you would a standard Python package.

* **Action:** Develop the pure physics modules inside `src/colpack/` (e.g., `init.py`, `compress.py`).
* **Focus:** Ensure functions accept standard Python data types (lists, dicts, floats) rather than relying on CLI `argparse`.
* **Developer Workflow:** Run `pip install -e ./src/` from the root directory so your local changes are instantly testable.

### Step 2: Embed the MCP Server (`src/colpack/agent/server.py`)

This is where you build the bridge between the LLM and your physics code. You will define strict rules for what the agent is allowed to send.

* **Action:** Create the `server.py` file using the `mcp` SDK.
* **Define Schemas:** Use `pydantic` to create rigid data structures (like `ParticleParam` and `ShapeDef`). If the agent tries to send a string when a float is required, Pydantic will block it and return an error.
* **Wrap Functions:** Use the `@mcp.tool()` decorator to wrap your functions from Step 1. Inside these wrappers, import your `colpack` modules and pass the validated Pydantic data into your physics engine.
* **Entry Point:** Include a `main()` function at the bottom of the file that calls `mcp.run()`.

### Step 3: Configure the Universal Installer (`src/pyproject.toml`)

You need to package the physics engine and the MCP server together so they can be installed with a single command.

* **Action:** Update your `pyproject.toml` to list all dependencies (`hoomd`, `numpy`, `pydantic`, `mcp`).
* **The Magic Link:** Add a `[project.scripts]` section to define a terminal command:
```toml
[project.scripts]
colpack-mcp = "colpack.agent.server:main"

```


* **Result:** When anyone installs the package, their system automatically gets a `colpack-mcp` command that spins up the tool server.

### Step 4: Establish the Self-Bootstrapping Skill (`agent/skills/colpack/SKILL.md`)

You must teach the AI agent how to install its own tools and orchestrate the workflow.

* **Action:** Write your Markdown instructions.
* **The Bootstrap Protocol:** The very first section of your skill must instruct the agent to:
1. Install the local package: `pip install -e ./src/`
2. Attach the MCP tools to its own context: `mcp add colpack-tools command colpack-mcp` (or the equivalent command for the specific framework like Claude Code).


* **The Workflow:** Define the steps the agent should take once the tools are active (e.g., "Ask the user for particle types, then call the `setup_sim` tool").

### Step 5: Execution, Testing, and Distribution

With the architecture complete, you can run the agent locally or share it with the world.

* **Local Testing:** Open your preferred AI IDE (OpenCode, Claude Code, Cursor) inside the `data/` directory. Point the agent to your `SKILL.md` file and ask it to run a simulation. It will read the instructions, install the package, boot the server, and execute natively.
* **Publishing:** Build your wheels (`python3 -m build` inside the `src/` folder) and publish to PyPI.
* **The Final Handoff:** Anyone can now clone the repo, give the `agent/` folder to their AI of choice, and instantly have a fully autonomous soft matter simulation assistant.

---

Would you like me to draft the exact code for `src/colpack/agent/server.py` so we can lock in the Pydantic schemas for your `setup_sim` and `compress_sim` tools?