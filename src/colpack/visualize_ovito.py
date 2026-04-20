import numpy as np
from pathlib import Path
from ovito.io import import_file
# ColPack visualization runs in headless MCP/batch environments; OpenGLRenderer requires a
# display context and causes a hard native crash there. TachyonRenderer is a CPU software
# renderer (headless-safe) — analogous to matplotlib.use("Agg") for plotting.
from ovito.vis import Viewport, TachyonRenderer


ORTHO_MARGIN_FACTOR = 0.575
CAMERA_DISTANCE_FACTOR = 4.0


def _resolve_render_size(width_inch, height_inch, dpi):
    if width_inch is None or height_inch is None:
        raise ValueError("width_inch and height_inch must be provided together.")

    if dpi <= 0:
        raise ValueError("dpi must be positive.")

    width_px = int(float(width_inch) * int(dpi))
    height_px = int(float(height_inch) * int(dpi))
    if width_px <= 0 or height_px <= 0:
        raise ValueError("Resolved render size must be positive.")

    return width_px, height_px


def _embed_png_dpi(output_path: Path, dpi: int, debug: bool = False):
    try:
        from PIL import Image
    except ImportError:
        if debug:
            print("visualize_gsd: Pillow not installed; skipping PNG DPI metadata.")
        return

    with Image.open(output_path) as image:
        image.save(output_path, dpi=(dpi, dpi))


def _normalize_vector(vector):
    norm = np.linalg.norm(vector)
    if norm <= 0:
        raise ValueError("Cannot normalize a zero-length vector.")
    return vector / norm


def _get_cell_vectors_and_origin(cell):
    matrix = np.asarray(cell.matrix, dtype=float)
    if matrix.shape == (3, 4):
        cell_vectors = matrix[:, :3]
        origin = matrix[:, 3]
    elif matrix.shape == (3, 3):
        cell_vectors = matrix
        origin = np.zeros(3, dtype=float)
    else:
        raise ValueError(f"Unsupported OVITO cell matrix shape: {matrix.shape}")

    return cell_vectors, origin


def _build_box_corners(cell_vectors, origin, is_2d):
    a_vec = cell_vectors[:, 0]
    b_vec = cell_vectors[:, 1]
    c_vec = cell_vectors[:, 2]
    corners = []
    k_values = [0] if is_2d else [0, 1]

    for i in [0, 1]:
        for j in [0, 1]:
            for k in k_values:
                corner = origin + i * a_vec + j * b_vec + k * c_vec
                corners.append(corner)

    return np.asarray(corners, dtype=float)


def _configure_viewport_from_box(vp, cell, is_2d, aspect_ratio, debug=False):
    cell_vectors, origin = _get_cell_vectors_and_origin(cell)
    corners = _build_box_corners(cell_vectors, origin, is_2d)
    center = corners.mean(axis=0)

    if is_2d:
        camera_dir = np.array([0.0, 0.0, -1.0], dtype=float)
        camera_up = np.array([0.0, 1.0, 0.0], dtype=float)
    else:
        camera_dir = _normalize_vector(np.array([-1.0, -0.8, -0.6], dtype=float))
        camera_up = np.array([0.0, 0.0, 1.0], dtype=float)

    camera_right = _normalize_vector(np.cross(camera_dir, camera_up))
    camera_up = _normalize_vector(np.cross(camera_right, camera_dir))

    projected_right = corners @ camera_right
    projected_up = corners @ camera_up
    span_right = float(projected_right.max() - projected_right.min())
    span_up = float(projected_up.max() - projected_up.min())
    required_fov = max(span_up, span_right / max(aspect_ratio, 1e-9))
    required_fov = max(required_fov, 1e-6) * ORTHO_MARGIN_FACTOR

    box_extents = corners.max(axis=0) - corners.min(axis=0)
    max_dim = float(max(box_extents.max(), 1.0))
    camera_distance = max_dim * CAMERA_DISTANCE_FACTOR

    vp.type = Viewport.Type.Ortho
    vp.camera_dir = tuple(camera_dir)
    vp.camera_up = tuple(camera_up)
    vp.camera_pos = tuple(center - camera_dir * camera_distance)
    vp.fov = required_fov

    if debug:
        print(
            "visualize_gsd: viewport framed from simulation box "
            f"(center={center.tolist()}, span_right={span_right:.4f}, span_up={span_up:.4f}, fov={required_fov:.4f})"
        )


