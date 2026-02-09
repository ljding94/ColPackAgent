

# TODO: nee to reevaluate if we nee this
def read_state(system_dir, summary_file="init_summary.json", gsd_file="init.gsd"):
# may put some helper function hereinit_gsd_path = os.path.join(system_dir, "init.gsd")
    init_summary_path = os.path.join(system_dir, "init_summary.json")
    with open(init_summary_path, "r") as f:
        init_summary = json.load(f)
        # particle_specs, particle_list, total_particles, number_density, box_length, overlaps
    particle_list = init_summary["particle_list"]
    init_number_density = init_summary["number_density"]
    init_box_length = init_summary["box_length"]
    total_N = init_summary["total_particles"]

    print("system initial number density:", init_number_density, "target number density:", target_number_density, "total particles:", total_N, "initial box length:", init_box_length)

    # step 2: set up hoomd system
    device = hoomd.device.GPU() if hoomd.device.GPU.is_available() else hoomd.device.CPU()
    sim = hoomd.Simulation(device=device, seed=seed)
    sim.create_state_from_gsd(filename=init_gsd_path)

    # step 3: step up the integrator and mc
    integrator = particle_list[0]["pIntegrator"]
    if integrator == "Sphere":
        mc = hoomd.hpmc.integrate.Sphere()
    elif integrator == "Ellipsoid":
        mc = hoomd.hpmc.integrate.Ellipsoid()
    elif integrator == "ConvexSpheropolygon":
        mc = hoomd.hpmc.integrate.ConvexSpheropolygon()
    elif integrator == "ConvexSpheropolyhedron":
        mc = hoomd.hpmc.integrate.ConvexSpheropolyhedron()
    else:
        raise ValueError(f"Unsupported integrator type: {integrator}")

    print("Using integrator:", integrator)
    for particle in particle_list:
        print("particle type:", particle["pType"], "shape:", particle["pShape"])
        mc.shape[particle["pType"]] = particle["pShape"]

    sim.operations.integrator = mc