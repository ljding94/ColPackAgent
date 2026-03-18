This is the consolidated, comprehensive plan for building **ColPackAgent**. This summary integrates our discussions on hardware portability (MacBook ↔ DGX), the "Library Pattern" for skills, and the expanded agent roles (Planner/Researcher).

https://gemini.google.com/share/213a01113510
---

## 🏗️ Project Vision: ColPackAgent

**Goal:** A multi-agent system for soft matter simulations (HOOMD-blue) that writes its own Python code, manages its own validation loops, and scales seamlessly from a local laptop to a multi-GPU cluster.

### 🌳 The Master Architecture (Monorepo)

We are using a **Parallel Structure**: Clean scientific code in `src/` and AI reasoning in `agent/`.

```text
ColPackAgent/
├── pyproject.toml             # Defines 'colpack' as an installable package
├── environment.yml            # Cross-platform deps (micromamba: linux-64/osx-arm64)
├── README.md                  # Instructions: "pip install -e ."
│
├── src/                       # 🛠️ THE BODY (The 'colpack' Python Package)
│   └── colpack/               # Importable via "import colpack"
│       ├── __init__.py
│       ├── device.py          # 🧠 Hardware Abstraction Layer (HAL)
│       ├── init.py            # HPMC shape mapping & state creation
│       ├── compress.py        # compress the system to target density
│       ├── thermalize.py      # NVT/NPT logic + "is_equilibrated()" checks
│       ├── production.py      # High-performance sampling loops
│       ├── planning.py        # Parameter grid generators (for Planner Agent)
│       └── analysis.py        # Dataframes & Plotting (for Research Agent)
│
├── data/                      # The data lack
│   ├── 20260202_test_run/     # automatic timestamp + topic ID
│   │   ├── metadata.json      # Agent notes: "User tested hard spheres"
│   │   ├── init.gsd
│   │   └── trajectory.gsd
│   │
│   └── 20260203_polymer_sweep/
│       ├── run_params.json
│       └── ...
│
├── agent/                     # 🧠 THE BRAIN (OpenCode Configuration)
│   ├── .opencode/
│   │   ├── opencode.json      # Global agent settings
│   │   └── skills/            # The "Standard Operating Procedures"
│   │       ├── 1_setup/       # "How to use colpack.init"
│   │       ├── 2_compress/    # "How to use colpack.compress"
│   │       ├── 3_thermal/     # "How to use colpack.thermalize"
│   │       ├── 4_run/         # "How to use colpack.production"
│   │       ├── 5_plan/        # "How to design a parameter sweep"
│   │       └── 6_research/    # "How to compile results into a Report.docx"
│   └── benchmarks/            # Scripts to test agent intelligence
│
├── tests/                     # Unit tests to verify the 'src' physics is correct
│
└── colpack_agent.py           # run this: "python3 colpack_agent.py"

```

---

## 📅 The 3-Step Implementation Plan

### Step 1: The "Agent-Ready" Package (`src/colpack`)

**Goal:** Build the scientific engine.

* **Action:** Create the Python package with the structure above.
* **Key Innovation:** Implement `colpack.device.get_device()` to auto-detect hardware.
* *MacBook:* Returns `hoomd.device.CPU` (or Metal).
* *DGX:* Returns `hoomd.device.GPU`.


* **Development:** You write this manually (with AI help) and test it using `pytest` to ensure physics correctness.
* **Install:** `pip install -e .` allows the agent to "see" your edits instantly.

### Step 2: The Skill Injection (`agent/skills`)

**Goal:** Teach the Agent how to use the engine.

* **Action:** Create `SKILL.md` files for each module.
* **Strategy:** The **"Library Pattern"**.
* Instead of telling the agent "Run this terminal command," we tell it "Write a Python script that imports `colpack`."
* This allows the agent to use Python logic (loops, `if/else`) to handle errors (e.g., "If `is_equilibrated()` returns False, double the timesteps").




### Step 3: The Scalable Orchestration

**Goal:** Enable "Write Once, Run Anywhere."

* **Workflow:**
1. **Planner Agent** (using `colpack.planning`) generates a list of 50 simulations.
2. **Coordinator Agent** spawns jobs.
3. **Runner Agent** (using `colpack.production`) executes them.
* On **Mac**: Runs sequentially (slow but works).
* On **DGX**: Runs in parallel (8x A100s) via the OpenCode SDK/Docker wrapper.


4. **Researcher Agent** (using `colpack.analysis`) watches the output folder and compiles the final `.docx` report.



---

### ✅ Success Criteria for this Plan

1. **Portability:** The same agent prompt works on your Mac and the DGX.
2. **Modularity:** You can upgrade the "Thermalization" logic in `src` without breaking the "Planner" agent.
3. **Self-Correction:** The agent can catch physics errors (overlaps, explosions) programmatically because it "owns" the running script.

**Ready to start?**
I can now generate the code for **Step 1.1**: The `device.py` module, which is the foundation for making this entire system hardware-agnostic. Would you like that?