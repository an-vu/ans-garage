"""Numerical check of the profile -> Blender node compiler (Cycles bake vs Python evaluation).

Textures are replaced by an analytic function of game-space coordinates in BOTH evaluations, so this
tests the translation of every operation, input conversion (UV flip, byte-colour decode, axes) and branch.
blender --background --factory-startup --python test_node_compiler.py -- <addon dir> <materials.json> <report.json>
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:]
addon, materials, out = Path(args[0]), Path(args[1]), Path(args[2])
spec = importlib.util.spec_from_file_location("unbound_profiles_test", addon / "unbound_profiles.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
mspec = importlib.util.spec_from_file_location("unbound_materials_test", addon / "unbound_materials.py")
M = importlib.util.module_from_spec(mspec)
mspec.loader.exec_module(M)

N = 48  # N*N samples
DEBUG = args[3] if len(args) > 3 else None
BAKED = {}
CAMERA = (3.0, 1.7, -4.0)
rng = np.random.default_rng(7)
# Dirt and dust amount and colour (the paint shader's own), and a rain phase on the wet ramp's rising edge.
CONDITION_VALUES = {("Ext_DirtColor_Amt", 3): 0.7, ("Ext_DustColor_Amt", 3): 0.4, ("WaterCycle", 0): 0.65,
                    **{(n, c): P.CONDITIONS[n][2] for n in ("Ext_DirtColor_Amt", "Ext_DustColor_Amt") for c in range(3)}}
# A case passes when Cycles and Python agree within 1e-3 on all but 1% of samples (branch thresholds hit exactly).
MAX_MISMATCH = 0.01


def tex_fn(slot, k, u, v, layer=0.0):
    return 0.5 + 0.5 * np.sin(3.1 * u + 2.3 * v + 0.37 * slot + 0.7 * k + 1.3 * layer)


class TestBuilder(P.NodeBuilder):
    """Same compiler; texture samples replaced by the analytic function (on game coordinates)."""

    def _sample(self, slot, image, coords):
        layer = getattr(self, "_layer", 0.0)
        out = []
        for k in range(4):
            a = self.math("MULTIPLY", coords[0], 3.1)
            b = self.math("MULTIPLY_ADD", coords[1], 2.3, a)
            c = self.math("ADD", b, 0.37 * slot + 0.7 * k)
            if not isinstance(layer, (int, float)) or layer:
                c = self.math("MULTIPLY_ADD", layer, 1.3, c)
            s = self.math("SINE", c)
            out.append(self.math("MULTIPLY_ADD", s, 0.5, 0.5))
        return out

    def view(self, name):
        if name.startswith("CameraPos."):
            return CAMERA["xyz".index(name[-1])]  # pinned camera (Frostbite axes) in both evaluations
        return super().view(name)

    def input(self, name):
        if name.startswith("ViewPos."):
            # Pinned view: identity rotation at CAMERA, i.e. ViewPos = WorldPos - CAMERA in both evaluations.
            c = "xyz".index(name[-1])
            return self.math("SUBTRACT", super().input("WorldPos." + name[-1]), CAMERA[c])
        return super().input(name)

    def _array_sample(self, rec, images, coords):
        layer = coords[2]
        if isinstance(layer, (int, float)):
            self._layer = float(max(0, min(len(images) - 1, math.floor(layer + 0.5))))
        else:
            self._layer = self.math("MINIMUM", self.math("MAXIMUM", self.math("ROUND", layer), 0.0), float(len(images) - 1))
        r = self._sample(rec["slot"], None, coords[:2])
        self._layer = 0.0
        return r


def py_eval(sp, roots, inputs):
    """Vectorized evaluation of specialized nodes."""
    memo = {}

    def val(v):
        if not isinstance(v, tuple):
            return np.full(N * N, P._f(v), dtype=np.float64)
        i = v[1]
        if i in memo:
            return memo[i]
        rec = sp.nodes[i]
        op = rec["op"]
        if op in ("input", "view"):
            r = inputs[rec["name"]]
        elif op == "param":
            r = np.full(N * N, inputs[(rec["name"], rec["c"])])
        elif op == "tex":
            co = [val(c) for c in rec["coords"]]
            layer = np.clip(np.floor(co[2] + 0.5), 0, 10) if len(co) == 3 else 0.0
            r = [tex_fn(rec["slot"], k, co[0], co[1], layer) for k in range(4)]
        elif op == "ch":
            r = val(rec["args"][0])[rec["args"][1]]
        else:
            a = [val(x) for x in rec["args"]]
            r = np_op(op, a, rec)
        memo[i] = r
        return r
    return {k: val(v) for k, v in roots.items()}


def np_op(op, a, rec):
    with np.errstate(all="ignore"):
        if op in ("add", "iadd"): return a[0] + a[1]
        if op in ("sub", "isub"): return a[0] - a[1]
        if op in ("mul", "imul"): return a[0] * a[1]
        if op == "div": return np.where(a[1] != 0, a[0] / np.where(a[1] != 0, a[1], 1), 0.0)
        if op == "neg": return -a[0]
        if op in ("max", "binop37"): return np.maximum(a[0], a[1])
        if op in ("min", "binop38"): return np.minimum(a[0], a[1])
        if op == "abs": return np.abs(a[0])
        if op == "saturate": return np.clip(a[0], 0, 1)
        if op == "sqrt": return np.sqrt(np.maximum(a[0], 0))
        if op == "rsqrt": return np.where(a[0] > 0, 1 / np.sqrt(np.maximum(a[0], 1e-30)), 0.0)
        if op == "exp2": return np.exp2(a[0])
        if op == "log2": return np.where(a[0] > 0, np.log2(np.maximum(a[0], 1e-300)), -np.inf)  # DXIL: log2(0) = -inf
        if op == "frac": return a[0] - np.floor(a[0])
        if op == "floor": return np.floor(a[0])
        if op == "ceil": return np.ceil(a[0])
        if op in ("trunc", "fptoui_i32", "fptosi_i32"): return np.trunc(a[0])
        if op == "round_ne": return np.floor(a[0] + 0.5)
        if op in ("sin", "cos", "tan"): return getattr(np, op)(a[0])
        if op in ("fmod", "isrem"): return np.fmod(a[0], np.where(a[1] != 0, a[1], 1))
        if op == "select": return np.where(a[0] > 0.5, a[1], a[2])
        if op == "and": return a[0] * a[1]
        if op == "or": return np.maximum(a[0], a[1])
        if op == "not": return 1 - a[0]
        if op in ("uitofp_float", "sitofp_float", "zext_i32"): return a[0]
        if op.startswith(("fcmp_", "icmp_")):
            p = op[5:]
            x, y = a
            r = {"olt": x < y, "ult": x < y, "slt": x < y, "ogt": x > y, "ugt": x > y, "sgt": x > y,
                 "ole": x <= y, "ule": x <= y, "sle": x <= y, "oge": x >= y, "uge": x >= y, "sge": x >= y,
                 "oeq": x == y, "ueq": x == y, "one": x != y, "une": x != y,
                 "eq": np.abs(x - y) <= 0.5, "ne": np.abs(x - y) > 0.5}[p]
            return r.astype(float)
        if op == "ishl": return a[0] * 2.0 ** a[1]
        if op == "ilshr": return np.floor(a[0] / 2.0 ** a[1])
        if op == "iand":
            m = int(a[1][0]) & 0xffffffff
            return np.mod(a[0], m + 1) if m & (m + 1) == 0 else a[0] - np.mod(a[0], 2)
        if op == "lookup":
            t = np.array(rec["table"])
            return t[np.clip(np.floor(a[0] + 0.5).astype(int), 0, len(t) - 1)]
    raise ValueError(op)


def make_mesh(name):
    """N*N tiny quads, random orientation; per-quad constant UVs/colours; BakeUV puts each quad in one texel."""
    verts, faces, normals = [], [], []
    for i in range(N * N):
        gx, gy = i % N, i // N
        c = np.array([gx * 0.05, gy * 0.05, 0.0])
        nrm = rng.normal(size=3)
        nrm /= np.linalg.norm(nrm)
        t = np.cross(nrm, [0.3, 0.5, 0.8])
        t /= np.linalg.norm(t)
        b = np.cross(nrm, t)
        s = 0.004
        base = len(verts)
        for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            verts.append(tuple(c + s * (du * t + dv * b)))
        faces.append((base, base + 1, base + 2, base + 3))
        normals.append(nrm)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    uvdata = {}
    for layer in ("UVChannel0", "UVChannel1", "UVChannel2", "UVChannel3"):
        uv = me.uv_layers.new(name=layer)
        vals = rng.uniform(-0.25, 1.25, size=(N * N, 2))
        uvdata[layer] = vals
        for f, poly in enumerate(me.polygons):
            for li in poly.loop_indices:
                uv.data[li].uv = vals[f]
    bake = me.uv_layers.new(name="BakeUV")
    for f, poly in enumerate(me.polygons):
        gx, gy = f % N, f // N
        u0, v0 = gx / N, gy / N
        for k, li in enumerate(poly.loop_indices):
            du, dv = ((0, 0), (1, 0), (1, 1), (0, 1))[k]
            bake.data[li].uv = (u0 + du / N, v0 + dv / N)
    me.uv_layers.active = bake
    col = me.color_attributes.new("VColor1", "BYTE_COLOR", "CORNER")
    bytes_ = rng.integers(0, 256, size=(N * N, 4))
    bytes_[: N * N // 4, 0] = 255  # cover the paint (Color0.r >= 0.753) branch heavily
    for f, poly in enumerate(me.polygons):
        for li in poly.loop_indices:
            col.data[li].color_srgb = tuple(bytes_[f] / 255.0)
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj, uvdata, bytes_, np.array(normals), np.array([np.mean([verts[f * 4 + k] for k in range(4)], axis=0) for f in range(N * N)])


def bake(obj, mat, socket_values, label):
    """Bake an emission of up to three float sockets into an N x N float image."""
    tree = mat.node_tree
    img = bpy.data.images.new("bake_" + label, N, N, float_buffer=True)
    node = tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    tree.nodes.active = node
    comb = tree.nodes.new("ShaderNodeCombineXYZ")
    for s, v in zip(comb.inputs, socket_values):
        if isinstance(v, (int, float)):
            s.default_value = v
        else:
            tree.links.new(v, s)
    em = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(comb.outputs[0], em.inputs["Color"])
    em.inputs["Strength"].default_value = 1.0
    outn = next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL")
    tree.links.new(em.outputs[0], outn.inputs["Surface"])
    bpy.ops.object.bake(type="EMIT", margin=0, use_clear=True)
    px = np.empty(N * N * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(N, N, 4)[..., :3].reshape(N * N, 3)  # row = gy, col = gx -> face index


def main():
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.device = "CPU"
    scene.render.bake.use_selected_to_active = False
    doc, states = None, None
    doc = json.loads(materials.read_text(encoding="utf-8-sig"))
    resolver = M.Resolver(doc)
    runtime, _, _ = P.runtime_values(materials.with_name("assembly.json"))
    images = P.Images(materials.parent)
    # Every entry the export's renderable sections select (vehicle-agnostic profiles: one entry per program and
    # vertex declaration), once per (entry, usage layout), with the first state that uses it.
    chosen = {}
    for mesh in doc["Meshes"]:
        slots = {s["Index"]: s for s in mesh["Slots"]}
        for section in mesh["Sections"]:
            if not section.get("Renderable") or section.get("MaterialSlot") not in slots:
                continue
            st, _, _ = resolver.choose_root(mesh, slots[section["MaterialSlot"]])
            prof = P.profile_for(st)
            if not prof:
                continue
            layout = P.section_layout(section)
            for e in P.entries_for(prof, layout, P.section_formats(section)):
                key = (id(e), tuple(layout))
                if key not in chosen and not e["Unresolved"]:
                    chosen[key] = ((st["Shader"] or {}).get("Asset"), st, e, layout)
    report = {}
    axes = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
    inv = [[axes[j][i] for j in range(3)] for i in range(3)]
    cases = sorted(((sh + "#%s#%d" % ("/".join(layout), i), st, e, layout, False)
                    for i, (sh, st, e, layout) in enumerate(chosen.values())), key=lambda c: c[0])
    # Again with dirt, dust and wet live, at values between clean and fully dirty/wet.
    cases += [(sh + "#conditions", st, e, layout, True) for sh, st, e, layout, _ in cases
              if any(x["Name"] in P.CONDITIONS for x in e["Externals"])]
    for shader, st, prof, layout, conditions in cases:
        prof.setdefault("Kind", P.profile_for(st).get("Kind")); prof["ShaderAsset"] = shader.split("#")[0]
        live = P.live_names(prof, runtime)
        consts = {n["name"]: 1.0 for n in prof["Nodes"] if n["op"] == "input" and n["name"].startswith("VSConst:")}
        try:
            rename = P.element_inputs(prof, layout)
        except P.Unsupported as exc:
            report[shader] = {"Skipped": str(exc)}
            continue
        p = P.plan(prof, st, runtime, live, images, materials.parent, consts, rename, conditions)
        if p["issues"] or p["unsupported"]:
            report[shader] = {"Skipped": p["issues"] or p["unsupported"]}
            continue
        if any(not str(k).startswith(("TexCoord", "Color0", "WorldNormal", "WorldPos", "ObjectPos", "ObjectNormal", "ObjectOrigin",
                                      "Time", "ViewFade", "CameraPos", "ViewPos", "P:"))
               for k in p["inputs"]):
            report[shader] = {"Skipped": "inputs outside the test mesh: %s" % p["inputs"]}
            continue
        obj, uvdata, bytes_, normals, centers = make_mesh("test_" + shader.rsplit("/", 1)[-1])
        mat = bpy.data.materials.new("test")
        mat.use_nodes = True
        obj.data.materials.append(mat)
        bpy.context.view_layer.objects.active = obj
        for o in scene.objects:
            o.select_set(o == obj)
        ctx = {"uv": {"TexCoord%d" % i: "UVChannel%d" % i for i in range(4)},
               "colors": {"Color0": {"name": "VColor1", "byte": True}}, "tangent_uv": "UVChannel0",
               "fb_to_blender": [tuple(map(float, r)) for r in axes], "blender_to_fb": [tuple(map(float, r)) for r in inv],
               "images": p["images"], "image_issues": p["image_issues"], "notes": []}
        b = TestBuilder(mat.node_tree, p["spec"], ctx)
        live_vals = {}
        for key in p["live"]:
            val = float(CONDITION_VALUES.get(key, p["values"][key]))
            b.ctx.setdefault("live", {})[key] = val
            live_vals[key] = val
        fb = lambda v: np.stack([v @ np.array(r, dtype=float) for r in inv], axis=1)
        nfb, pfb = fb(normals), fb(centers)
        inputs = dict(live_vals)
        for i in range(4):
            uvv = uvdata["UVChannel%d" % i]
            inputs["TexCoord%d.u" % i], inputs["TexCoord%d.v" % i] = uvv[:, 0], 1 - uvv[:, 1]
        for c, ch in enumerate("rgba"):
            inputs["Color0." + ch] = bytes_[:, c] / 255.0
        for c, ch in enumerate("xyz"):
            inputs["WorldNormal." + ch] = nfb[:, c]
            inputs["WorldPos." + ch] = pfb[:, c]
            inputs["ObjectPos." + ch] = centers[:, c]
            inputs["ObjectNormal." + ch] = normals[:, c]
            inputs["ObjectOrigin." + ch] = np.zeros(N * N)
        for c, ch in enumerate("xyz"):
            inputs["ViewPos." + ch] = pfb[:, c] - CAMERA[c]
        inputs["Time"] = np.zeros(N * N)
        inputs["ViewFade"] = np.ones(N * N)
        for c, ch in enumerate("xyz"):
            inputs["CameraPos." + ch] = np.full(N * N, CAMERA[c])
        outs = {k: p["outs"][k] for k in ("BaseColor", "Metallic", "Smoothness", "RT2.x", "CoatSmoothness", "Emissive", "Discard",
                                          "Transmittance", "Reflectance") if k in p["outs"]}
        flat = []
        for k, v in outs.items():
            for i, x in enumerate(v if isinstance(v, list) else [v]):
                used = P.reachable(p["spec"], [x])
                names = {p["spec"].nodes[j].get("name") for j in used}
                if any(p["spec"].nodes[j]["op"] == "frame" for j in used):
                    continue
                flat.append(("%s[%d]" % (k, i), x))
        if DEBUG and shader.endswith(DEBUG.split(":")[0]):
            used = sorted(P.reachable(p["spec"], [dict(flat)[DEBUG.split(":")[1] if ":" in DEBUG else "BaseColor[0]"]]))
            flat = [("n%d" % j, ("N", j)) for j in used if p["spec"].nodes[j]["op"] not in ("tex",)]
        expected = py_eval(p["spec"], dict(flat), inputs)
        result = {}
        for start in range(0, len(flat), 3):
            group = flat[start:start + 3]
            sockets = [b.export(b.value(x)) for _, x in group]
            got = bake(obj, mat, sockets + [0.0] * (3 - len(sockets)), shader.rsplit("/", 1)[-1] + str(start))
            for j, (label, _) in enumerate(group):
                e = expected[label]
                e = np.broadcast_to(e, (N * N,))
                BAKED[label] = got[:, j]
                d = np.abs(got[:, j] - e)
                ok = np.isfinite(e)
                result[label] = {"MaxAbs": float(np.max(d[ok])) if ok.any() else None,
                                 "P99": float(np.percentile(d[ok], 99)) if ok.any() else None,
                                 "Over1e-3": int(np.sum(d[ok] > 1e-3)), "Samples": int(ok.sum())}
        report[shader] = result
        worst = max((r["MaxAbs"] or 0) for r in result.values()) if result else None
        if DEBUG and shader.endswith(DEBUG.split(":")[0]):
            def loggy(k):
                rec = p["spec"].nodes[int(k[1:])]
                return rec["op"] == "log2" or (rec["op"] == "mul" and any(isinstance(a, tuple) and p["spec"].nodes[a[1]]["op"] == "log2" for a in rec["args"]))
            bad = [k for k, v in result.items() if v["Over1e-3"] and not loggy(k)]
            for k in bad[:3]:
                j = int(k[1:].split("[")[0]) if k.startswith("n") else None
                rec = p["spec"].nodes[j] if j is not None else None
                print("FIRST BAD", k, result[k], json.dumps(rec, default=str)[:300])
                if rec and rec["op"].startswith(("fcmp", "icmp")):
                    x = [np.broadcast_to(py_eval(p["spec"], {"a": a}, inputs)["a"], (N * N,)) for a in rec["args"]]
                    e = expected[k]
                    print("   operand gap at mismatching samples:", np.abs(x[0] - x[1])[np.abs(e - BAKED[k]) > 1e-3][:5])
                for a in (rec or {}).get("args", []):
                    if isinstance(a, tuple):
                        xa = np.broadcast_to(py_eval(p["spec"], {"a": a}, inputs)["a"], (N * N,))
                        m = np.abs(expected[k] - BAKED[k]) > 1e-3
                        print("   arg", a, p["spec"].nodes[a[1]]["op"], "python", xa[m][:4], "baked", BAKED.get("n%d" % a[1], np.zeros(N * N))[m][:4])
        print(shader.rsplit("/", 1)[-1], "outputs", len(result), "worst", worst,
              {k: v["Over1e-3"] for k, v in result.items() if v["Over1e-3"]})
        bpy.data.objects.remove(obj)
    out.write_text(json.dumps(report, indent=1))
    bad = {k: v for k, v in report.items() if "Skipped" not in v
           and any(o["Over1e-3"] > MAX_MISMATCH * o["Samples"] for o in v.values())}
    for k in bad:
        print("FAIL", k.rsplit("/", 1)[-1], {o: r["Over1e-3"] for o, r in bad[k].items() if r["Over1e-3"]})
    tested = sum("Skipped" not in v for v in report.values())
    print("PASSED", tested - len(bad), "FAILED", len(bad), "(%d with dirt, dust and wet)" % sum(k.endswith("#conditions") for k in report))
    if bad:
        raise SystemExit(1)


main()
