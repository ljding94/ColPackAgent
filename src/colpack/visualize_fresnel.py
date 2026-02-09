import json
from pathlib import Path
import gsd.hoomd
import numpy as np

try:
    import fresnel
    import scipy.spatial
    from scipy.spatial.transform import Rotation
except ImportError:
    # Handle cases where visualization dependencies might be missing in some environments
    fresnel = None
    scipy = None
    Rotation = None


def _create_ellipsoid_polyhedron(a, b, c, num_points=150):
    """Generate polyhedron data for an ellipsoid with semi-axes a, b, c."""
    indices = np.arange(0, num_points, dtype=float) + 0.5
    phi = np.arccos(1 - 2 * indices / num_points)
    theta = np.pi * (1 + 5**0.5) * indices

    x = np.cos(theta) * np.sin(phi)
    y = np.sin(theta) * np.sin(phi)
    z = np.cos(phi)

    verts = np.column_stack((x * a, y * b, z * c))
    return verts


def render(
    frame,
    output_path=None,
    width=1000,
    height=1000,
    light_samples=None,
    high_quality=False,
    preview=False,
    debug=False,
    show_boundary=True,
):
    """
    Render a GSD frame using Fresnel.

    Parameters
    ----------
    frame : gsd.hoomd.Frame
        The frame to render.
    output_path : str or Path, optional
        If provided, save a PNG render at this path.
    width : int, optional
        Output image width in pixels.
    height : int, optional
        Output image height in pixels.
    light_samples : int, optional
        Number of light samples for path tracing.
    high_quality : bool, optional
        Use higher quality rendering settings.
    preview : bool, optional
        If True, call fresnel.preview(scene).
    debug : bool, optional
        Print debug info.
    show_boundary : bool, optional
        Show simulation box.
    """

    dimensions = getattr(frame.configuration, "dimensions", 3)

    if dimensions == 2:
        return render2d(
            frame=frame,
            output_path=output_path,
            width=width,
            height=height,
            light_samples=light_samples,
            high_quality=high_quality,
            preview=preview,
            debug=debug,
            show_boundary=show_boundary,
        )
    elif dimensions == 3:
        return render3d(
            frame=frame,
            output_path=output_path,
            width=width,
            height=height,
            light_samples=light_samples,
            high_quality=high_quality,
            preview=preview,
            debug=debug,
            show_boundary=show_boundary,
        )
    else:
        raise ValueError(f"Unsupported system dimensionality: {dimensions}")