def render_physical_size(
    vp,
    output_path,
    width_inch=3.3,
    height_inch=3.3,
    dpi=600,
    frame_index=-1,
    antialiasing_level=8,
    enable_shadows=False,
    background=(1.0, 1.0, 1.0),
    debug=False,
):
    """Render an OVITO viewport to a target physical size with DPI metadata."""
    width_px, height_px = _resolve_render_size(width_inch=width_inch, height_inch=height_inch, dpi=dpi)

    renderer = TachyonRenderer()
    renderer.ambient_occlusion = False  # faster, consistent with simple batch renders
    aa_samples = max(int(antialiasing_level), 1)
    if hasattr(renderer, "antialiasing"):
        renderer.antialiasing = aa_samples > 1
    if hasattr(renderer, "antialiasing_samples"):
        renderer.antialiasing_samples = aa_samples
    if hasattr(renderer, "shadows"):
        renderer.shadows = bool(enable_shadows)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    vp.render_image(
        filename=str(output_path),
        size=(width_px, height_px),
        frame=frame_index,
        renderer=renderer,
        background=background,
    )
    _embed_png_dpi(output_path, int(dpi), debug=debug)

    if debug:
        print(
            f"Rendered {float(width_inch):.3f}\" x {float(height_inch):.3f}\" "
            f"image at {int(dpi)} DPI ({width_px}x{height_px} pixels, "
            f"aa_samples={aa_samples}, shadows={bool(enable_shadows)})."
        )


def _set_simulation_cell_visibility(pipeline, cell, show_boundary, debug=False):
    show_boundary = bool(show_boundary)
    source_data = getattr(getattr(pipeline, "source", None), "data", None)
    if source_data is not None and hasattr(source_data, "cell") and hasattr(source_data.cell, "vis"):
        cell_vis = source_data.cell.vis
    elif hasattr(cell, "vis"):
        cell_vis = cell.vis
    else:
        if debug:
            print("visualize_gsd: could not access simulation cell vis object; boundary visibility unchanged.")
        return

    if hasattr(cell_vis, "render_cell"):
        cell_vis.render_cell = show_boundary
    elif hasattr(cell_vis, "enabled"):
        cell_vis.enabled = show_boundary

    if debug:
        print(f"visualize_gsd: boundary visibility set to {show_boundary}")


