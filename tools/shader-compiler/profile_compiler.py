"""Shader formula compiler library: turns a disassembled pixel program into a static-state surface formula.

Used by compile_all.py, which builds blender/ans_garage/shader_profiles.json.gz for every vehicle shader.
"""
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.setrecursionlimit(100000)
import analyze_ps as ap
import build_profile as bp
import dag_tools as dt
import dxil_eval as dx
import make_profiles as mp
from dxil_eval import E, is_num

dx.ROWDOT = True
HERE = Path(__file__).parent
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from settings import path as setting  # noqa: E402

DATA = setting("shader_data_dir")  # game-derived inputs (disassembly, parsed shader database); never committed
DB_SHA256 = "db8ac19bb35c4cc8dd9a19e06c0dade4e74e3972d1f653a47b8a996ec6572096"
FMT = {3: "Float3", 4: "Float4", 6: "Half2", 8: "Half4", 13: "UByte4N", 19: "Short2N", 23: "UShort4", 25: "UShort4N"}
RUNTIME_KEYS = set()  # parameter keys bound to runtime vehicle customization
VIEW_BIND = 2  # per-view constants (3744 bytes) in these programs
# Vehicle-agnostic mode (compile_all.py): layouts are the database's vertex declarations, inputs are named by
# declaration element ("Elem<i>.<component>") and mapped to usages per mesh section in the add-on. Element roles the
# routing heuristics rely on (Pos at element 0, a Half4 position delta) are recorded per entry as AssumedUsages.
AGNOSTIC = False
ASSUMED = {}
VIEW_SEMANTICS = {(41, 0): "CameraPos.x", (41, 1): "CameraPos.y", (41, 2): "CameraPos.z", (0, 2): "Time"}


# ------------------------------------------------------------------ vertex program routing
def vs_listing(vs):
    text = (DATA / "asm" / (vs + ".asm")).read_text()
    defs = {}
    for line in text.splitlines():
        m = re.match(r"\s+(%\d+) = (.*?)(\s+;.*)?$", line)
        if m:
            defs[m.group(1)] = m.group(2)
    stores = {}
    for m in re.finditer(r"storeOutput\.f32\(i32 5, i32 1, i32 (\d+), i8 (\d), float (\S+)\)", text):
        stores[(int(m.group(1)), int(m.group(2)))] = m.group(3)
    return defs, stores


def slice_info(defs, v):
    elements, buffer, seen, stack = set(), False, set(), [v]
    while stack:
        x = stack.pop()
        if x in seen or not x.startswith("%"):
            continue
        seen.add(x)
        d = defs.get(x, "")
        m = re.match(r"call \w+ @dx\.op\.loadInput\.\w+\(i32 4, i32 (\d+)", d)
        if m:
            elements.add(int(m.group(1)))
            continue
        if "bufferLoad" in d:
            buffer = True
        stack.extend(re.findall(r"%\d+", d))
    return elements, buffer


def position_kind(defs, v, usage):
    """Final operation decides: Pos + deformation -> ObjectPos; rotated position + instance translation -> WorldPos."""
    m = re.match(r"fadd fast float (%\d+), (%\d+)$", defs.get(v, ""))
    if not m:
        return None
    ops = [defs.get(o, "") for o in m.groups()]
    for i, d in enumerate(ops):
        li = re.match(r"call float @dx\.op\.loadInput\.f32\(i32 4, i32 (\d+)", d)
        if li and int(li.group(1)) < len(usage) and usage[int(li.group(1))] == "Pos":
            return "ObjectPos"
        if re.match(r"extractvalue %dx\.types\.ResRet\.f32 %\d+, 3$", d):
            el, _ = slice_info(defs, m.groups()[1 - i])
            if any(e < len(usage) and usage[e] == "Pos" for e in el):
                return "WorldPos"
    return None


def view_fade(defs, v):
    """1 - saturate(dot4(cubic(x), view-constant coefficients)): a per-vertex runtime fade from the camera environment."""
    m = re.match(r"fsub fast float 1\.000000e\+00, (%\d+)$", defs.get(v, ""))
    if not m or "unary.f32(i32 7" not in defs.get(m.group(1), ""):
        return False
    inner = re.findall(r"%\d+", defs[m.group(1)])
    return any("dot4" in defs.get(x, "") for x in inner)