def render2d(
    frame,
    output_path=None,
    width=1000,
    height=1000,
    light_samples=None,
    high_quality=False,
    preview=False,
    debug=False,
    show_boundary=True,
):
    try:
        import fresnel
    except ImportError as exc:
        raise ImportError("fresnel is required for visualization.") from exc

    try:
        import scipy.spatial
    except ImportError as exc:
        raise ImportError("scipy is required to compute convex hulls for polyhedra.") from exc

    if light_samples is None:
        light_samples = 64 if high_quality else 8

    scene = fresnel.Scene()

    type_shapes = list(frame.particles.type_shapes)
    type_ids = frame.particles.typeid
    if len(type_shapes) < len(frame.particles.types):
        missing = len(frame.particles.types) - len(type_shapes)
        type_shapes.extend([{}] * missing)

    palette = [
        [0.95, 0.5, 0.5],
        [0.5, 0.5, 0.95],
        [0.5, 0.85, 0.5],
        [0.9, 0.7, 0.3],
        [0.75, 0.5, 0.85],
    ]

    for type_id, json_string in enumerate(type_shapes):
        if isinstance(json_string, (str, bytes, bytearray)):
            shape_spec = json.loads(json_string)
        elif isinstance(json_string, dict):
            shape_spec = json_string.copy()
        else:
            continue

        ids = np.where(type_ids == type_id)[0]
        if len(ids) == 0:
            continue

        shape_class = shape_spec.get("type", "Sphere") # Default fallback

        geometry = None

        if shape_class == "Sphere":
            # In 2D, Sphere is a Disk
            # Use Sphere geometry. In orthographic 2D with solid=1.0, this looks exactly like a flat disk.
            diameter = shape_spec.get("diameter", 1.0)
            geometry = fresnel.geometry.Sphere(scene, N=len(ids), radius=diameter / 2)
            geometry.position[:] = frame.particles.position[ids]

            # Use explicit color for Spheres, just like Mesh/Cylinder end-caps
            geometry.color[:] = fresnel.color.linear(palette[type_id % len(palette)])
            geometry.material = fresnel.material.Material(
                roughness=0.5,
                specular=0.5,
                solid=1.0,
                primitive_color_mix=1.0,
            )

        elif shape_class == "Ellipsoid":
            a = shape_spec.get("a", 0.5)
            b = shape_spec.get("b", 0.5)
            # 2D Ellipsoid -> Triangulated Mesh (Flat Disk)
            N_pts = 64
            theta = np.linspace(0, 2 * np.pi, N_pts, endpoint=False)
            x = a * np.cos(theta)
            y = b * np.sin(theta)

            # Generate triangle soup for the ellipse
            # Center point
            center = np.array([0.0, 0.0, 0.0])
            perimeter = np.column_stack((x, y, np.zeros_like(x)))

            vertices = []
            for i in range(N_pts):
                # Triangle: Center -> P_i -> P_{i+1}
                p1 = perimeter[i]
                p2 = perimeter[(i + 1) % N_pts]
                vertices.extend([center, p1, p2])

            vertices = np.array(vertices)

            geometry = fresnel.geometry.Mesh(scene, vertices=vertices, N=len(ids))
            geometry.position[:] = frame.particles.position[ids]
            geometry.orientation[:] = frame.particles.orientation[ids]

        elif shape_class in {"ConvexSpheropolygon", "Polygon"}:
            verts = np.array(shape_spec.get("vertices", []))
            sweep_radius = float(shape_spec.get("sweep_radius", 0.0))

            # Handle special cases (disk, stadium)
            if len(verts) == 1: # Disk
                # FIX: Use Sphere instead of Cylinder for 1-vertex Spheropolygon (Disk)
                geometry = fresnel.geometry.Sphere(scene, N=len(ids), radius=sweep_radius)
                geometry.position[:] = frame.particles.position[ids]

                geometry.color[:] = fresnel.color.linear(palette[type_id % len(palette)])
                geometry.material = fresnel.material.Material(
                    roughness=0.5,
                    specular=0.5,
                    solid=1.0,
                    primitive_color_mix=1.0,
                )
            elif len(verts) == 2: # Stadium/Capsule 2D
                # Vertices are local 2D (x,y)
                p1_local = np.array([verts[0][0], verts[0][1], 0.0])
                p2_local = np.array([verts[1][0], verts[1][1], 0.0])

                orientations = frame.particles.orientation[ids] # [s, x, y, z]
                positions = frame.particles.position[ids]

                # Transform to quaternion [x, y, z, w] for scipy
                quat_scipy = orientations[:, [1, 2, 3, 0]]
                r = Rotation.from_quat(quat_scipy)

                v1_rot = r.apply(np.tile(p1_local, (len(ids), 1)))
                v2_rot = r.apply(np.tile(p2_local, (len(ids), 1)))

                p1_world = positions + v1_rot
                p2_world = positions + v2_rot

                geometry = fresnel.geometry.Cylinder(scene, N=len(ids))
                geometry.points[:] = np.stack((p1_world, p2_world), axis=1)
                geometry.radius[:] = sweep_radius

                # End caps
                spheres = fresnel.geometry.Sphere(scene, N=2*len(ids), radius=sweep_radius)
                spheres.position[:] = np.vstack((p1_world, p2_world))

                spheres.color[:] = fresnel.color.linear(palette[type_id % len(palette)])
                spheres.material = fresnel.material.Material(
                    roughness=0.5,
                    specular=0.5,
                    solid=1.0,
                    primitive_color_mix=1.0,
                )
            else:
                # General Polygon -> Triangulated Mesh
                # Spheropolygons with sweep_radius > 0 are tricky in 2D meshes without manual triangulation of the ease.
                # For basic polygons (rectangles, triangles), we can just triangulate the face.

                # Simple fan triangulation for convex polygons
                # Center point
                center = np.mean(verts, axis=0)
                center_3d = np.array([center[0], center[1], 0.0])

                vertices = []
                N_verts = len(verts)
                for i in range(N_verts):
                     # Triangle: Center -> P_i -> P_{i+1}
                     p1 = verts[i]
                     p2 = verts[(i + 1) % N_verts]
                     vertices.extend([center_3d, [p1[0], p1[1], 0.0], [p2[0], p2[1], 0.0]])

                vertices = np.array(vertices)

                # If there's a sweep radius (Spheropolygon), rendering just the polygon mesh is an approximation.
                # But for 2D diagram purposes, it's usually acceptable if sweep is small.
                # If sweep is large, we might want to fall back to Cylinder+Sphere caps or a more complex mesh.

                geometry = fresnel.geometry.Mesh(scene, vertices=vertices, N=len(ids))
                geometry.position[:] = frame.particles.position[ids]
                geometry.orientation[:] = frame.particles.orientation[ids]

        if geometry:
            geometry.color[:] = fresnel.color.linear(palette[type_id % len(palette)])
            geometry.material = fresnel.material.Material(
                roughness=0.5,
                specular=0.5,
                solid=1.0,
                primitive_color_mix=1.0,
            )

    # 2D Camera
    if frame.configuration.box is not None:
        box = frame.configuration.box
        Lx, Ly = box[0], box[1]
        span = max(Lx, Ly) * 1.1
        camera = fresnel.camera.Orthographic(
            position=(0, 0, 100),
            look_at=(0, 0, 0),
            up=(0, 1, 0),
            height=span,
        )
        scene.camera = camera
    else:
        scene.camera = fresnel.camera.Orthographic.fit(scene)

    if show_boundary and hasattr(fresnel.geometry, "Box") and frame.configuration.box is not None:
        boundary = fresnel.geometry.Box(scene, box=frame.configuration.box, box_radius=0.02)
        boundary.material = fresnel.material.Material(
            color=fresnel.color.linear([0, 0, 0]),
            solid=1.0
        )

    if output_path:
        try:
            from PIL import Image
        except ImportError:
            pass
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image = fresnel.pathtrace(scene, w=width, h=height, light_samples=light_samples)
            Image.fromarray(image[:]).save(output_path)

    return scene


