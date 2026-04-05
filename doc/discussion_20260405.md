Here are the detailed, step-by-step instructions to build out the `agent/` directory. This structure sets up the Markdown "brain" (the Skill) and the standalone Python application wrapper using the OpenCode Agent SDK.

### 1. Directory Setup
Navigate to the root of your repository and create the following structure:

```bash
mkdir -p agent/skills/colpack/references
touch agent/requirements.txt
touch agent/app.py
touch agent/skills/colpack/SKILL.md
touch agent/skills/colpack/references/1_setup_problem.md
touch agent/skills/colpack/references/2_plan_runs.md
touch agent/skills/colpack/references/3_execute_simulation.md
```

### 2. The Requirements File (`agent/requirements.txt`)
We need the core SDK and the MCP utilities to bridge the agent with your FastMCP server.

```text
opencode-agent-sdk>=0.4.12
fastmcp
```

### 3. The Master Orchestrator (`agent/skills/colpack/SKILL.md`)
This file is the executive brain. It establishes the persona, the tool requirements, and the strict sequence of operations.

```markdown
# Persona
You are ColPackAgent, an expert soft matter physics AI assistant powered by HOOMD-blue and Freud. Your goal is to autonomously orchestrate particle packing and polymer simulations.

# The Workflow Loop
You must strictly follow this sequence for all tasks. Never skip a step.

### Step 1: Setup
**Action:** Call `setup_simulation_problem_tool`.
**Rule:** Before calling this tool, you MUST read `references/1_setup_problem.md` to understand the exact JSON schema, allowed 2D/3D shapes, and required dimension formatting.

### Step 2: Plan
**Action:** Call `plan_simulation_runs_tool`.
**Rule:** Before calling this tool, you MUST read `references/2_plan_runs.md` to learn how to structure `baseline_parameters` and formulate the dot-notation for `tunable_parameters` (e.g., `particle_specs.1.diameter`).

### Step 3: Execute & Analyze
**Action:** Call `execute_simulation_workflow_tool`.
**Rule:** Before calling this tool, you MUST read `references/3_execute_simulation.md`. If the execution tool returns `"n_failed" > 0`, you must automatically read the `workflow_status.csv` in the working directory to diagnose the crash before reporting back to the user.
```

### 4. The Standard Operating Procedures (`agent/skills/colpack/references/`)
These files contain the "few-shot" examples that guarantee the LLM formats its tool calls correctly. Here is an example of what `1_setup_problem.md` should look like:

**`1_setup_problem.md`**
```markdown
# Guide: Setting up Simulation Problems

When calling the `setup_simulation_problem_tool`, your input must exactly match the schema.

### Allowed Configurations
- **2D Shapes:** `disk`, `ellipse`, `polygon`, `capsule`.
- **3D Shapes:** `sphere`, `ellipsoid`, `polyhedron`, `cube`, `capsule`.
- **Ensembles:** `NVT` (constant volume) or `NPT` (constant pressure).

### Example Payload: Binary 2D Mixture
```json
{
  "dimension": 2,
  "total_particle_number": 200,
  "particle_shape_list": ["disk", "capsule"],
  "ensemble": "NVT",
  "working_dir": "/data/current_run"
}
```
*Note: Write similar files for `2_plan_runs.md` and `3_execute_and_troubleshoot.md` focusing strictly on JSON examples and edge cases for those specific tools.*

### 5. The Standalone Wrapper (`agent/app.py`)
This is the programmatic entry point for users who just want to run the application without installing a separate IDE. It reads your `SKILL.md`, initializes the OpenCode SDK, and automatically attaches your FastMCP server.

```python
import asyncio
import os
from pathlib import Path
from opencode_agent_sdk import OpenCodeAgent, LocalMCPClient

async def main():
    print("Booting ColPackAgent...")

    # 1. Load the "Brain"
    # We read the main SKILL.md to act as the agent's system prompt
    skill_path = Path(__file__).parent / "skills" / "colpack" / "SKILL.md"

    if not skill_path.exists():
        print(f"Error: Could not find skill file at {skill_path}")
        return

    system_prompt = skill_path.read_text()

    # 2. Initialize the OpenCode Agent
    agent = OpenCodeAgent(system_prompt=system_prompt)

    # 3. Mount the MCP Tools (The "Hands")
    # This automatically spawns your FastMCP server in the background
    # using the CLI command defined in your pyproject.toml
    try:
        mcp_server = LocalMCPClient(command="colpack-mcp")
        agent.attach_tools(mcp_server)
        print("Successfully attached simulation tools via FastMCP.")
    except Exception as e:
        print(f"Failed to attach tools. Did you run `pip install -e ./src/`? Error: {e}")
        return

    print("\n================================================")
    print(" ColPackAgent Ready. Type 'exit' to quit.")
    print("================================================")

    # 4. The Orchestration Loop
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ['exit', 'quit']:
                print("Shutting down ColPackAgent...")
                break
            if not user_input.strip():
                continue

            # The SDK handles the iterative tool-calling loop automatically
            response = await agent.chat(user_input)
            print(f"\nColPackAgent: {response.text}")

        except KeyboardInterrupt:
            print("\nShutting down ColPackAgent...")
            break
        except Exception as e:
            print(f"\nAgent Error: {e}")

if __name__ == "__main__":
    # Ensure the script runs gracefully
    asyncio.run(main())
```

### Execution
With this structure, the dual-use capability is fully unlocked:
1. **To run it standalone:** A user simply types `python agent/app.py` and starts chatting in the terminal.
2. **To use it in an IDE:** You point Claude Code or the OpenCode CLI directly to the `agent/skills/colpack/` folder, and the LLM natively adopts the instructions and tools.