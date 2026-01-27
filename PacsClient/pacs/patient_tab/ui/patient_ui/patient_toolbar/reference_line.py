import vtkmodules.all as vtk
import numpy as np


def rl_eps() -> float:
    """Small epsilon used for robust floating point comparisons."""
    return 1e-7


def rl_clip_plane_with_quad(p_plane, n_plane, quad_pts):
    """
    Intersect a plane with a convex quad (slice rectangle).
    Returns (True, (P0, P1)) for a segment, or (False, (None, None)) if no proper segment exists.
    """
    EPS = rl_eps()

    def _intersect(p, n, a, b):
        ab = b - a
        denom = np.dot(n, ab)
        if abs(denom) < EPS:
            return False, None  # parallel to the plane
        t = np.dot(n, (p - a)) / denom
        if t < -EPS or t > 1.0 + EPS:
            return False, None  # outside segment
        return True, a + t * ab

    hits = []
    for i in range(4):
        ok, x = _intersect(p_plane, n_plane, quad_pts[i], quad_pts[(i + 1) % 4])
        if ok and not any(np.linalg.norm(x - h) < 1e-4 for h in hits):
            hits.append(x)

    if len(hits) >= 2:
        return True, (hits[0], hits[1])
    return False, (None, None)


def rl_quad_corners_lps(rows, cols, pos_lps, row_dir, col_dir, sy, sx):
    """
    Return 4 LPS points (voxel centers) for the target slice quad:
    order = [p00, p10, p11, p01]
    """
    p00 = pos_lps
    p10 = pos_lps + (cols - 1) * sx * col_dir
    p01 = pos_lps + (rows - 1) * sy * row_dir
    p11 = p10 + (rows - 1) * sy * row_dir
    return [np.asarray(p00, float), np.asarray(p10, float),
            np.asarray(p11, float), np.asarray(p01, float)]


def rl_center_of_slice(rows, cols, pos_lps, row_dir, col_dir, sy, sx):
    """Slice-quad geometric center in LPS (used as pivot for in-plane transforms)."""
    return pos_lps + 0.5 * ((cols - 1) * sx * col_dir + (rows - 1) * sy * row_dir)


def rl_rotate_ccw_90_in_plane(P, C, col_dir, row_dir):
    """
    Rotate point P around center C by +90° (counter-clockwise) within the slice plane.
    Basis: (col_dir, row_dir); (a, b) -> (-b, a)
    """
    d = P - C
    a = float(np.dot(d, col_dir))
    b = float(np.dot(d, row_dir))
    return C + (-b) * col_dir + (a) * row_dir


def rl_apply_flip_y_in_plane(P, C, col_dir, row_dir):
    """
    Mirror within the slice plane along the row axis (equivalent to Flip-Y):
    (a, b) -> (a, -b)
    """
    d = P - C
    a = float(np.dot(d, col_dir))
    b = float(np.dot(d, row_dir))
    return C + (a) * col_dir + (-b) * row_dir


def rl_apply_flip_x_in_plane(P, C, col_dir, row_dir):
    """
    Mirror within the slice plane along the column axis (Flip-X; mirror w.r.t. the YZ plane):
    (a, b) -> (-a, b)
    """
    d = P - C
    a = float(np.dot(d, col_dir))
    b = float(np.dot(d, row_dir))
    return C + (-a) * col_dir + (b) * row_dir


def rl_lps_to_target_index(P_lps, pos2, col2, row2, sx, sy, t_slice):
    """
    Map an LPS point on the target slice plane to target index space (i, j, k=t_slice).
    """
    d = P_lps - pos2
    i = float(np.dot(d, col2) / (sx if sx != 0 else 1.0))
    j = float(np.dot(d, row2) / (sy if sy != 0 else 1.0))
    return np.array([i, j, float(t_slice)], dtype=float)


def rl_ensure_line_actor(iv, color=(1.0, 0.2, 0.2), width=2.5):
    """
    Create (once) and return the VTK line source/actor used as the reference line overlay for a viewer.
    """
    if not hasattr(iv, "_ref_line_src"):
        ls = vtk.vtkLineSource()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(ls.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetLineWidth(width)
        actor.GetProperty().SetLighting(False)
        actor.PickableOff()
        iv.renderer.AddActor(actor)
        iv._ref_line_src = ls
        iv._ref_actor = actor
    return iv._ref_line_src, iv._ref_actor


def rl_hide_actor_if_any(iv):
    """Hide the reference-line actor if it exists."""
    if hasattr(iv, "_ref_actor"):
        iv._ref_actor.VisibilityOff()
        try:
            iv.renderer.GetRenderWindow().Render()
        except Exception:
            pass