def render3d(
    frame,
    output_path=None,
    width=1000,
    height=1000,
    light_samples=None,
    high_quality=False,
    preview=False,
    debug=False,
    show_boundary=True,
):
    try:
        import fresnel
    except ImportError as exc:
        raise ImportError("fresnel is required for visualization.") from exc

    try:
        import scipy.spatial
    except ImportError as exc:
        raise ImportError("scipy is required to compute convex hulls for polyhedra.") from exc

    if light_samples is None:
        light_samples = 64 if high_quality else 8

    scene = fresnel.Scene()

    type_shapes = list(frame.particles.type_shapes)
    type_ids = frame.particles.typeid
    if len(type_shapes) < len(frame.particles.types):
        missing = len(frame.particles.types) - len(type_shapes)
        type_shapes.extend([{}] * missing)

    palette = [
        [0.95, 0.5, 0.5],
        [0.5, 0.5, 0.95],
        [0.5, 0.85, 0.5],
        [0.9, 0.7, 0.3],
        [0.75, 0.5, 0.85],
    ]

    for type_id, json_string in enumerate(type_shapes):
        if isinstance(json_string, (str, bytes, bytearray)):
            shape_spec = json.loads(json_string)
        elif isinstance(json_string, dict):
            shape_spec = json_string.copy()
        else:
            continue

        ids = np.where(type_ids == type_id)[0]
        if len(ids) == 0:
            continue

        shape_class = shape_spec.get("type", "Sphere")
        geometry = None

        if shape_class == "Sphere":
            diameter = shape_spec.get("diameter", 1.0)
            geometry = fresnel.geometry.Sphere(scene, N=len(ids), radius=diameter / 2)
            geometry.position[:] = frame.particles.position[ids]
            geometry.color[:] = fresnel.color.linear(palette[type_id % len(palette)])

        elif shape_class == "Ellipsoid":
            a = shape_spec.get("a", 0.5)
            b = shape_spec.get("b", 0.5)
            c = shape_spec.get("c", 0.5)
            verts = _create_ellipsoid_polyhedron(a, b, c, num_points=150 if high_quality else 80)

            hull = scipy.spatial.ConvexHull(verts)
            p_color = palette[type_id % len(palette)]

            poly_info = {
                "face_origin": -hull.equations[:, 3][:, np.newaxis] * hull.equations[:, 0:3],
                "face_normal": hull.equations[:, 0:3],
                "face_color": np.full((len(hull.equations), 3), p_color),
                "vertices": verts,
                "radius": np.max(np.linalg.norm(verts, axis=1)),
            }
            geometry = fresnel.geometry.ConvexPolyhedron(scene, poly_info, N=len(ids))
            geometry.position[:] = frame.particles.position[ids]
            geometry.orientation[:] = frame.particles.orientation[ids]
            geometry.color[:] = fresnel.color.linear(palette[type_id % len(palette)])

        elif shape_class in {"ConvexSpheropolyhedron", "ConvexPolyhedron"}:
            verts = np.array(shape_spec.get("vertices", []))
            sweep_radius = float(shape_spec.get("sweep_radius", 0.0))

            p_color = palette[type_id % len(palette)]

            if len(verts) == 1:
                # Sphere (1 vertex)
                # Effectively a sphere with radius = sweep_radius
                geometry = fresnel.geometry.Sphere(scene, N=len(ids), radius=sweep_radius)
                geometry.position[:] = frame.particles.position[ids]
                geometry.color[:] = fresnel.color.linear(p_color)

            elif len(verts) == 2:
                # 3D Capsule
                p1_local = verts[0]
                p2_local = verts[1]
                vec = p2_local - p1_local
                length = np.linalg.norm(vec)

                positions = frame.particles.position[ids]
                orientations = frame.particles.orientation[ids] # [s, x, y, z]

                if length > 1e-6:
                    quat_scipy = orientations[:, [1, 2, 3, 0]]
                    r = Rotation.from_quat(quat_scipy)

                    v1_rot = r.apply(np.tile(p1_local, (len(ids), 1)))
                    v2_rot = r.apply(np.tile(p2_local, (len(ids), 1)))

                    p1_world = positions + v1_rot
                    p2_world = positions + v2_rot

                    # 1. Cylinder
                    cyl = fresnel.geometry.Cylinder(scene, N=len(ids))
                    cyl.points[:] = np.stack((p1_world, p2_world), axis=1)
                    cyl.radius[:] = sweep_radius
                    cyl.color[:] = fresnel.color.linear(p_color)
                    cyl.material = fresnel.material.Material(
                        roughness=0.5,
                        specular=0.5,
                        primitive_color_mix=1.0
                    )

                    # 2. End caps
                    sph = fresnel.geometry.Sphere(scene, N=2*len(ids), radius=sweep_radius)
                    sph.position[:] = np.vstack((p1_world, p2_world))
                    sph.color[:] = fresnel.color.linear(p_color)
                    sph.material = cyl.material

                    # We manually handled materials, so continue
                    continue # IMPORTANT: Skip generic material assignment
                else:
                    # Degenerate
                    geometry = fresnel.geometry.Sphere(scene, N=len(ids), radius=sweep_radius)
                    geometry.position[:] = positions
                    geometry.color[:] = fresnel.color.linear(p_color)
            else:
                # General Polyhedron (Tetrahedron, Cube, etc.)
                if debug:
                    print(f"render3d: Processing Polyhedron type {type_id} with {len(verts)} verts, N={len(ids)}, radius={sweep_radius}")

                # We still need ConvexHull to get the triangulation (connectivity) of the vertices
                hull = scipy.spatial.ConvexHull(verts)

                # hull.simplices contains the integer indices of vertices forming each triangle
                # We create a flat list of vertices for the mesh: (N_triangles * 3, 3)
                mesh_verts = verts[hull.simplices].reshape(-1, 3)

                geometry = fresnel.geometry.Mesh(scene, vertices=mesh_verts, N=len(ids))
                geometry.position[:] = frame.particles.position[ids]
                geometry.orientation[:] = frame.particles.orientation[ids]
                geometry.color[:] = fresnel.color.linear(p_color)

        if geometry:
            def_color = palette[type_id % len(palette)]
            # Check if geometry has color attribute and if it's not set
            # (Though in logic above we tried to set it for most cases)
            # Actually for ConvexPolyhedron, face_color handles it.
            # For Sphere, we set geometry.color.

            # We enforce primitive_color_mix=1.0 for everyone to use the explicit colors (face or vertex/geometry)
            geometry.material = fresnel.material.Material(
                roughness=0.5,
                specular=0.5,
                primitive_color_mix=1.0,
            )

    if show_boundary and hasattr(fresnel.geometry, "Box"):
        boundary = fresnel.geometry.Box(scene, box=frame.configuration.box, box_radius=0.02)
        boundary.material = fresnel.material.Material(
            color=fresnel.color.linear([0.6, 0.6, 0.6]),
            roughness=1.0,
            specular=0.0,
        )

    # 3D Camera
    if frame.configuration.box is not None:
        box = frame.configuration.box
        Lx, Ly, Lz = box[0], box[1], box[2]
        diagonal = np.sqrt(Lx**2 + Ly**2 + Lz**2)
        # Move camera further away to prevent near-plane clipping
        dist = max(Lx, Ly, Lz) * 2.0
        camera = fresnel.camera.Orthographic(
            position=(dist, dist, dist * 0.5),
            look_at=(0, 0, 0),
            up=(0, 0, 1),
            # Increase height to ensure full box visibility including rotations
            height=diagonal * 1.1,
        )
        scene.camera = camera
    else:
        scene.camera = fresnel.camera.Orthographic.fit(scene)

    if preview:
        fresnel.preview(scene)

    if output_path:
        try:
            from PIL import Image
        except ImportError:
            pass
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image = fresnel.pathtrace(scene, w=width, h=height, light_samples=light_samples)
            Image.fromarray(image[:]).save(output_path)

    return scene


def visualize_gsd(
    gsd_path,
    output_path=None,
    frame_index=-1,
    width=1000,
    height=1000,
    light_samples=None,
    high_quality=False,
    preview=False,
    debug=False,
    show_boundary=True,
):
    """
    Render a GSD file using Fresnel while preserving shape information from
    frame.particles.type_shapes.

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
    light_samples : int, optional
            Number of light samples for path tracing.
    preview : bool, optional
            If True, call fresnel.preview(scene) for interactive viewing.
    """

    gsd_path = Path(gsd_path)
    if not gsd_path.exists():
        raise FileNotFoundError(f"GSD file not found: {gsd_path}")

    traj = gsd.hoomd.open(str(gsd_path), mode="r")
    frame = traj[frame_index]

    if debug:
        print(f"visualize_gsd: loading {gsd_path}, frame {frame_index}")

    return render(frame=frame, output_path=output_path, width=width, height=height, light_samples=light_samples, high_quality=high_quality, preview=preview, debug=debug, show_boundary=show_boundary)