def layouts_from(doc):
    out = set()
    for mesh in doc["Meshes"]:
        for s in mesh["Sections"]:
            attrs = tuple((a["Usage"], a["Format"]) for a in s.get("VertexAttributes", []) if a["Usage"] != "Unknown")
            if attrs:
                out.add(attrs)
    return out


PARSED = {}


def vs_constant(s, vs, defs, v):
    """Name of a vertex-program external constant passed straight through (e.g. per-wheel g_facingParam)."""
    m = re.match(r"extractvalue %dx\.types\.CBufRet\.f32 (%\d+), (\d)$", defs.get(v, ""))
    if not m:
        return None
    load = re.match(r"call %dx\.types\.CBufRet\.f32 @dx\.op\.cbufferLoadLegacy\.f32\(i32 59, %dx\.types\.Handle (%\d+), i32 (\d+)\)",
                    defs.get(m.group(1), ""))
    if not load:
        return None
    handle = re.match(r"call %dx\.types\.Handle @dx\.op\.createHandle\(i32 57, i8 2, i32 \d+, i32 (\d+)", defs.get(load.group(1), ""))
    if not handle:
        return None
    consts = PARSED["p"]["Constants"][s["VSConstants"]]
    try:
        bind, _ = ap.external_cbuffer((DATA / "asm" / (vs + ".asm")).read_text(), consts)
    except ValueError:
        return None
    if int(handle.group(1)) != bind:
        return None
    reg = int(load.group(2))
    hit = [e for e in consts["ExternalValues"] if e["Index"] - 1 - consts.get("ValueStart", 0) == reg]
    return "VSConst:%s.%s" % (hit[0]["Name"], "xyzw"[int(m.group(2))]) if len(hit) == 1 else None


_VS_EVAL = {}


def vs_outputs(vs):
    """Symbolic vertex-program outputs {(sig, row, col): expr} (loops opaque), cached."""
    if vs not in _VS_EVAL:
        old = dx.OPAQUE_LOOPS
        dx.OPAQUE_LOOPS = True
        try:
            _, ev = dx.evaluate_ps((DATA / "asm" / (vs + ".asm")).read_text(), {})
            _VS_EVAL[vs] = ev.outputs_rows
        except Exception:
            _VS_EVAL[vs] = {}
        finally:
            dx.OPAQUE_LOOPS = old
    return _VS_EVAL[vs]


def view_space(vs, row, col):
    """viewRow.w + dot(viewRow.xyz, worldPos - cameraPos) with view-matrix rows cb2[16..18] -> ViewPos.x/y/z."""
    expr = vs_outputs(vs).get((1, row, col))
    if not isinstance(expr, E):
        return None
    cbs = {(x.args[0], x.args[1], x.args[2]) for x in dt.topo([expr]) if x.op == "cb" and is_num(x.args[1])}
    view_rows = {r for b, r, c in cbs if b == VIEW_BIND and r in (16, 17, 18)}
    if len(view_rows) != 1:
        return None
    r = next(iter(view_rows))
    needed = {(VIEW_BIND, r, c) for c in range(4)} | {(VIEW_BIND, 41, c) for c in range(3)}
    if not needed <= cbs or {(b, rr) for b, rr, c in cbs if b == VIEW_BIND} - {(VIEW_BIND, r), (VIEW_BIND, 41)}:
        return None
    return "ViewPos." + "xyz"[r - 16]


def program_layouts(shader, ps, programs, layouts):
    """Vertex layouts (usage tuples) of this export served by the program's solutions."""
    out = defaultdict(int)
    for s in programs[shader]["Solutions"]:
        if s["PS"] != ps:
            continue
        decl = tuple(FMT.get(d[0], str(d[0])) for d in s["Declaration"])
        usages = {tuple(u for u, _ in l) for l in layouts if tuple(f for _, f in l) == decl}
        if len(usages) == 1:
            out[next(iter(usages))] += 1
    return dict(out)