def visualize_gsd(
    gsd_path,
    output_path=None,
    frame_index=-1,
    width_inch=3.3,
    height_inch=3.3,
    dpi=600,
    preview=False,
    debug=False,
    show_boundary=True,
    antialiasing_level=8,
    enable_shadows=False,
    **kwargs,
):
    """
    Render a GSD file using OVITO.

    Parameters
    ----------
    gsd_path : str or Path
        Path to the GSD file.
    output_path : str or Path, optional
        If provided, save a PNG render at this path.
    frame_index : int, optional
        Frame index to render (default: -1, last frame).
    width_inch : float, optional
        Physical output width in inches.
    height_inch : float, optional
        Physical output height in inches.
    dpi : int, optional
        DPI metadata and pixel conversion used with width_inch/height_inch.
    preview : bool, optional
        No-op for headless Ovito, but kept for API compatibility.
    debug : bool, optional
        Print debug information.
    show_boundary : bool, optional
        Whether to show the simulation box (default: True).
    enable_shadows : bool, optional
        Whether to enable cast shadows in the Tachyon renderer (default: False).
    **kwargs : dict
        Additional arguments ignored (compatibility with fresnel version).
    """

    gsd_path = Path(gsd_path)
    if not gsd_path.exists():
        raise FileNotFoundError(f"GSD file not found: {gsd_path}")

    # Load the particle data
    pipeline = import_file(str(gsd_path))

    # Resolve frame index
    num_frames = pipeline.source.num_frames
    if frame_index < 0:
        frame_index = num_frames + frame_index

    if frame_index < 0 or frame_index >= num_frames:
        raise ValueError(f"Frame index {frame_index} out of range (0-{num_frames-1})")

    if debug:
        print(f"visualize_gsd: loading {gsd_path}, frame {frame_index}/{num_frames}")

    if "shadows" in kwargs:
        enable_shadows = bool(kwargs.pop("shadows"))

    # Add to scene to visualize
    pipeline.add_to_scene()

    # Define a modifier to set custom colors (skipping the first silver color)
    def assign_colors(frame, data):
        if 'Particle Type' in data.particles:
            type_prop = data.particles['Particle Type']
            colors = [
                (0.12, 0.47, 0.71),  # Blue
                (1.0, 0.50, 0.05),   # Orange
                (0.17, 0.63, 0.17),  # Green
                (0.84, 0.15, 0.16),  # Red
                (0.58, 0.40, 0.74),  # Purple
                (0.55, 0.34, 0.29),  # Brown
                (0.89, 0.47, 0.76),  # Pink
                (0.50, 0.50, 0.50),  # Gray
                (0.74, 0.74, 0.13),  # Yellow
                (0.09, 0.75, 0.81),  # Cyan
            ]

            # Get type indices
            ptypes = np.array(type_prop)

            # Map types to colors
            # Use modulo to cycle through colors if there are more types than colors
            # We map the type ID directly to a color index
            color_indices = ptypes % len(colors)
            color_data = np.array(colors)[color_indices]

            # Create 'Color' property which overrides type colors
            # Using create_property is valid on the data object passed to modifier
            data.particles_.create_property('Color', data=color_data)

    pipeline.modifiers.append(assign_colors)

    # Evaluate at the requested frame to inspect data (e.g. for dimensions)
    data = pipeline.compute(frame_index)

    # Determine dimensionality based on cell

    # Determine dimensionality based on cell
    # Typically 2D sims have 0 length in Z or specific flags.
    # We can check data.cell.is_2D if available or check matrix
    cell = data.cell
    is_2d = False
    if hasattr(cell, "is2D") and cell.is2D:
        is_2d = True
    elif cell.matrix[2, 2] == 0:  # Flat box
        is_2d = True

    if debug:
        print(f"visualize_gsd: detected 2D={is_2d}")

    _set_simulation_cell_visibility(pipeline, cell=cell, show_boundary=show_boundary, debug=debug)

    render_width_px, render_height_px = _resolve_render_size(width_inch=width_inch, height_inch=height_inch, dpi=dpi)
    aspect_ratio = render_width_px / max(render_height_px, 1)

    # Set up viewport from the simulation box instead of particle extents so
    # different shapes with the same box dimensions occupy the same image area.
    vp = Viewport()
    _configure_viewport_from_box(vp, cell=cell, is_2d=is_2d, aspect_ratio=aspect_ratio, debug=debug)

    # Add a modifier to rotate particles for visualization if they are 2D capsules being rendered as Z-capsules
    # But we can't easily detect this mismatch generically without inspecting shapes.
    # However, forcing a rotation on the pipeline for visualization can align X-capsules (if rendered as Z) to X.
    # But let's avoid hacking visualizer unless requested. The issue is likely Ovito version or GSD compliance.

    # Create renderer
    # OpenGLRenderer gives the "standard" Ovito look (smooth, fast)
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if debug:
            print(f"visualize_gsd: rendering to {output_path}")

        render_physical_size(
            vp,
            output_path=output_path,
            width_inch=width_inch,
            height_inch=height_inch,
            dpi=dpi,
            frame_index=frame_index,
            antialiasing_level=antialiasing_level,
            enable_shadows=enable_shadows,
            background=(1.0, 1.0, 1.0),
            debug=debug,
        )

    if preview:
        print("Note: Ovito 'preview' not supported in headless usage. Check output file.")

    # Remove from scene to clean up if called correctly in loop, though usually fine in script
    pipeline.remove_from_scene()

    return pipeline
