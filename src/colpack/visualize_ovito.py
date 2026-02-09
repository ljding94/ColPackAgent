import os
from pathlib import Path
from ovito.io import import_file
from ovito.vis import Viewport, OpenGLRenderer

def visualize_gsd(
    gsd_path,
    output_path=None,
    frame_index=-1,
    width=1000,
    height=1000,
    preview=False,
    debug=False,
    show_boundary=True,
    **kwargs
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
    width : int, optional
        Output image width in pixels.
    height : int, optional
        Output image height in pixels.
    preview : bool, optional
        No-op for headless Ovito, but kept for API compatibility.
    debug : bool, optional
        Print debug information.
    show_boundary : bool, optional
        Whether to show the simulation box (default: True).
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

    # Add to scene to visualize
    pipeline.add_to_scene()

    # Evaluate at the requested frame to inspect data (e.g. for dimensions)
    data = pipeline.compute(frame_index)

    # Determine dimensionality based on cell
    # Typically 2D sims have 0 length in Z or specific flags.
    # We can check data.cell.is_2D if available or check matrix
    cell = data.cell
    is_2d = False
    if hasattr(cell, 'is2D') and cell.is2D:
        is_2d = True
    elif cell.matrix[2,2] == 0: # Flat box
        is_2d = True

    if debug:
        print(f"visualize_gsd: detected 2D={is_2d}")

    # Set up viewport
    vp = Viewport()
    if is_2d:
        vp.type = Viewport.Type.Top
    else:
        vp.type = Viewport.Type.Ortho

    # Configure camera
    vp.zoom_all()

    # Add a modifier to rotate particles for visualization if they are 2D capsules being rendered as Z-capsules
    # But we can't easily detect this mismatch generically without inspecting shapes.
    # However, forcing a rotation on the pipeline for visualization can align X-capsules (if rendered as Z) to X.
    # But let's avoid hacking visualizer unless requested. The issue is likely Ovito version or GSD compliance.

    # Create renderer
    # OpenGLRenderer gives the "standard" Ovito look (smooth, fast)
    renderer = OpenGLRenderer()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if debug:
            print(f"visualize_gsd: rendering to {output_path}")

        vp.render_image(
            filename=str(output_path),
            size=(width, height),
            frame=frame_index,
            renderer=renderer,
            background=(1.0, 1.0, 1.0)  # White background
        )

    if preview:
        print("Note: Ovito 'preview' not supported in headless usage. Check output file.")

    # Remove from scene to clean up if called correctly in loop, though usually fine in script
    pipeline.remove_from_scene()

    return pipeline