def ps_input_semantics(shader, ps, programs, layouts, frame_rows, layout=None):
    """{(row, col): semantic} for PS input signature 1, merged over every paired VS whose declaration matches a layout
    (only the given layout when one is passed)."""
    found = defaultdict(set)
    evidence = []
    real = 0
    for s in programs[shader]["Solutions"]:
        if s["PS"] != ps:
            continue
        decl = tuple(FMT.get(d[0], str(d[0])) for d in s["Declaration"])
        matches = [l for l in layouts if tuple(f for _, f in l) == decl]
        usages = {tuple(u for u, _ in l) for l in matches}
        if len(usages) != 1:
            continue
        usage = next(iter(usages))
        if layout is not None and usage != layout:
            continue
        defs, stores = vs_listing(s["VS"])
        if all(not v.startswith("%") for v in stores.values()):
            continue  # degenerate variant (all constant outputs)
        real += 1
        frame = {}
        if frame_rows:
            r0 = min(frame_rows)
            for k in range(3):
                for c, name in ((0, "WorldTangent"), (1, "WorldBitangent"), (2, "WorldNormal")):
                    v = stores.get((r0 + k, c))
                    if v:
                        frame[v] = name + "." + "xyz"[k]
        for (row, col), v in stores.items():
            if row in frame_rows and col < 3:
                continue
            d = defs.get(v, "")
            m = re.match(r"call float @dx\.op\.loadInput\.f32\(i32 4, i32 (\d+), i32 0, i8 (\d)", d)
            if not v.startswith("%"):
                sem = "Const:" + v
            elif m:
                u, k = usage[int(m.group(1))], int(m.group(2))
                if u.startswith("Elem"):
                    sem = u.split(":")[0] + "." + str(k)
                elif u.startswith("TexCoord"):
                    sem = u + "." + "uv??"[k]
                elif u.startswith("Color"):
                    sem = u + "." + "rgba"[k]
                elif u == "Pos":
                    sem = "ObjectPos." + "xyzw"[k]
                else:
                    sem = u + "." + "xyzw"[k]
            elif v in frame:
                sem = frame[v]
            elif vs_constant(s, s["VS"], defs, v):
                sem = vs_constant(s, s["VS"], defs, v)
            elif col == 3 and view_space(s["VS"], row, col):
                sem = view_space(s["VS"], row, col)
            else:
                el, buf = slice_info(defs, v)
                names = {usage[e] if e < len(usage) else "SV_InstanceID" for e in el}
                if AGNOSTIC:
                    deltas = {e for e in el if e < len(usage) and usage[e].endswith(":Half4")}
                    names = {"Delta" if n.endswith(":Half4") else n for n in names}
                pos_kind = position_kind(defs, v, usage) if col < 3 else None
                if pos_kind:
                    sem = pos_kind + "." + "xyzw"[col]
                elif view_fade(defs, v):
                    sem = "ViewFade"
                elif "Pos" in names and buf and col < 3:
                    sem = "?WorldPos." + "xyzw"[col]  # tentative: skinning also reads buffers
                elif "Pos" in names and not buf and names <= {"Pos", "Delta", "SV_InstanceID"} and col < 3:
                    sem = "?ObjectPos." + "xyzw"[col]
                    if AGNOSTIC:
                        ASSUMED.update({str(e): "Delta" for e in deltas})
                elif names <= {"SV_InstanceID"} and buf and re.match(r"extractvalue %dx\.types\.ResRet\.f32 %\d+, \d", d):
                    sem = "ObjectOrigin." + "xyzw"[col]
                else:
                    sem = "Computed"
            if AGNOSTIC and sem.lstrip("?").startswith(("ObjectPos", "WorldPos")):
                ASSUMED["0"] = "Pos"
            found[(row, col)].add(sem)
        evidence.append({"VS": s["VS"], "Layout": list(usage)})
    if layout is not None and real == 0 and AGNOSTIC:
        # Constant-stub vertex programs only; other declarations' routing cannot be transferred without usages.
        return {}, [{"Evidence": "layout's vertex programs are constant stubs; routing unknown", "Layout": list(layout)}]
    if layout is not None and real == 0:
        # Every vertex program paired for this layout is a constant-output stub (skinned layouts in this DB):
        # use the routing of the real vertex programs, but only where they agree unanimously.
        merged, evidence = ps_input_semantics(shader, ps, programs, layouts, frame_rows, None)
        merged = {k: v for k, v in merged.items() if len(v) == 1}
        return merged, [{"Evidence": "layout's vertex programs are constant stubs; unanimous routing of the other "
                                     "layouts used", "Layout": list(layout)}] + evidence
    merged = {}
    for key, names in found.items():
        definitive = {n for n in names if not n.startswith("?")}
        tentative = {n[1:] for n in names if n.startswith("?")}
        merged[key] = definitive if definitive and (not tentative or tentative <= definitive or len(definitive) == 1) else (definitive | tentative)
    return merged, evidence


