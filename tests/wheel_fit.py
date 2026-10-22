"""Shared by the tests: measure a fitted wheel mesh (tire or rim) against the game's wheel shader formula.

P.yz += normalize(P.yz) * lerp(W.y, W.x + W.z, Color0.b); P.x += (0.5 - Color0.a) * 2 * W.w, in the mesh's own space
(axle = X), Color0 read as raw bytes. Applied here with numpy to the mesh as modelled, independently of the add-on.
"""
import numpy as np


def _raw(colour, values):
    if colour.data_type != "BYTE_COLOR":
        return values
    return np.where(values <= 0.0031308, values * 12.92, 1.055 * np.power(np.clip(values, 0, None), 1 / 2.4) - 0.055)


def measure(obj, depsgraph):
    """{"FormulaError": largest distance (m) between the evaluated mesh and the formula, "Radius" / "ModelledRadius":
    (min, max) distance from the axle, "Width" / "ModelledWidth": extent along the axle}."""
    me = obj.data
    n = len(me.vertices)
    co = np.empty(n * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    evaluated = obj.evaluated_get(depsgraph)
    ev = evaluated.to_mesh()
    fitted = np.empty(len(ev.vertices) * 3)
    ev.vertices.foreach_get("co", fitted)
    evaluated.to_mesh_clear()
    fitted = fitted.reshape(-1, 3)
    colour = me.color_attributes[0]
    values = np.empty(len(colour.data) * 4)
    colour.data.foreach_get("color", values)
    values = values.reshape(-1, 4)
    if colour.domain == "CORNER":
        corners = np.empty(len(me.loops), np.int64)
        me.loops.foreach_get("vertex_index", corners)
        per_vertex = np.zeros((n, 4))
        per_vertex[corners] = values
        values = per_vertex
    blue, alpha = _raw(colour, values[:, 2]), values[:, 3]
    w_y, w_xz, w_w = obj["unbound_wheel_fit"]
    radius = np.linalg.norm(co[:, 1:], axis=1)
    unit = co[:, 1:] / np.where(radius > 0, radius, 1)[:, None]
    expected = co.copy()
    expected[:, 1:] += unit * (w_y + (w_xz - w_y) * blue)[:, None]
    expected[:, 0] += (0.5 - alpha) * 2 * w_w
    fitted_radius = np.linalg.norm(fitted[:, 1:], axis=1)
    error = float(np.abs(fitted - expected).max()) if fitted.shape == expected.shape else float("inf")
    return {"FormulaError": error, "Radius": (float(fitted_radius.min()), float(fitted_radius.max())),
            "ModelledRadius": (float(radius.min()), float(radius.max())),
            "Width": float(np.ptp(fitted[:, 0])), "ModelledWidth": float(np.ptp(co[:, 0]))}
