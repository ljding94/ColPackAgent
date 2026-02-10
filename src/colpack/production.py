import os
import gsd.hoomd
import hoomd
import math
import json
from colpack.helper import read_state, save_state


def production_run(production_steps, system_dir, seed=0):
    """
    particle_list_json, thermalized_gsd files are expected in system_dir
    then perform production run for a given number of steps
    finally save the production run system to system_dir/production.gsd
    """
    # load particle list and initial gsd
    thermalize_summar_path = os.path.join(system_dir, "thermalize_summary.json")
    thermalize_gsd_path = os.path.join(system_dir, "thermalized.gsd")

    sim, mc, thermalize_summary = read_state(thermalize_summar_path, thermalize_gsd_path)

    sim.run(production_steps)
    print(f"Production run completed after {production_steps} steps.")
    print(f"production run overlaps:", mc.overlaps)
    print(f"production run move size: {mc.translate_moves}, rotation move size: {mc.rotate_moves}")

    # step 5: save the compressed system
    gsd_path = os.path.join(system_dir, "production.gsd")
    save_state(sim, thermalize_summary["particle_list"], gsd_path)

    summary = thermalize_summary.copy()
    summary["production_steps"] = production_steps
    summary["overlaps"] = mc.overlaps

    summary_path = os.path.join(system_dir, "production_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=4)

    return summary