# ------------------------------------------------------------------ DAG post-processing
def frame_rows_of(roots):
    """Rows that appear as a consecutive triple of rowdots against the same vector."""
    by_vec = defaultdict(set)
    for x in dt.topo([v for _, v in roots]):
        if x.op == "rowdot":
            by_vec[x.args[2]].add(x.args[1])
    triples = set()
    for rows in by_vec.values():
        for r in rows:
            if {r, r + 1, r + 2} <= rows:
                triples.add((r, r + 1, r + 2))
    if len(triples) > 1:
        raise ValueError("Several tangent frames: %s" % triples)
    return set(next(iter(triples))) if triples else set()


def lower_rowdots(roots, frame):
    """Frame-row dots -> frame(vec, k, sig, r0); other row dots -> explicit arithmetic."""
    def fn(x, y):
        if y.op != "rowdot":
            return None
        sig, row, vec = y.args
        if row in frame:
            return E("frame", vec, row - min(frame), sig, min(frame))
        r = 0.0
        for c in range(3):
            r = dx.add(r, dx.mul(E("in", sig, row, c), vec[c]))
        return r
    labels = [l for l, _ in roots]
    return list(zip(labels, dt.transform([v for _, v in roots], fn)))


def name_inputs(roots, sem_in, frame):
    """Replace interpolant leaves by semantic inputs; tangent-frame products become frame(vec, k)."""
    unresolved = set()
    def fn(x, y):
        if y.op == "in":
            names = sem_in.get((y.args[1], y.args[2]), {"Missing"})
            name = next(iter(names)) if len(names) == 1 else "Inconsistent:" + "|".join(sorted(names))
            if name.startswith(("Inconsistent", "Missing", "Computed")):
                desc = "IN%d[%d].%s=%s" % (y.args[0], y.args[1], dx.XYZW[y.args[2]], name)
                unresolved.add(desc)
                return E("input", "Unresolved:" + desc)
            return E("input", name)
        if y.op == "frame" and len(y.args) == 4:
            return E("frame", y.args[0], y.args[1])
        return None
    labels = [l for l, _ in roots]
    out = list(zip(labels, dt.transform([v for _, v in roots], fn)))
    return out, unresolved


def face_axes(expr):
    """Normal components from the cube-face selection tree (5/4 -> z, 3/2 -> y, 1/0 -> x)."""
    axes = {}
    for x in dt.topo([expr]):
        if x.op == "select" and is_num(x.args[1]) and is_num(x.args[2]):
            pair = (x.args[1], x.args[2])
            axis = {(5, 4): 2, (3, 2): 1, (1, 0): 0, (5.0, 4.0): 2, (3.0, 2.0): 1, (1.0, 0.0): 0}.get(pair)
            c = x.args[0]
            if axis is None or not (isinstance(c, E) and c.op in ("fcmp_olt", "fcmp_ult") and c.args[1] == 0):
                continue
            comp = c.args[0]
            if isinstance(comp, E) and comp.op == "mul":
                rest = [a for a in comp.args if not (isinstance(a, E) and a.op == "rsqrt")]
                comp = rest[0] if len(rest) == 1 else comp
            axes[axis] = comp
    return [axes.get(i) for i in range(3)] if len(axes) == 3 else None


