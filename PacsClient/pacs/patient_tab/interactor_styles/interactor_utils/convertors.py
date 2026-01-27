import numpy as np
from typing import List, Sequence, Tuple, Optional


def build_payload_ijk(server_config, ijk_list_3d):
    """Build the canonical IJK-3D payload (no 'slice' field)."""

    params = {
        "coord_system": "IJK",
        "points": [[float(i), float(j), float(k)] for (i, j, k) in ijk_list_3d],
        "name": server_config.get("DEFAULT_SEG_NAME") or "poly_seg",
    }
    print(f'\n\n\nserver config: \n{server_config}\n\n\n')

    if server_config.get("DEFAULT_OUT_DIR"):
        params["out_dir"] = server_config["DEFAULT_OUT_DIR"]
    if server_config.get("SERIES_UID"):
        params["series_uid"] = server_config["SERIES_UID"]
    if server_config.get("SERIES_INDEX") is not None:
        params["series_index"] = int(server_config["SERIES_INDEX"])
    if server_config.get("SERIES_RULE"):
        params["series_rule"] = str(server_config["SERIES_RULE"])
    if server_config.get("DEBUG_SEG"):
        params["debug"] = True

    payload = {
        "action": "segment_polygon",
        "params": params,
    }
    if server_config.get("STUDY_UID"):
        payload["study_uid"] = server_config["STUDY_UID"]
    elif server_config.get("DICOM_FOLDER"):
        payload["dicom_folder"] = server_config["DICOM_FOLDER"]
    else:
        raise ValueError("Neither STUDY_UID nor DICOM_FOLDER is set.")

    print(f'\n\n\npayload: {payload}\n\n\n')
    return payload


def get_world_points(points, rep):
    pts_world_out = []
    for i in range(points):
        pos = [0.0, 0.0, 0.0]
        rep.GetNthNodeWorldPosition(i, pos)
        pts_world_out.append([float(pos[0]), float(pos[1]), float(pos[2])])
    return pts_world_out


def world_to_ijk_vtk(vtk_image, world_pt3):
    ox, oy, oz = vtk_image.GetOrigin()
    sx, sy, sz = vtk_image.GetSpacing()
    # print(f'oz: {oz}\nsz: {sz}')
    O = np.array([ox, oy, oz], float)
    S = np.array([sx, sy, sz], float)
    # print(f'O: {O}\nS: {S}\n')

    # Direction (VTK 9): 3x3
    Dm = vtk_image.GetDirectionMatrix() if hasattr(vtk_image, "GetDirectionMatrix") else None
    if Dm is not None:
        D = np.array([Dm.GetElement(r, c) for r in range(3) for c in range(3)], float).reshape(3, 3)
    else:
        D = np.eye(3)

    A = D @ np.diag(S)
    ijk_cont = np.linalg.inv(A) @ (np.array(world_pt3, float) - O)
    # print(f'ijk_cont on world to itj vtk function: {ijk_cont}')
    return ijk_cont


def rect_from_quad_by_longest_diagonal(
    points: List[Sequence[float]],
    image_size: Optional[Tuple[float, float]] = None,  # (W, H), optional clamp
    margin: float = 0.0,          # outward padding in pixels
    keep_z: str = "first",        # "first" | "mean" | "none"
    round_to_int: bool = False,   # round final coords to integers
) -> List[List[float]]:
    """
    Build an axis-aligned rectangle using the longer diagonal of a quadrilateral.

    Assumptions:
        - `points` has exactly 4 vertices in polygon order (CW or CCW).
        - The two diagonals are (p0,p2) and (p1,p3). We pick the longer one.
        - The rectangle is axis-aligned; the chosen diagonal endpoints become
          opposite corners of the rectangle. No guarantee to cover all 4 vertices.

    Returns:
        Corners in order:
            [ [xmin, ymin, (z?)],
              [xmax, ymin, (z?)],
              [xmax, ymax, (z?)],
              [xmin, ymax, (z?)] ]
        If `keep_z="none"` or input has no z, corners are 2D [x, y].
        Otherwise corners are 3D [x, y, z].
    """
    if len(points) != 4:
        raise ValueError("points must contain exactly 4 vertices (quadrilateral).")
    if len(points[0]) < 2:
        raise ValueError("each point must be [x, y] or [x, y, z].")

    # Unpack points
    p0, p1, p2, p3 = points

    def sqr_dist(a, b):
        dx, dy = (a[0] - b[0]), (a[1] - b[1])
        return dx*dx + dy*dy

    # Pick the longer diagonal: (p0,p2) vs (p1,p3)
    d02 = sqr_dist(p0, p2)
    d13 = sqr_dist(p1, p3)
    A, C = (p0, p2) if d02 >= d13 else (p1, p3)  # A and C are opposite corners

    # Build axis-aligned rectangle from A and C (opposite corners)
    xmin, xmax = (A[0], C[0]) if A[0] <= C[0] else (C[0], A[0])
    ymin, ymax = (A[1], C[1]) if A[1] <= C[1] else (C[1], A[1])

    # Apply optional margin (outward)
    xmin, xmax = xmin - margin, xmax + margin
    ymin, ymax = ymin - margin, ymax + margin

    # Optional clamp to image bounds
    if image_size is not None:
        W, H = image_size
        xmin = max(0.0, min(xmin, W - 1))
        xmax = max(0.0, min(xmax, W - 1))
        ymin = max(0.0, min(ymin, H - 1))
        ymax = max(0.0, min(ymax, H - 1))

    # z handling
    has_z = len(points[0]) > 2
    if has_z and keep_z in ("first", "mean"):
        if keep_z == "first":
            z_val = float(points[0][2])
        else:
            z_val = sum(float(p[2]) for p in points) / float(len(points))
    else:
        z_val = None

    # Corners (2D or 3D)
    if z_val is None:
        corners = [
            [xmin, ymin],
            [xmax, ymin],
            [xmax, ymax],
            [xmin, ymax],
        ]
    else:
        corners = [
            [xmin, ymin, z_val],
            [xmax, ymin, z_val],
            [xmax, ymax, z_val],
            [xmin, ymax, z_val],
        ]

    # Optional integer rounding
    if round_to_int:
        out = []
        for c in corners:
            if len(c) == 2:
                out.append([int(round(c[0])), int(round(c[1]))])
            else:
                out.append([int(round(c[0])), int(round(c[1])), int(round(c[2]))])
        corners = out

    return corners


def bbox_corners_to_xywh(corners: List[List[float]]) -> Tuple[float, float, float, float]:
    """
    Convert corners (xmin/ymin → xmax/ymax order) to (x, y, w, h).
    """
    if len(corners) != 4:
        raise ValueError("corners must have length 4")
    xmin, ymin = float(corners[0][0]), float(corners[0][1])
    xmax, ymax = float(corners[2][0]), float(corners[2][1])
    return xmin, ymin, (xmax - xmin), (ymax - ymin)




# points = [
#     [139.34217687074837, 175.04285714285717, 3.0],
#     [184.6210884353742, 175.39115646258506, 3.0],
#     [188.8006802721089, 134.9884353741497, 3.0],
#     [139.34217687074837, 135.68503401360545, 3.0],
#     [139.34217687074837, 175.04285714285717, 3.0],  # closing duplicate
# ]
#
# bbox = axis_aligned_bbox_from_polygon(points, image_size=None, margin=0.0, keep_z="first", round_to_int=False)
# bbox_int = axis_aligned_bbox_from_polygon(points, image_size=None, margin=0.0, keep_z="first", round_to_int=True)
