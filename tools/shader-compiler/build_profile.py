"""Build a static-state surface profile for one vehicle shader G-buffer program.

The profile is a simplified expression DAG (formulas only, no bytecode) over:
  interpolants (IN), material/runtime parameters (P:<name>.<c>), texture samples (T:<slot>),
  view constants that remain after simplification (V:<reg>.<c>).
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.setrecursionlimit(50000)
import analyze_ps as ap
import dag_tools as dt
import dxil_eval as dx
from dxil_eval import E, is_num

HERE = Path(__file__).parent
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from settings import path as setting  # noqa: E402

DATA = setting("shader_data_dir")  # game-derived inputs (disassembly, parsed shader database); never committed


def srgb_to_linear(c):
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def uniform_texture_value(path, srgb):
    """Exact decoded channel values if every texel is identical, else None."""
    from ddsread import load
    a = load(path).reshape(-1, 4)
    if not (a == a[0]).all():
        return None
    v = a[0] / 255.0
    if srgb:
        v[:3] = srgb_to_linear(v[:3])
    return [float(x) for x in v]


def find_normal(expr):
    """(a,b,c) where expr contains a*rsqrt(a*a+b*b+c*c)."""
    for x in dt.topo([expr]):
        if x.op == "rsqrt":
            s = x.args[0]
            terms = []
            stack = [s]
            while stack:
                t = stack.pop()
                if isinstance(t, E) and t.op == "add":
                    stack.extend(t.args)
                else:
                    terms.append(t)
            sq = [t.args[0] for t in terms if isinstance(t, E) and t.op == "mul" and t.args[0] is t.args[1]]
            if len(sq) == 3 and len(terms) == 3:
                return x, sq
    return None, None


def axis_order(expr, rs, comps):
    """Return comps reordered as x,y,z using the RT0.x/RT0.y default branch (encoding writes x from comp a)."""
    return comps


def extract_smoothness(expr):
    """RT0.z = 0.5 + select(c, 0.001466276 + k*S, -0.001466276 - k*S), k = 0.4980469 (sign bit of the normal)."""
    k, eps = 0.4980469, 0.001466276
    if isinstance(expr, E) and expr.op == "select" and is_num(expr.args[1]) and is_num(expr.args[2]):
        a, b = expr.args[1] - 0.5, 0.5 - expr.args[2]
        if abs(a - b) < 1e-6:
            return dx.f32((a - eps) / k)
        return None
    sel = expr.args[1] if isinstance(expr, E) and expr.op == "add" and is_num(expr.args[0]) and expr.args[0] == 0.5 else None
    if not (isinstance(sel, E) and sel.op == "select"):
        return None
    pos = sel.args[1]
    if is_num(pos):
        return dx.f32((pos - eps) / k)
    if pos.op == "add" and is_num(pos.args[0]) and abs(pos.args[0] - eps) < 1e-6:
        return dx.div(pos.args[1], k)
    return None


def quantized(expr):
    """All (shift, scale, X) for fptoui(0.5 + scale*X) packed into an integer expression."""
    out = []
    def walk(x, shift):
        if not isinstance(x, E):
            return
        if x.op == "ishl" and is_num(x.args[1]):
            return walk(x.args[0], shift + x.args[1])
        if x.op == "ilshr" and is_num(x.args[1]):
            return walk(x.args[0], shift - x.args[1])
        if x.op in ("ior", "iand"):
            for a in x.args: walk(a, shift)
            return
        if x.op == "fptoui_i32":
            a = x.args[0]
            if a.op == "add" and is_num(a.args[0]) and a.args[0] == 0.5 and a.args[1].op == "mul" and is_num(a.args[1].args[0]):
                out.append((shift, a.args[1].args[0], a.args[1].args[1]))
            return
    walk(expr, 0)
    return out


def leaf_name(x, bind, params):
    if x.op == "in":
        return "IN%d.%d.%s" % (x.args[0], x.args[1], dx.XYZW[x.args[2]])
    if x.op == "cb":
        b, reg, c, kind = x.args
        if b == bind and is_num(reg) and reg in params:
            return "P:%s.%s" % (params[reg], dx.XYZW[c])
        return "V:cb%d.%s.%s" % (b, reg, dx.XYZW[c])
    raise ValueError(x.op)


def serialize(roots, bind, params):
    nodes, ids = [], {}

    def ref(v):
        if isinstance(v, bool): return {"b": v}
        if is_num(v): return {"c": float(v)} if isinstance(v, float) else {"i": int(v)}
        if isinstance(v, tuple): return {"t": [ref(a) for a in v]}
        return {"n": ids[v]}
    for x in dt.topo([v for _, v in roots]):
        if x.op in ("in", "cb"):
            rec = {"op": "leaf", "name": leaf_name(x, bind, params)}
        elif x.op == "tex":
            kind, slot, coords, extra = x.args
            rec = {"op": "tex", "kind": kind, "slot": slot, "coords": [ref(c) for c in coords],
                   "extra": {k: ref(v) for k, v in extra}}
        elif x.op == "ch":
            rec = {"op": "ch", "args": [ref(x.args[0]), {"i": x.args[1]}]}
        elif x.op == "lookup":
            rec = {"op": "lookup", "table": dt.LOOKUPS[x.args[0]], "args": [ref(x.args[1])]}
        else:
            rec = {"op": x.op, "args": [ref(a) for a in x.args]}
        ids[x] = len(nodes)
        nodes.append(rec)
    return {"nodes": nodes, "outputs": {l: ref(v) for l, v in roots}}


# Program table keyed by shader: vehicle-shader-programs.json (asset names, one export) or all-shader-programs.json
# (name hashes, whole database).
PROGRAMS_FILE = "vehicle-shader-programs.json"
_CACHE = {}


def _cached(name):
    if name not in _CACHE:
        _CACHE[name] = json.loads((DATA / name).read_text(encoding="utf-8-sig"))
    return _CACHE[name]


def build(shader, ps, material_paths, exposed, overrides=None, bound=None, uniform_ok=True, verbose=True, targets=None,
          extra_cb=None):
    """bound: {texture parameter name: decoded uniform value or 'image'} as bound by the materials."""
    parsed = _cached("parsed.json")[0]
    programs = _cached(PROGRAMS_FILE)
    defaults_root = DATA / "shader-defaults"
    defaults = {t["ResourceId"]: t for t in _cached("shader-defaults/textures.json")["Textures"]}
    names = _cached("default-texture-names.json")
    text = (DATA / "asm" / (ps + ".asm")).read_text()
    for gname, values in dx.Program(text).globals.items():
        dt.LOOKUPS[gname.split("?")[1].split("@")[0]] = values
    consts, sol = ap.constants_for(parsed, programs, shader, ps)
    ext = {v["Name"]: v for v in consts["ExternalValues"]}
    unknown = [n for n in ext if n.casefold() in {e.casefold() for e in exposed}]
    prog, ev, consts, sol, bind = ap.run(parsed, programs, DATA / "asm", shader, ps, overrides or {}, unknown, extra_cb)
    params = {ext[n]["Index"] - 1 - consts.get("ValueStart", 0): n for n in unknown}
    roots = [("RT%d.%s" % (k[0], dx.XYZW[k[1]]), v) for k, v in sorted(ev.outputs.items())
             if targets is None or k[0] in targets]
    if ev.discards:
        d = False
        for c in ev.discards:
            d = dx.bor(d, c)
        roots.append(("DISCARD", d))
    full = list(roots)

    # Texture slot identities.
    slot_info = {}
    default_by_slot = {t["Index"]: t["Hash"] for t in consts["Textures"]}
    for i in sorted(set(default_by_slot) | {t["Index"] for t in consts["ExternalTextures"]}):
        external = next((t for t in consts["ExternalTextures"] if t["Index"] == i), None)
        h = default_by_slot.get(i)
        info = {"Slot": i, "Dim": prog.texture_dims.get(i), "Parameter": external["Name"] if external else None,
                "ParameterKey": external["ParameterKey"] if external else None, "DefaultHash": h,
                "DefaultAsset": names.get(str(h)) if h else None}
        slot_info[i] = info
    asset_to_resource = {}
    for t in defaults.values():
        for a in t.get("Aliases", []):
            asset_to_resource[a["Asset"].casefold()] = t

    subst, assumptions = {}, []
    samples = [x for x in dt.topo([v for _, v in roots]) if x.op == "tex"]
    for s in samples:
        if s.args[1] not in slot_info:
            slot_info[s.args[1]] = {"Slot": s.args[1], "Dim": prog.texture_dims.get(s.args[1]), "Parameter": None,
                                    "ParameterKey": None, "DefaultHash": None, "DefaultAsset": None,
                                    "Runtime": "Undescribed engine resource (instance data buffer)"}
            continue
        info = slot_info[s.args[1]]
        value, why = None, None
        p = info["Parameter"]
        if p and bound and p in bound:
            b = bound[p]
            if b == "image":
                continue
            value, why = b, "material binds a texture whose decoded texels are uniform"
        elif p and info["DefaultHash"] is None:
            value, why = [0.0, 0.0, 0.0, 0.0], "runtime-bound texture without shader default; static undamaged state assumes zero"
        elif info["DefaultAsset"]:
            res = asset_to_resource.get(info["DefaultAsset"].casefold())
            if res and res.get("Path") and uniform_ok:
                u = uniform_texture_value(defaults_root / res["Path"], res.get("ColorSpace") == "sRGB")
                if u is not None:
                    value, why = u, "shader default texture with uniform texels"
        if value is not None:
            for k in range(4):
                subst[E("ch", s, k)] = value[k]
            assumptions.append({"Slot": info["Slot"], "Parameter": p, "Asset": info["DefaultAsset"], "Value": value, "Reason": why})
    # Derivatives (specular anti-aliasing from normal curvature) are not reproduced.
    for x in dt.topo([v for _, v in roots]):
        if x.op in ("ddx", "ddy", "ddx_fine", "ddy_fine"):
            subst[x] = 0.0
    simplified = dt.simplify(roots, fixed_subst=subst)
    check = dt.compare([(l, dt.rebuild(v, subst, {})) for l, v in full], simplified)
    if verbose:
        print("nodes full", dt.count(full), "-> simplified", dt.count(simplified))
        print("max |full - simplified| per output (after exact substitutions):", {k: v for k, v in check.items() if v[0] > 1e-5})
    return {"prog": prog, "consts": consts, "bind": bind, "params": params, "roots": simplified, "full": full,
            "slots": slot_info, "assumptions": assumptions, "check": check, "exposed": unknown}


def semantic(result):
    r = dict(result["roots"])
    out = {}
    rs, comps = find_normal(r["RT0.x"])
    if comps:
        out["Normal"] = comps
    s = extract_smoothness(r["RT0.z"])
    if s is not None:
        out["Smoothness"] = s
    out["BaseColor"] = [r["RT1.x"], r["RT1.y"], r["RT1.z"]]
    out["Occlusion_RT1w"] = r["RT1.w"]
    out["RT2"] = [r["RT2.x"], r["RT2.y"], r["RT2.z"], r["RT2.w"]]
    out["Metallic"] = r["RT2.y"]
    if "RT3.x" in r:
        out["Emissive"] = [r["RT3.x"], r["RT3.y"], r["RT3.z"]]
    if "RT4.x" in r:
        out["RT4"] = {k: quantized(r[k]) for k in ("RT4.x", "RT4.y", "RT4.z", "RT4.w")}
        _, cn = find_normal(r["RT4.z"])
        if cn:
            out["CoatNormal"] = cn
    return out


if __name__ == "__main__":
    shader, ps = sys.argv[1], sys.argv[2]
    exposed = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] else []
    res = build(shader, ps, None, exposed)
    sem = semantic(res)
    roots = []
    for k, v in sem.items():
        if k == "RT4":
            for kk, items in v.items():
                for shift, scale, x in items:
                    roots.append(("%s<<%d*%g" % (kk, shift, scale), x))
        elif isinstance(v, list):
            roots += [("%s[%d]" % (k, i), x) for i, x in enumerate(v)]
        else:
            roots.append((k, v))
    print(dx.render(roots))
    print(json.dumps(res["assumptions"], indent=1))