def semantic_outputs(roots, targets):
    r = dict(roots)
    out, notes = {}, []
    n = face_axes(r["RT0.w"])
    if n is None:
        raise ValueError("Normal encoding not recognized")
    out["Normal"] = n
    s = bp.extract_smoothness(r["RT0.z"])
    if s is None:
        raise ValueError("Smoothness encoding not recognized")
    out["Smoothness"] = s
    out["BaseColor"] = [r["RT1.x"], r["RT1.y"], r["RT1.z"]]
    out["Metallic"] = r["RT2.y"]
    out["RT1.w"] = r["RT1.w"]
    out["RT2.x"] = r["RT2.x"]
    out["RT2.z"] = r["RT2.z"]
    out["ShadingId"] = r["RT2.w"]
    if "DISCARD" in r and r["DISCARD"] is not False:
        out["Discard"] = r["DISCARD"]
    if targets >= 4:
        out["Emissive"] = [r["RT3.x"], r["RT3.y"], r["RT3.z"]]
    if targets == 5:
        q = {k: bp.quantized(r[k]) for k in ("RT4.x", "RT4.y", "RT4.z", "RT4.w")}
        coat_s = [x for shift, scale, x in q["RT4.z"] if scale == 255 and shift == 8]
        if len(coat_s) == 1:
            out["CoatSmoothness"] = coat_s[0]
        cn = face_axes(r["RT4.x"])
        if cn:
            out["CoatNormal"] = cn
        colors = sorted(((shift, x) for shift, scale, x in q["RT4.x"] if scale == 255), key=lambda t: -t[0])
        if len(colors) == 3:
            # Stored as 8-bit sqrt(value): decode as value = stored^2 (encoding only; lighting meaning unknown).
            out["RT4Color"] = [dx.mul(c, c) for _, c in colors]
    return out


# ------------------------------------------------------------------ serialization
class Serializer:
    def __init__(self, bind, params, semantics, slot_table):
        self.bind, self.params, self.sem, self.slots = bind, params, semantics, slot_table
        self.nodes, self.ids, self.unresolved, self.engine = [], {}, set(), set()

    def ref(self, v):
        if isinstance(v, bool): return {"b": v}
        if is_num(v): return {"c": float(v)} if isinstance(v, float) else {"i": int(v)}
        return {"n": self.add(v)}

    def add(self, x):
        if x in self.ids:
            return self.ids[x]
        o = x.op
        if o == "tex":
            for c in x.args[2]:
                if isinstance(c, E): self.add(c)
            lod = dict(x.args[3]).get("lod")
            if isinstance(lod, E): self.add(lod)
        else:
            for c in dt.children(x):
                self.add(c)
        if o == "input":
            rec = {"op": "input", "name": x.args[0]}
        elif o == "in":
            key = (x.args[1], x.args[2])
            names = self.sem.get(key, {"Missing"})
            name = next(iter(names)) if len(names) == 1 else "Inconsistent:" + "|".join(sorted(names))
            if name.startswith(("Inconsistent", "Missing", "Computed")):
                self.unresolved.add("IN%d[%d].%s=%s" % (x.args[0], x.args[1], dx.XYZW[x.args[2]], name))
            rec = {"op": "input", "name": name}
        elif o == "cb":
            b, reg, c, kind = x.args
            if b == self.bind and is_num(reg) and reg in self.params:
                p = self.params[reg]
                rec = {"op": "param", "name": p["Name"], "c": c, "int": kind == "i32" or p["Type"] == 1}
            else:
                name = VIEW_SEMANTICS.get((reg, c)) if is_num(reg) and b == VIEW_BIND else None
                if name is None and b != VIEW_BIND and is_num(reg):
                    name = "Engine:cb%d[%s].%s" % (b, reg, dx.XYZW[c])
                    self.engine.add(name)
                elif name is None:
                    self.unresolved.add("cb%d[%s].%s" % (b, reg, dx.XYZW[c]))
                    name = "View:%s.%s" % (reg, dx.XYZW[c])
                rec = {"op": "view", "name": name}
        elif o == "tex":
            kind, slot, coords, extra = x.args
            if slot not in self.slots:
                self.unresolved.add("t%d" % slot)
            rec = {"op": "tex", "slot": slot, "kind": kind, "coords": [self.ref(c) for c in coords]}
            if kind == "sampleLevel":
                rec["lod"] = self.ref(dict(extra).get("lod", 0.0))
        elif o == "ch":
            rec = {"op": "ch", "args": [self.ref(x.args[0]), {"i": x.args[1]}]}
        elif o == "lookup":
            rec = {"op": "lookup", "table": dt.LOOKUPS[x.args[0]], "args": [self.ref(x.args[1])]}
        elif o == "frame":
            rec = {"op": "frame", "args": [self.ref(c) for c in x.args[0]], "k": x.args[1]}
        elif o in ("undef", "status", "memload", "rowdot"):
            self.unresolved.add(o)
            rec = {"op": o}
        else:
            rec = {"op": o, "args": [self.ref(a) for a in x.args]}
        self.ids[x] = len(self.nodes)
        self.nodes.append(rec)
        return self.ids[x]


