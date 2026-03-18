# need to define the server for the agent to use colpack tools
# 1. setup_simulation: this tool should initialize the simulation, and compress it
# 2. run_simulation: this tool should run the simulation and analyze the simulation data
# 3. plan_simulation: this tool plan a list of parameters to run the simulation

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# TODO: need to define the mcp tools

# Create the single unified server (The Toolbox)
mcp = FastMCP("ColPackTools")

# ==========================================
# TOOL 1: SETUP & COMPRESS
# ==========================================
class SetupParams(BaseModel):
    # Define your setup inputs here (e.g., the list of particle dictionaries)
    pass

@mcp.tool()
def setup_sim(params: SetupParams) -> str:
    """Initializes and compresses the simulation state."""
    import colpack
    # Your initialization and compression logic goes here
    return "Setup complete. System is compressed and ready."


# ==========================================
# TOOL 2: RUN & ANALYZE
# ==========================================
class RunParams(BaseModel):
    # Define your run inputs here (e.g., timesteps, temperature)
    pass

@mcp.tool()
def run_sim(params: RunParams) -> str:
    """Runs the main NVT/NPT production loop and analyzes the output."""
    import colpack
    # Your thermalization, sampling, and analysis logic goes here
    return "Simulation finished. Analysis saved to data folder."

# ==========================================
# TOOL 3: PLAN SIMULATION
# ==========================================
class PlanParams(BaseModel):
    # Define your planning inputs here (e.g., parameter ranges, number of runs)
    pass

# ==========================================
# ENTRY POINT
# ==========================================
def main():
    mcp.run()

if __name__ == "__main__":
    main()