def compile_shader(shader, ps, doc, states, root, programs, parsed, layouts, layout=None):
    consts, sol = ap.constants_for(parsed, programs, shader, ps)
    ext = {v["Name"].casefold(): v for v in consts["ExternalValues"]}
    exposed = mp.overridden_params(shader, states, ext) | {n for n in mp.RUNTIME_EXPOSED if n.casefold() in ext}         | {v["Name"] for v in ext.values() if v["ParameterKey"].casefold() in RUNTIME_KEYS}
    bound = mp.bindings_for(shader, states, root)
    static = {k: v for k, v in mp.STATIC_UNDAMAGED.items() if k.casefold() in ext}
    ASSUMED.clear()
    res = bp.build(shader, ps, None, sorted(exposed), overrides=static, bound=bound, verbose=False)
    roots = res["roots"]
    targets = len({k.split(".")[0] for k, _ in res["full"] if k.startswith("RT")})
    frame = frame_rows_of(res["full"]) or frame_rows_of(roots)
    roots = lower_rowdots(roots, frame)
    sem_in, vs_evidence = ps_input_semantics(shader, ps, programs, layouts, frame, layout)
    if not frame:
        # No tangent frame anywhere in the program: an interpolant row encoded unperturbed as the
        # G-buffer normal is the vertex normal.
        comps = face_axes(dict(roots)["RT0.w"])
        if comps and all(isinstance(c, E) and c.op == "in" for c in comps) and len({c.args[1] for c in comps}) == 1                 and [c.args[2] for c in comps] == [0, 1, 2]:
            row = comps[0].args[1]
            for c in range(3):
                if sem_in.get((row, c)) == {"Computed"}:
                    sem_in[(row, c)] = {"WorldNormal." + "xyz"[c]}
    roots, unresolved_inputs = name_inputs(roots, sem_in, frame)
    out = semantic_outputs(roots, targets)
    params = {v["Index"] - 1 - consts.get("ValueStart", 0): v for v in consts["ExternalValues"] if v["Name"] in res["exposed"]}
    slot_table = {}
    for i, info in res["slots"].items():
        a = next((a for a in res["assumptions"] if a["Slot"] == i), None)
        slot_table[i] = {**info, "Folded": a}
    ser = Serializer(res["bind"], params, sem_in, slot_table)
    outputs, omitted = {}, {}
    # Reporting-only outputs are omitted (not serialized) when they need unresolved inputs.
    optional = ("RT1.w", "RT2.z", "RT4Color", "Emissive")
    for k in sorted(out, key=lambda k: k in optional):
        v = out[k]
        if k in optional:
            probe = Serializer(res["bind"], params, sem_in, slot_table)
            for x in (v if isinstance(v, list) else [v]):
                probe.ref(x)
            conditional = [n["name"] for n in probe.nodes if n["op"] in ("input", "view")
                           and n["name"].startswith(("Unresolved:", "Engine:", "View:"))]
            if probe.unresolved or conditional:
                probe.unresolved |= set(conditional)
                omitted[k] = sorted(probe.unresolved)
                continue
        outputs[k] = [ser.ref(x) for x in v] if isinstance(v, list) else ser.ref(v)
    used_slots = sorted({n["slot"] for n in ser.nodes if n["op"] == "tex"})
    used_inputs = {n["name"] for n in ser.nodes if n["op"] == "input"}
    unresolved_inputs = {u for u in unresolved_inputs if "Unresolved:" + u in used_inputs}
    ser.engine = {e for e in ser.engine if any(n["op"] == "view" and n["name"] == e for n in ser.nodes)}
    return {
        "Shader": shader, "PS": ps, "Targets": targets, "SolutionCount": None,
        "Externals": [{"Name": v["Name"], "Key": v["ParameterKey"], "Index": v["Index"], "Width": v["Width"],
                       "Type": v["Type"], "Default": v["Value"], "Exposed": v["Name"] in res["exposed"]}
                      for v in consts["ExternalValues"]],
        "Slots": {str(i): {k: v for k, v in slot_table[i].items()} for i in used_slots},
        "FoldedSlots": [a for a in res["assumptions"]],
        "BoundAtProfileBuild": bound,
        "FrameRows": sorted(frame),
        "InputEvidence": vs_evidence[:6],
        "StaticOverrides": static,
        "Nodes": ser.nodes, "Outputs": outputs, "OmittedOutputs": omitted,
        "Unresolved": sorted(ser.unresolved),
        "ConditionalInputs": sorted(unresolved_inputs | ser.engine),
        "AssumedUsages": dict(ASSUMED),
        "Verification": {"FullNodes": dt.count(res["full"]), "SimplifiedNodes": len(ser.nodes),
                         "MaxAbsDifference": {k: v[0] for k, v in res["check"].items()}},
    }, res, roots, out


ENGINE_ZERO_MAX_EFFECT = 0.1


def engine_constants(roots, external_bind, view_bind=2):
    return [x for x in dt.topo([v for _, v in roots]) if x.op == "cb" and x.args[0] not in (external_bind, view_bind)]


def engine_effect(roots, engine, n=20000):
    """Max |output(c) - output(0)| for engine constants c in {0.25, 1, 4} on shared continuous random inputs."""
    worst = 0.0
    zero = set(engine)
    for value in (0.25, 1.0, 4.0):
        a = dt.evaluate([v for _, v in roots], dt.random_leaf_factory(n, np.random.default_rng(5), [(lambda x: x in zero, 0.0)], True), n)
        b = dt.evaluate([v for _, v in roots], dt.random_leaf_factory(n, np.random.default_rng(5), [(lambda x: x in zero, value)], True), n)
        for _, v in roots:
            d = np.abs(np.asarray(dt._get(v, a, n), dtype=float) - np.asarray(dt._get(v, b, n), dtype=float))
            worst = max(worst, float(np.nanmax(d)) if np.isfinite(d).any() else 0.0)
    return worst


def mul_factors(x):
    """Multiplicative factors of x (through saturate is NOT allowed; caller strips it)."""
    if isinstance(x, E) and x.op == "mul":
        return mul_factors(x.args[0]) + mul_factors(x.args[1])
    return [x]


def compile_forward(shader, ps, doc, states, root, programs, parsed, layouts, layout=None):
    """Dual-source forward glass: target 1 is the per-channel transmittance, computed before lighting."""
    consts, sol = ap.constants_for(parsed, programs, shader, ps)
    ext = {v["Name"].casefold(): v for v in consts["ExternalValues"]}
    exposed = mp.overridden_params(shader, states, ext) | {n for n in mp.RUNTIME_EXPOSED if n.casefold() in ext}         | {v["Name"] for v in ext.values() if v["ParameterKey"].casefold() in RUNTIME_KEYS}
    bound = mp.bindings_for(shader, states, root)
    dx.OPAQUE_LOOPS = True
    ASSUMED.clear()
    try:
        static = {k: v for k, v in mp.STATIC_UNDAMAGED.items() if k.casefold() in ext}
        res = bp.build(shader, ps, None, sorted(exposed), overrides=static, bound=bound, verbose=False, targets={1})
    finally:
        dx.OPAQUE_LOOPS = False
    roots = res["roots"]
    for x in dt.topo([v for _, v in roots]):
        if x.op in ("loopcarried", "backedge"):
            raise ValueError("Transmittance depends on lighting loops")
    frame = frame_rows_of(res["full"]) or frame_rows_of(roots)
    roots = lower_rowdots(roots, frame)
    sem_in, vs_evidence = ps_input_semantics(shader, ps, programs, layouts, frame, layout)
    roots, unresolved_inputs = name_inputs(roots, sem_in, frame)
    r = dict(roots)
    channels = [r["RT1.x"], r["RT1.y"], r["RT1.z"]]
    out = {"Transmittance": channels}
    inner = [c.args[0] if isinstance(c, E) and c.op == "saturate" else c for c in channels]
    common = None
    for c in inner:
        f = {x for x in mul_factors(c) if isinstance(x, E)}
        common = f if common is None else common & f
    if common and len(common) == 1:
        out["Reflectance"] = dx.sub(1.0, next(iter(common)))
    params = {v["Index"] - 1 - consts.get("ValueStart", 0): v for v in consts["ExternalValues"] if v["Name"] in res["exposed"]}
    slot_table = {i: {**info, "Folded": next((a for a in res["assumptions"] if a["Slot"] == i), None)}
                  for i, info in res["slots"].items()}
    ser = Serializer(res["bind"], params, sem_in, slot_table)
    outputs = {k: [ser.ref(x) for x in v] if isinstance(v, list) else ser.ref(v) for k, v in out.items()}
    used_slots = sorted({n["slot"] for n in ser.nodes if n["op"] == "tex"})
    return {
        "Shader": shader, "PS": ps, "Kind": "forward_transmittance", "Targets": 2, "SolutionCount": None,
        "Externals": [{"Name": v["Name"], "Key": v["ParameterKey"], "Index": v["Index"], "Width": v["Width"],
                       "Type": v["Type"], "Default": v["Value"], "Exposed": v["Name"] in res["exposed"]}
                      for v in consts["ExternalValues"]],
        "Slots": {str(i): slot_table[i] for i in used_slots}, "FoldedSlots": res["assumptions"],
        "BoundAtProfileBuild": bound, "FrameRows": sorted(frame), "InputEvidence": vs_evidence[:6],
        "StaticOverrides": static,
        "Nodes": ser.nodes, "Outputs": outputs, "Unresolved": sorted(ser.unresolved),
        "ConditionalInputs": sorted(unresolved_inputs | ser.engine),
        "AssumedUsages": dict(ASSUMED),
        "Verification": {"FullNodes": dt.count(res["full"]), "SimplifiedNodes": len(ser.nodes),
                         "MaxAbsDifference": {k: v[0] for k, v in res["check"].items()}},
    }, res, roots, out


def equivalent(a_out, b_out, n=8000):
    """Numerically compare two variants' semantic outputs (shared leaf semantics)."""
    ra = [(k + str(i), x) for k, v in a_out.items() for i, x in enumerate(v if isinstance(v, list) else [v]) if k != "ShadingId"]
    rb = [(k + str(i), x) for k, v in b_out.items() for i, x in enumerate(v if isinstance(v, list) else [v]) if k != "ShadingId"]
    if [l for l, _ in ra] != [l for l, _ in rb]:
        return {"labels": "differ"}
    diff = dt.compare(ra, rb, n=n)
    return {k: v[0] for k, v in diff.items() if v[0] > 1e-4}


CONNECTED = ("BaseColor", "Metallic", "Smoothness", "Normal", "CoatSmoothness", "CoatNormal", "RT2.x",
             "Discard", "Transmittance", "Reflectance")


def entry_key(prof):
    return hashlib.sha256(json.dumps([prof["Nodes"], prof["Outputs"]], sort_keys=True).encode()).hexdigest()


def compile_entries(shader, candidates, compile_fn, doc, states, root, programs, parsed, layouts, report):
    """One entry per distinct compiled result; each lists the programs and vertex layouts it serves."""
    entries = {}
    for count, ps in candidates:
        for layout, solutions in sorted(program_layouts(shader, ps, programs, layouts).items(), key=lambda x: -x[1]):
            try:
                prof, res, roots, sem = compile_fn(shader, ps, doc, states, root, programs, parsed, layouts, layout)
            except Exception as exc:
                report.setdefault("Errors", []).append({"PS": ps, "Layout": list(layout), "Error": repr(exc)})
                print(shader, ps[:8], "ERROR", repr(exc))
                continue
            key = entry_key(prof)
            if key not in entries:
                prof["Programs"], prof["Layouts"], prof["SolutionCount"] = [], [], 0
                entries[key] = (prof, sem)
            e = entries[key][0]
            if ps not in e["Programs"]:
                e["Programs"].append(ps)
            if list(layout) not in e["Layouts"]:
                e["Layouts"].append(list(layout))
            e["SolutionCount"] += solutions
    # Several distinct entries may serve one layout (permutation key unknown). The add-on decides after
    # specializing them with the material's and vehicle's actual values; the alternatives are kept here.
    return [prof for prof, _ in entries.values() if prof["Layouts"]]
