"""Compiled shader profiles: static-state G-buffer formulas translated into Blender nodes.

shader_profiles.json.gz is produced offline from the game's own compiled pixel programs (v293
vehicle shader database, DXC disassembly, symbolic evaluation). It contains formulas only, for every
shader and vertex declaration in the database (vehicle-agnostic, keyed by shader name hash). This module:
  1. matches a restored source material to a profile by exact shader identity,
  2. verifies every folded assumption against the actual material (parameters, bound textures),
  3. specializes the formulas with the material's own parameter values,
  4. emits Blender nodes and connects a Principled BSDF.
Unknown inputs fail closed: the slot stays unconnected and the reason is reported.
"""
import hashlib
import json
import math
from pathlib import Path

ENGINE_ZERO_MAX_EFFECT = 0.1
# Engine constants outside the shader database, read in a frame capture of the game (Lotus Evija, garage): the forward
# pixel shaders' function-constant buffer b0, row 1.x (scales the metal reflection of glass, lenses and livery windows).
ENGINE_VALUES = {"cb0[1].x": 1.0}
# Largest output difference tolerated between permutations of one vertex layout (light glass: see-through/reflection).
PERMUTATION_MAX = 0.1
PERMUTATION_GLASS_MAX = 0.12
# Runtime view constants the compiler could not resolve (cb2[44].w: the camera exposure in the cs_lglass lenses) are
# accepted only when the car's specialized outputs do not change at all across this range of values.
VIEW_CONSTANT_RANGE = (1e-5, 1e-4, 1e-3, 0.01, 0.1, 0.5, 2.0, 10.0, 100.0)
_PROFILES = None
# Runtime vehicle customization -> shader parameter, by parameter-key equality (see SHADER-FINDINGS).
# RaceVehicleCustomizationComponentData key field -> (RaceVehicleItemData field or None, component fallback field).
# The tints' keys drive Ext_Glass_Color (window glass), Ext_Headlight_Color and Ext_Taillight_Tint (light lenses).
RUNTIME_PAINT = {"PaintFacingColorParameter": ("DefaultPaint", "DefaultPaint"),
                 "PaintMaterialParameter": ("Material", "DefaultMaterial"),
                 "WindowsTintParameter": ("WindowsTint", "DefaultWindowsTint"),
                 "HeadlightsTintParameter": (None, "DefaultHeadlightsTint"),
                 "TaillightsTintParameter": (None, "DefaultTaillightsTint")}
OMITTED_REASON = "Output needs engine constants outside the shader database (e.g. exposure/day-night view constants); omitted"
UNSUPPORTED_OUTPUTS = {
    "RT1.w": "G-buffer occlusion/specular-occlusion term (vertex color ambient treatment) has no Principled input",
    "RT2.z": "G-buffer diffuse occlusion term has no Principled input",
    "RT4Color": "Car-paint second-layer color in the fifth G-buffer target; its deferred-lighting use is unknown",
}


def profiles():
    global _PROFILES
    if _PROFILES is None:
        import gzip
        packed = Path(__file__).with_name("shader_profiles.json.gz")
        _PROFILES = json.loads(gzip.decompress(packed.read_bytes()).decode("utf-8"))
    return _PROFILES


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def shader_key(asset):
    """Shader database key: DJB2-xor hash of the lower-case shader asset name."""
    h = 5381
    for c in (asset or "").lower().encode("utf-8"):
        h = ((h * 33) ^ c) & 0xFFFFFFFF
    return str(h)


def profile_for(state):
    return profiles()["Profiles"].get(shader_key((state.get("Shader") or {}).get("Asset") or ""))


def report_for(asset):
    report = profiles().get("Report", {})
    return report.get(shader_key(asset)) or {}


# ------------------------------------------------------------------ runtime vehicle inputs
def runtime_values(assembly_path):
    """{parameter key: [x, y, z, w?]} from RaceVehicleCustomizationComponentData keys and RaceVehicleItemData values."""
    if not assembly_path or not Path(assembly_path).is_file():
        return {}, ["assembly.json not found; runtime paint unavailable"], None
    doc = json.loads(Path(assembly_path).read_text(encoding="utf-8-sig"))
    raws = [n.get("Raw", {}) for n in doc.get("Nodes", [])]
    comps = [r for r in raws if r.get("Type") == "RaceVehicleCustomizationComponentData"]
    items = [r for r in raws if r.get("Type") == "RaceVehicleItemData"]
    notes, out = [], {}
    if len(comps) != 1:
        return {}, ["Expected one RaceVehicleCustomizationComponentData, found %d" % len(comps)], doc
    for field, (item_field, fallback) in RUNTIME_PAINT.items():
        key = ((comps[0].get(field) or {}).get("ShaderParameterHandle") or {}).get("Data")
        if not key:
            continue
        source = items[0].get(item_field) if item_field and len(items) == 1 else None
        origin = "RaceVehicleItemData.%s" % item_field
        if not isinstance(source, dict):
            source = comps[0].get(fallback)
            origin = "RaceVehicleCustomizationComponentData." + fallback
            if item_field:
                notes.append(field + ": no unique RaceVehicleItemData value; component default used")
        if isinstance(source, dict):
            out[key.casefold()] = {"Value": [float(source.get(c, 0.0)) for c in "xyz"], "Origin": origin, "Field": field}
    # Wheel customization: (Front|Rear)(Rim|Caliper)(Primary|Secondary)(Color|Material)Parameter keys take the
    # default item of that type and location (RimsItemData / CalipersItemData Primary/SecondaryPaint|Material).
    import re
    for field, value in comps[0].items():
        m = re.fullmatch(r"(Front|Rear)(Rim|Caliper)(Primary|Secondary)(Color|Material)Parameter", field)
        key = ((value or {}).get("ShaderParameterHandle") or {}).get("Data") if isinstance(value, dict) else None
        if not m or not key:
            continue
        kind = {"Rim": "RimsItemData", "Caliper": "CalipersItemData"}[m.group(2)]
        loc = "ItemPosition_" + m.group(1)
        items_here = [i for i in doc.get("Items", []) if i.get("Type") == kind and i.get("Default")
                      and ((i.get("Raw") or {}).get("Location") or {}).get("Name") == loc]
        item_field = m.group(3) + ("Paint" if m.group(4) == "Color" else "Material")
        if len(items_here) != 1 or not isinstance(items_here[0]["Raw"].get(item_field), dict):
            notes.append("%s: %d default %s at %s; not applied" % (field, len(items_here), kind, loc))
            continue
        v = items_here[0]["Raw"][item_field]
        out[key.casefold()] = {"Value": [float(v.get(c, 0.0)) for c in "xyz"], "Field": field,
                               "Origin": "%s %s.%s" % (kind, items_here[0].get("Asset", "").rsplit("/", 1)[-1], item_field)}
    return out, notes, doc


# ------------------------------------------------------------------ specialization
def _f(v):
    return float(v) if not isinstance(v, bool) else (1.0 if v else 0.0)


def _fold(op, a):
    """Scalar semantics for constant arguments (booleans as Python bool, integers as int)."""
    try:
        if op == "add": return a[0] + a[1]
        if op == "sub": return a[0] - a[1]
        if op == "mul": return a[0] * a[1]
        if op == "div": return a[0] / a[1] if a[1] != 0 else (math.copysign(math.inf, a[0]) if a[0] else math.nan)
        if op == "neg": return -a[0]
        if op == "max": return max(a[0], a[1])
        if op == "min": return min(a[0], a[1])
        if op == "abs": return abs(a[0])
        if op == "saturate": return min(max(a[0], 0.0), 1.0)
        if op == "sqrt": return math.sqrt(a[0]) if a[0] >= 0 else math.nan
        if op == "rsqrt": return 1 / math.sqrt(a[0]) if a[0] > 0 else math.inf
        if op == "exp2": return 2.0 ** a[0]
        if op == "log2": return math.log2(a[0]) if a[0] > 0 else -math.inf
        if op == "frac": return a[0] - math.floor(a[0])
        if op == "floor": return float(math.floor(a[0]))
        if op == "ceil": return float(math.ceil(a[0]))
        if op == "trunc": return float(math.trunc(a[0]))
        if op == "round_ne": return float(round(a[0]))
        if op in ("sin", "cos", "tan", "acos", "asin", "atan"): return getattr(math, op)(a[0])
        if op == "fmod": return math.fmod(a[0], a[1])
        if op == "select": return a[1] if a[0] else a[2]
        if op == "and": return bool(a[0]) and bool(a[1])
        if op == "or": return bool(a[0]) or bool(a[1])
        if op == "not": return not a[0]
        if op == "xor": return bool(a[0]) != bool(a[1])
        if op.startswith("fcmp_") or op.startswith("icmp_"):
            p = op[5:]
            x, y = a
            return {"oeq": x == y, "ueq": x == y, "one": x != y, "une": x != y, "eq": x == y, "ne": x != y,
                    "olt": x < y, "ult": x < y, "slt": x < y, "ole": x <= y, "ule": x <= y, "sle": x <= y,
                    "ogt": x > y, "ugt": x > y, "sgt": x > y, "oge": x >= y, "uge": x >= y, "sge": x >= y}[p]
        if op in ("fptoui_i32", "fptosi_i32"): return int(math.trunc(a[0])) if math.isfinite(a[0]) else 0
        if op in ("uitofp_float", "sitofp_float", "zext_i32"): return float(a[0]) if op != "zext_i32" else int(a[0])
        if op in ("iadd", "isub", "imul", "iand", "ior", "ishl", "ilshr", "isrem"):
            x, y = int(a[0]), int(a[1])
            return {"iadd": x + y, "isub": x - y, "imul": x * y, "iand": x & y, "ior": x | y,
                    "ishl": x << (y & 31), "ilshr": (x & 0xffffffff) >> (y & 31),
                    "isrem": int(math.fmod(x, y)) if y else 0}[op]
        if op == "binop37": return max(int(a[0]), int(a[1]))
        if op == "binop38": return min(int(a[0]), int(a[1]))
    except (ValueError, OverflowError, ZeroDivisionError):
        return math.nan
    return None


class Spec:
    """Profile nodes specialized to concrete parameter values; live parameters stay symbolic."""

    def __init__(self, profile, values, live, input_consts=None, rename=None, tex_consts=None):
        self.profile, self.nodes, self.map = profile, [], {}
        self.input_consts = input_consts or {}
        self.rename = rename or {}
        self.tex_consts = tex_consts or {}
        for i, n in enumerate(profile["Nodes"]):
            self.map[i] = self._node(n, values, live)

    def ref(self, r):
        if "n" in r: return self.map[r["n"]]
        if "c" in r: return r["c"]
        if "i" in r: return r["i"]
        if "b" in r: return r["b"]
        raise ValueError(r)

    def _new(self, rec):
        self.nodes.append(rec)
        return ("N", len(self.nodes) - 1)

    def _node(self, n, values, live):
        op = n["op"]
        if op == "param":
            key = (n["name"], n["c"])
            if key in live:
                return self._new({"op": "param", "name": n["name"], "c": n["c"]})
            v = values[key]
            return int(v) if n.get("int") else float(v)
        if op in ("input", "view"):
            if op == "input" and n.get("name") in self.rename:
                n = dict(n, name=self.rename[n["name"]])
            if n.get("name") in self.input_consts:
                return float(self.input_consts[n["name"]])
            return self._new(dict(n))
        if op == "tex":
            if n["slot"] in self.tex_consts:
                return ("T", n["slot"])  # uniform texture: every sample is the same texel value
            return self._new({"op": "tex", "slot": n["slot"], "kind": n["kind"],
                              "coords": [self.ref(c) for c in n["coords"]]})
        if op == "ch":
            src = self.ref(n["args"][0])
            if isinstance(src, tuple) and src[0] == "T":
                return float(self.tex_consts[src[1]][n["args"][1]["i"]])
            return self._new({"op": "ch", "args": [src, n["args"][1]["i"]]})
        if op == "frame":
            return self._frame([self.ref(c) for c in n["args"]], n["k"])
        if op == "lookup":
            idx = self.ref(n["args"][0])
            if not isinstance(idx, tuple):
                table = n["table"]
                return table[max(0, min(len(table) - 1, int(idx)))]
            return self._new({"op": "lookup", "table": n["table"], "args": [idx]})
        return self._finish(op, [self.ref(a) for a in n["args"]])

    def _frame(self, args, k):
        if all(not isinstance(a, tuple) for a in args) and _f(args[0]) == 0 and _f(args[1]) == 0:
            # The frame's third column is the vertex normal interpolant itself: frame((0,0,c), k) = c * N_k.
            normal = self._new({"op": "input", "name": "WorldNormal." + "xyz"[k]})
            return normal if _f(args[2]) == 1 else self._new({"op": "mul", "args": [_f(args[2]), normal]})
        return self._new({"op": "frame", "args": args, "k": k})

    def _finish(self, op, args):
        if all(not isinstance(a, tuple) for a in args):
            r = _fold(op, args)
            if r is not None:
                return r
        # Light algebraic simplification with constants (same rules as the offline simplifier).
        if op == "select" and not isinstance(args[0], tuple):
            return args[1] if args[0] else args[2]
        if op == "select" and args[1] == args[2] and not isinstance(args[1], tuple):
            return args[1]
        if op == "mul" and any(not isinstance(a, tuple) and a == 0 for a in args):
            return 0.0
        if op == "mul" and not isinstance(args[0], tuple) and args[0] == 1: return args[1]
        if op == "mul" and not isinstance(args[1], tuple) and args[1] == 1: return args[0]
        if op == "add" and not isinstance(args[0], tuple) and args[0] == 0: return args[1]
        if op == "add" and not isinstance(args[1], tuple) and args[1] == 0: return args[0]
        if op == "sub" and not isinstance(args[1], tuple) and args[1] == 0: return args[0]
        if op == "and":
            if any(a is False for a in args): return False
            if args[0] is True: return args[1]
            if args[1] is True: return args[0]
        if op == "or":
            if any(a is True for a in args): return True
            if args[0] is False: return args[1]
            if args[1] is False: return args[0]
        return self._new({"op": op, "args": args})

    def substitute(self, consts):
        """Replace specialized nodes {index: constant} and fold again (used after the constant proof)."""
        old, self.nodes, remap = self.nodes, [], {}

        def r(a):
            if isinstance(a, tuple) and a[0] == "N":
                return remap[a[1]]
            return a
        for i, n in enumerate(old):
            op = n["op"]
            if i in consts:
                remap[i] = consts[i]
            elif op in ("input", "view", "param"):
                remap[i] = self._new(dict(n))
            elif op == "tex":
                remap[i] = self._new(dict(n, coords=[r(c) for c in n["coords"]]))
            elif op == "ch":
                remap[i] = self._new({"op": "ch", "args": [r(n["args"][0]), n["args"][1]]})
            elif op == "frame":
                remap[i] = self._frame([r(a) for a in n["args"]], n["k"])
            elif op == "lookup":
                idx = r(n["args"][0])
                remap[i] = (n["table"][max(0, min(len(n["table"]) - 1, int(idx)))] if not isinstance(idx, tuple)
                            else self._new({"op": "lookup", "table": n["table"], "args": [idx]}))
            else:
                remap[i] = self._finish(op, [r(a) for a in n["args"]])
        self.map = {k: r(v) for k, v in self.map.items()}

    def output(self, name):
        o = self.profile["Outputs"].get(name)
        if o is None:
            return None
        return [self.ref(r) for r in o] if isinstance(o, list) else self.ref(o)


# ------------------------------------------------------------------ verification of folded assumptions
def parameter_values(profile, state, runtime):
    """Concrete values for every external parameter, with fail-closed checks for non-exposed overrides."""
    by_name = {}
    for p in state["Parameters"].get("VectorParameters", {}).values():
        name = p.get("ParameterName")
        name = name.get("Value") if isinstance(name, dict) else name
        value = p.get("Value", {})
        if isinstance(value, dict):
            by_name[name.casefold()] = [float(value.get(c, 0.0)) for c in "xyzw"]
    for p in state["Parameters"].get("BoolParameters", {}).values():
        name = p.get("ParameterName")
        name = name.get("Value") if isinstance(name, dict) else name
        by_name[name.casefold()] = [1.0 if p.get("Value") else 0.0] * 4
    values, applied, issues = {}, [], []
    static = profile.get("StaticOverrides", {})
    for e in profile["Externals"]:
        default = list(static.get(e["Name"], e["Default"]))
        if e["Type"] == 1 and e["Name"] not in static:
            default = [float(int.from_bytes(__import__("struct").pack("<f", x), "little")) for x in default]
        v = by_name.get(e["Name"].casefold(), default)
        rt = runtime.get(e["Key"].casefold())
        chosen = (state.get("ParameterOverrides") or {}).get(e["Name"])
        if chosen is not None:
            # A runtime value the player sets in the game (the license plate text), chosen in the sidebar.
            v = [float(x) for x in chosen] + v[len(chosen):]
            applied.append({"Parameter": e["Name"], "Value": v, "Origin": "chosen in the An's Garage sidebar",
                            "Precedence": "player setting in the game; not stored in the vehicle's data"})
        elif rt:
            v = rt["Value"] + default[len(rt["Value"]):]
            applied.append({"Parameter": e["Name"], "Value": v, "Origin": rt["Origin"],
                            "Precedence": "runtime vehicle parameter overrides material value"
                            if e["Name"].casefold() in by_name else "runtime vehicle parameter"})
        elif not e["Exposed"] and any(abs(a - b) > 1e-6 for a, b in zip(v, default)):
            issues.append("Parameter %s differs from the profile's folded default" % e["Name"])
        for c in range(4):
            values[(e["Name"], c)] = v[c]
    return values, applied, issues


def check_bindings(profile, state, root, image_loader):
    """Folded texture slots must match the actual binding; returns {slot: image source} for sampled slots."""
    bindings = {b["Parameter"].casefold(): b for b in state["TextureBindings"]}
    overrides = {k.casefold(): v for k, v in (state.get("TextureOverrides") or {}).items()}
    issues, sources = [], {}
    built = {k.casefold(): v for k, v in profile.get("BoundAtProfileBuild", {}).items()}
    for k, v in built.items():
        if v == "image" or k not in bindings:
            continue
        b = bindings[k]
        try:
            uniform = image_loader.uniform(root, b)
        except Exception as exc:
            issues.append("Cannot verify folded texture %s: %s" % (b["Parameter"], exc))
            continue
        if uniform is None or any(abs(a - c) > 1.5 / 255 for a, c in zip(uniform, v)):
            issues.append("Texture %s is not the uniform value the profile folded" % b["Parameter"])
    for slot, info in profile["Slots"].items():
        p = (info.get("Parameter") or "").casefold()
        if p and p in overrides:
            sources[int(slot)] = ("default", overrides[p])  # item-level shader override (exported texture by asset)
        elif p and p in bindings:
            sources[int(slot)] = ("binding", bindings[p])
        elif info.get("DefaultAsset"):
            sources[int(slot)] = ("default", info["DefaultAsset"])
        elif p and not info.get("DefaultHash"):
            # Same rule the offline compiler applies: a runtime-bound texture (damage, dirt) without a shader default
            # and without a material binding samples as zero in the static undamaged state.
            sources[int(slot)] = ("zero", "runtime-bound texture %s without binding or shader default; static "
                                          "undamaged state assumes zero" % info.get("Parameter"))
        else:
            issues.append("Texture slot t%s has no binding or shader default" % slot)
        if info.get("Dim") not in ("2d", "2darray") and sources.get(int(slot), ("",))[0] != "zero":
            sources[int(slot)] = ("unsupported", "%s texture (%s)" % (info.get("Dim"), info.get("DefaultAsset") or p))
    return sources, issues


# ------------------------------------------------------------------ Blender node emission
MATH = {"add": "ADD", "sub": "SUBTRACT", "mul": "MULTIPLY", "div": "DIVIDE", "max": "MAXIMUM", "min": "MINIMUM",
        "abs": "ABSOLUTE", "sqrt": "SQRT", "rsqrt": "INVERSE_SQRT", "frac": "FRACT", "floor": "FLOOR",
        "ceil": "CEIL", "trunc": "TRUNC", "round_ne": "ROUND", "sin": "SINE", "cos": "COSINE", "tan": "TANGENT",
        "acos": "ARCCOSINE", "asin": "ARCSINE", "atan": "ARCTANGENT", "fmod": "MODULO", "isrem": "MODULO",
        "iadd": "ADD", "isub": "SUBTRACT", "imul": "MULTIPLY", "binop37": "MAXIMUM", "binop38": "MINIMUM",
        "fptoui_i32": "TRUNC", "fptosi_i32": "TRUNC"}
IDENTITY = {"uitofp_float", "sitofp_float", "zext_i32"}


class Unsupported(Exception):
    pass


# Shader node trees update in full after every node, link or value written, so one big tree costs the square of its
# size to build. Formulas go into nested groups of at most this many nodes instead (renderers flatten groups).
PART_NODE_LIMIT = 120
SOCKET_TYPES = {"VALUE": "NodeSocketFloat", "VECTOR": "NodeSocketVector", "RGBA": "NodeSocketColor"}


def group_nodes(tree):
    """Every node of a tree and of the groups nested in it."""
    for n in tree.nodes:
        yield n
        if n.type == "GROUP" and n.node_tree:
            yield from group_nodes(n.node_tree)


class NodeBuilder:
    """Emit one specialized profile into a node tree. Values are Python numbers or output sockets."""

    def __init__(self, tree, spec, ctx):
        self.t, self.spec, self.ctx = tree, spec, ctx
        self.main = tree
        self.memo, self.shared, self.column = {}, {}, {}
        self.count = {tree.name: len(tree.nodes)}
        self.parts, self.imports = {}, {}  # part tree name -> (group node in main, input node, output node)

    # -- primitives
    def node(self, kind):
        if self.count[self.t.name] >= PART_NODE_LIMIT:
            self._new_part()
        self.count[self.t.name] += 1
        return self.t.nodes.new(kind)

    def _new_part(self):
        import bpy
        k = len(self.parts) + 1
        part = bpy.data.node_groups.new("%s | part %d" % (self.main.name, k), "ShaderNodeTree")
        gin, gout = part.nodes.new("NodeGroupInput"), part.nodes.new("NodeGroupOutput")
        gin.location, gout.location = (-2800, 0), (3200, 0)
        gnode = self.main.nodes.new("ShaderNodeGroup")
        gnode.node_tree, gnode.label = part, "Formula part %d" % k
        gnode.location = (-2400 + 300 * k, 2000)
        self.parts[part.name] = (gnode, gin, gout)
        self.count[part.name] = 2
        self.t, self.column = part, {}

    def link(self, a, b):
        tree = b.id_data
        tree.links.new(self.into(a, tree), b)

    def into(self, s, tree):
        """Output socket `s` as seen inside `tree`: passed out of its part and into `tree` through group sockets."""
        src = s.id_data
        if src == tree:
            return s
        key = (s.as_pointer(), tree.name)
        if key not in self.imports:
            if src != self.main and tree != self.main:
                self.imports[key] = self.into(self.into(s, self.main), tree)
                return self.imports[key]
            name = "v%d" % len(self.imports)
            if src != self.main:  # out of a part into the main tree
                gnode, _, gout = self.parts[src.name]
                src.interface.new_socket(name=name, in_out="OUTPUT", socket_type=SOCKET_TYPES[s.type])
                src.links.new(s, gout.inputs[name])
                self.imports[key] = gnode.outputs[name]
            else:  # from the main tree into a part
                gnode, gin, _ = self.parts[tree.name]
                tree.interface.new_socket(name=name, in_out="INPUT", socket_type=SOCKET_TYPES[s.type])
                self.main.links.new(s, gnode.inputs[name])
                self.imports[key] = gin.outputs[name]
        return self.imports[key]

    def export(self, v):
        """A value as a number or a socket of the main tree."""
        return v if isinstance(v, (bool, int, float)) else self.into(v, self.main)

    def _place(self, node, depth):
        y = self.column.get(depth, 0)
        node.location = (-2400 + depth * 170, 1200 - y)
        self.column[depth] = y + 150

    def _set(self, sock, v):
        if isinstance(v, (bool, int, float)):
            sock.default_value = _f(v)
        else:
            self.link(v, sock)

    def math(self, operation, a, b=None, c=None, clamp=False, depth=10, label=""):
        n = self.node("ShaderNodeMath")
        n.operation, n.use_clamp = operation, clamp
        if label:
            n.label = label
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self._set(n.inputs[i], v)
        self._place(n, depth)
        return n.outputs[0]

    def separate(self, vec_socket, key, depth=2):
        if key not in self.shared:
            n = self.node("ShaderNodeSeparateXYZ")
            self.link(vec_socket, n.inputs[0])
            self._place(n, depth)
            self.shared[key] = n
        return self.shared[key]

    def combine(self, xyz, depth=12):
        n = self.node("ShaderNodeCombineXYZ")
        for s, v in zip(n.inputs, xyz):
            self._set(s, v)
        self._place(n, depth)
        return n.outputs[0]

    def shared_node(self, key, kind, setup=None, depth=0):
        if key not in self.shared:
            n = self.node(kind)
            if setup:
                setup(n)
            self._place(n, depth)
            self.shared[key] = n
        return self.shared[key]

    # -- Frostbite <-> Blender axes (from the assembly's recorded FBX conversion)
    def to_fb(self, vec_socket, key):
        """Blender world vector -> Frostbite world components (x, y, z)."""
        if ("fb", key) in self.shared:
            return self.shared[("fb", key)]
        out = []
        for row in self.ctx["blender_to_fb"]:
            n = self.node("ShaderNodeVectorMath")
            n.operation = "DOT_PRODUCT"
            self.link(vec_socket, n.inputs[0])
            n.inputs[1].default_value = row
            self._place(n, 1)
            out.append(n.outputs["Value"])
        self.shared[("fb", key)] = out
        return out

    def to_blender(self, xyz):
        v = self.combine(xyz, depth=29)
        out = []
        for row in self.ctx["fb_to_blender"]:
            n = self.node("ShaderNodeVectorMath")
            n.operation = "DOT_PRODUCT"
            self.link(v, n.inputs[0])
            n.inputs[1].default_value = row
            self._place(n, 30)
            out.append(n.outputs["Value"])
        return self.combine(out, depth=31)

    def srgb_encode(self, lin, key):
        """Recover the source UByte4N value from Blender's byte-colour (sRGB-decoded) attribute.

        Inverse sRGB transfer, then snap to the nearest k/255: the source is exactly k/255, and the
        decode/encode round trip error (~5e-5) is far below half a step, so the snap is lossless."""
        if ("enc", key) in self.shared:
            return self.shared[("enc", key)]
        low = self.math("MULTIPLY", lin, 12.92, depth=2)
        p = self.math("POWER", lin, 1 / 2.4, depth=2)
        high = self.math("MULTIPLY_ADD", p, 1.055, -0.055, depth=3)
        is_low = self.math("LESS_THAN", lin, 0.0031308, depth=2)
        r = self.mix(is_low, low, high, depth=4)
        r = self.math("DIVIDE", self.math("ROUND", self.math("MULTIPLY", r, 255.0, depth=5), depth=5), 255.0, depth=6,
                      label="Snap to source byte k/255")
        self.shared[("enc", key)] = r
        return r

    def mix(self, cond, a_true, b_false, depth=20):
        if not isinstance(a_true, (bool, int, float)) or not isinstance(b_false, (bool, int, float)):
            n = self.node("ShaderNodeMix")
            n.data_type, n.clamp_factor = "FLOAT", True
            self._set(n.inputs["Factor"], cond)
            self._set(n.inputs[2], b_false)   # A (factor 0)
            self._set(n.inputs[3], a_true)    # B (factor 1)
            self._place(n, depth)
            return n.outputs[0]
        return self.math("MULTIPLY_ADD", cond, _f(a_true) - _f(b_false), _f(b_false), depth=depth)

    # -- leaves
    def input(self, name):
        ctx = self.ctx
        if name.startswith("Const:"):
            return float(name.split(":", 1)[1])
        if name == "ViewFade":
            # Vertex-program fade from runtime view constants (camera environment): static state = no attenuation.
            note = "Assumption: per-vertex view fade (vertex-program polynomial of runtime view constants) = 1"
            if note not in ctx.setdefault("notes", []):
                ctx["notes"].append(note)
            return 1.0
        kind, _, comp = name.partition(".")
        if kind.startswith("TexCoord"):
            layer = ctx["uv"].get(kind)
            if not layer:
                raise Unsupported("Source %s has no Blender UV layer provenance" % kind)
            uv = self.shared_node(("uv", layer), "ShaderNodeUVMap", lambda n: setattr(n, "uv_map", layer))
            sep = self.separate(uv.outputs["UV"], ("uvsep", layer))
            if comp == "u":
                return sep.outputs["X"]
            if ("v", layer) not in self.shared:
                self.shared[("v", layer)] = self.math("SUBTRACT", 1.0, sep.outputs["Y"], depth=3,
                                                      label="Source V = 1 - Blender V (Frosty export flip)")
            return self.shared[("v", layer)]
        if kind.startswith("Color"):
            attr = ctx["colors"].get(kind)
            if not attr:
                raise Unsupported("Source %s has no Blender color attribute provenance" % kind)
            node = self.shared_node(("col", attr["name"]), "ShaderNodeVertexColor",
                                    lambda n: setattr(n, "layer_name", attr["name"]))
            if comp == "a":
                return node.outputs["Alpha"]
            sep = self.shared_node(("colsep", attr["name"]), "ShaderNodeSeparateColor", depth=1)
            if not sep.inputs[0].is_linked:
                self.link(node.outputs["Color"], sep.inputs[0])
            ch = sep.outputs["rgb".index(comp)]
            return self.srgb_encode(ch, (attr["name"], comp)) if attr["byte"] else ch
        if kind == "WorldPos":
            g = self.shared_node("geo", "ShaderNodeNewGeometry")
            return self.to_fb(g.outputs["Position"], "pos")["xyz".index(comp)]
        if kind == "WorldNormal":
            g = self.shared_node("geo", "ShaderNodeNewGeometry")
            return self.to_fb(g.outputs["Normal"], "normal")["xyz".index(comp)]
        if kind == "ObjectPos":
            tc = self.shared_node("texco", "ShaderNodeTexCoord")
            return self.separate(tc.outputs["Object"], "objsep").outputs["xyz".index(comp)]
        if kind == "ObjectNormal":
            # The vertex program's decoded normal, normalized per vertex; Blender's object-space shading normal is
            # normalized per sample (the same at vertices, a little longer between them).
            note = "Object-space normal: normalized per sample (the vertex program normalizes per vertex)"
            if note not in ctx.setdefault("notes", []):
                ctx["notes"].append(note)
            tc = self.shared_node("texco", "ShaderNodeTexCoord")
            return self.separate(tc.outputs["Normal"], "objnsep").outputs["xyz".index(comp)]
        if kind == "ViewPos":
            # Vertex-program view-matrix rows applied to (world position - camera position): camera-space position.
            # Frostbite view space: x right, y up, z forward; Blender camera space: x right, y up, z backward.
            if "viewpos" not in self.shared:
                g = self.shared_node("geo", "ShaderNodeNewGeometry")
                vt = self.node("ShaderNodeVectorTransform")
                vt.vector_type, vt.convert_from, vt.convert_to = "POINT", "WORLD", "CAMERA"
                self.link(g.outputs["Position"], vt.inputs[0])
                self._place(vt, 1)
                self.shared["viewpos"] = self.separate(vt.outputs[0], "viewsep")
            sep = self.shared["viewpos"]
            if comp == "z":
                return self.math("MULTIPLY", sep.outputs["Z"], -1.0, depth=3)
            return sep.outputs["xy".index(comp)]
        if kind == "ObjectOrigin":
            oi = self.shared_node("objinfo", "ShaderNodeObjectInfo")
            return self.to_fb(oi.outputs["Location"], "origin")["xyz".index(comp)]
        raise Unsupported("Unresolved shader input " + name)

    def view(self, name):
        if name == "Time":
            return 0.0  # static state
        if name.startswith("CameraPos."):
            if "campos" not in self.shared:
                g = self.shared_node("geo", "ShaderNodeNewGeometry")
                cam = self.shared_node("camdata", "ShaderNodeCameraData")
                scale = self.node("ShaderNodeVectorMath")
                scale.operation = "SCALE"
                self.link(g.outputs["Incoming"], scale.inputs[0])
                self.link(cam.outputs["View Distance"], scale.inputs["Scale"])
                add = self.node("ShaderNodeVectorMath")
                add.operation = "ADD"
                add.label = "Camera position = P + incoming * view distance"
                self.link(g.outputs["Position"], add.inputs[0])
                self.link(scale.outputs["Vector"], add.inputs[1])
                self._place(scale, 1)
                self._place(add, 1)
                self.shared["campos"] = add.outputs["Vector"]
            return self.to_fb(self.shared["campos"], "campos")["xyz".index(name[-1])]
        raise Unsupported("Unresolved view constant " + name)

    def texture(self, idx, rec):
        if ("tex", idx) in self.memo:
            return self.memo[("tex", idx)]
        image = self.ctx["images"].get(rec["slot"])
        if image is None:
            raise Unsupported("Texture slot t%d unavailable: %s" % (rec["slot"], self.ctx["image_issues"].get(rec["slot"], "")))
        coords = [self.value(c) for c in rec["coords"]]
        if isinstance(image, list):
            if len(coords) != 3:
                raise Unsupported("Array texture t%d sampled without a layer" % rec["slot"])
            out = self._array_sample(rec, image, coords)
            self.memo[("tex", idx)] = out
            return out
        if len(coords) != 2:
            raise Unsupported("Non-2D sample on t%d" % rec["slot"])
        out = self._sample(rec["slot"], image, coords)
        self.memo[("tex", idx)] = out
        return out

    def _array_sample(self, rec, images, coords):
        """D3D Texture2DArray: layer = clamp(round(z), 0, count - 1)."""
        layer = coords[2]
        if isinstance(layer, (int, float)):
            i = max(0, min(len(images) - 1, int(math.floor(layer + 0.5))))
            return self._sample(rec["slot"], images[i], coords[:2])
        layer = self.math("ROUND", layer, depth=13)
        result = None
        for i, image in enumerate(images):
            sample = self._sample(rec["slot"], image, coords[:2])
            if result is None:
                result = sample
                continue
            pick = self.math("COMPARE", layer, float(i), 0.5, depth=18) if i < len(images) - 1 else                 self.math("GREATER_THAN", layer, float(i) - 0.5, depth=18)
            result = [self.mix(pick, s, r, depth=19) for s, r in zip(sample, result)]
        return result

    def _sample(self, slot, image, coords):
        flipped = self.math("SUBTRACT", 1.0, coords[1], depth=14, label="Game V -> Blender V")
        vec = self.combine([coords[0], flipped, 0.0], depth=15)
        n = self.node("ShaderNodeTexImage")
        n.image, n.extension, n.interpolation = image, "REPEAT", "Linear"
        n.label = "t%d %s" % (slot, image.get("unbound_asset", image.name))
        self.link(vec, n.inputs["Vector"])
        self._place(n, 16)
        sep = self.node("ShaderNodeSeparateColor")
        self.link(n.outputs["Color"], sep.inputs[0])
        self._place(sep, 17)
        return [sep.outputs[0], sep.outputs[1], sep.outputs[2], n.outputs["Alpha"]]

    def frame(self, rec):
        """frame(v, k): component k of T*v.x + B*v.y + N*v.z in Frostbite world, via a Normal Map node."""
        fkey = ("framevec", tuple(map(str, rec["args"])))
        if fkey not in self.shared:
            signs = self.ctx.get("basis_signs")
            if not signs:
                # Unverified basis: keep only the normal-aligned term (tangent-plane detail disabled, reported).
                self.ctx.setdefault("notes", []).append("Tangent-space detail disabled: " + self.ctx.get("basis_reason", "basis unverified"))
                g = self.shared_node("geo", "ShaderNodeNewGeometry")
                n = self.to_fb(g.outputs["Normal"], "normal")
                self.shared[fkey] = [self.math("MULTIPLY", n[k], self.value(rec["args"][2])) for k in range(3)]
                return self.shared[fkey][rec["k"]]
            v = self.combine([self.value(a) for a in rec["args"]], depth=20)
            length = self.node("ShaderNodeVectorMath")
            length.operation = "LENGTH"
            self.link(v, length.inputs[0])
            norm = self.node("ShaderNodeVectorMath")
            norm.operation = "NORMALIZE"
            self.link(v, norm.inputs[0])
            scale = self.node("ShaderNodeVectorMath")
            scale.operation = "MULTIPLY"
            self.link(norm.outputs["Vector"], scale.inputs[0])
            scale.inputs[1].default_value = tuple(0.5 * s for s in signs)
            bias = self.node("ShaderNodeVectorMath")
            bias.operation = "ADD"
            self.link(scale.outputs["Vector"], bias.inputs[0])
            bias.inputs[1].default_value = (0.5, 0.5, 0.5)
            nm = self.node("ShaderNodeNormalMap")
            nm.space, nm.uv_map = "TANGENT", self.ctx["tangent_uv"]
            nm.label = "Source tangent frame (basis checked against this mesh's FBX)"
            self.link(bias.outputs["Vector"], nm.inputs["Color"])
            world = self.node("ShaderNodeVectorMath")
            world.operation = "SCALE"
            self.link(nm.outputs["Normal"], world.inputs[0])
            self.link(length.outputs["Value"], world.inputs["Scale"])
            for i, n in enumerate((length, norm, scale, bias, nm, world)):
                self._place(n, 21 + i)
            self.shared[fkey] = self.to_fb(world.outputs["Vector"], fkey)
        return self.shared[fkey][rec["k"]]

    # -- generic value
    def value(self, v):
        if not isinstance(v, tuple):
            return _f(v) if isinstance(v, bool) else v
        idx = v[1]
        if idx in self.memo:
            return self.memo[idx]
        rec = self.spec.nodes[idx]
        op = rec["op"]
        if op == "input":
            r = self.input(rec["name"])
        elif op == "view":
            r = self.view(rec["name"])
        elif op == "param":
            r = self.ctx["live"][(rec["name"], rec["c"])]
        elif op == "tex":
            r = self.texture(idx, rec)
        elif op == "ch":
            src = rec["args"][0]
            r = self.texture(src[1], self.spec.nodes[src[1]])[rec["args"][1]]
        elif op == "frame":
            r = self.frame(rec)
        elif op == "exp2" and self._pow_pattern(rec):
            base, k = self._pow_pattern(rec)
            r = self.math("POWER", self.value(base), self.value(k))
        else:
            r = self.operation(op, [self.value(a) for a in rec["args"]], rec)
        self.memo[idx] = r
        return r

    def _pow_pattern(self, rec):
        """exp2(k * log2(x)) -> (x, k). DXIL gives exp2(-inf) = 0 at x = 0; Blender POWER(0, k > 0) = 0 matches,
        while Blender's safe LOGARITHM would return 0 and turn the result into 1."""
        arg = rec["args"][0]
        inner = self.spec.nodes[arg[1]] if isinstance(arg, tuple) else None
        if inner and inner["op"] == "mul":
            for i in (0, 1):
                lg, other = inner["args"][i], inner["args"][1 - i]
                if isinstance(lg, tuple) and self.spec.nodes[lg[1]]["op"] == "log2":
                    return self.spec.nodes[lg[1]]["args"][0], other
        return None

    def operation(self, op, a, rec):
        if op in IDENTITY:
            return a[0]
        if op in MATH:
            return self.math(MATH[op], *a[:2]) if len(a) > 1 else self.math(MATH[op], a[0])
        if op == "neg":
            return self.math("MULTIPLY", a[0], -1.0)
        if op == "saturate":
            return self.math("ADD", a[0], 0.0, clamp=True)
        if op == "exp2":
            return self.math("POWER", 2.0, a[0])
        if op == "log2":
            return self.math("LOGARITHM", a[0], 2.0)
        if op in ("fcmp_olt", "fcmp_ult", "icmp_slt", "icmp_ult"):
            return self.math("LESS_THAN", a[0], a[1])
        if op in ("fcmp_ogt", "fcmp_ugt", "icmp_sgt", "icmp_ugt"):
            return self.math("GREATER_THAN", a[0], a[1])
        if op in ("fcmp_ole", "fcmp_ule", "icmp_sle", "icmp_ule"):
            return self.math("SUBTRACT", 1.0, self.math("GREATER_THAN", a[0], a[1]))
        if op in ("fcmp_oge", "fcmp_uge", "icmp_sge", "icmp_uge"):
            return self.math("SUBTRACT", 1.0, self.math("LESS_THAN", a[0], a[1]))
        if op in ("fcmp_oeq", "fcmp_ueq"):
            return self.math("COMPARE", a[0], a[1], 0.0)
        if op in ("fcmp_one", "fcmp_une"):
            return self.math("SUBTRACT", 1.0, self.math("COMPARE", a[0], a[1], 0.0))
        if op == "icmp_eq":
            return self.math("COMPARE", a[0], a[1], 0.5)
        if op == "icmp_ne":
            return self.math("SUBTRACT", 1.0, self.math("COMPARE", a[0], a[1], 0.5))
        if op == "and":
            return self.math("MULTIPLY", a[0], a[1])
        if op == "or":
            return self.math("MAXIMUM", a[0], a[1])
        if op == "not":
            return self.math("SUBTRACT", 1.0, a[0])
        if op == "xor":
            return self.math("ABSOLUTE", self.math("SUBTRACT", a[0], a[1]))
        if op == "select":
            return self.mix(a[0], a[1], a[2])
        if op == "ishl" and isinstance(a[1], (int, float)):
            return self.math("MULTIPLY", a[0], float(2 ** int(a[1])))
        if op == "ilshr" and isinstance(a[1], (int, float)):
            return self.math("FLOOR", self.math("DIVIDE", a[0], float(2 ** int(a[1]))))
        if op == "iand" and isinstance(a[1], (int, float)):
            mask = int(a[1]) & 0xffffffff
            if mask & (mask + 1) == 0:  # low-bit mask on non-negative integers
                return self.math("MODULO", a[0], float(mask + 1))
            if mask == 0xfffffffe:
                return self.math("SUBTRACT", a[0], self.math("MODULO", a[0], 2.0))
        if op == "lookup":
            r = 0.0
            for i, value in enumerate(rec["table"]):
                r = self.mix(self.math("COMPARE", a[0], float(i), 0.5), float(value), r)
            return r
        raise Unsupported("No node translation for operation " + op)


# ------------------------------------------------------------------ images
class Images:
    """Resolve export textures and shader-default textures (by source asset name) to Blender images."""

    def __init__(self, root, extra_folders=()):
        self.root = Path(root)
        self.by_asset, self.cache, self.uniform_cache, self.paths, self.constants = {}, {}, {}, {}, {}
        doc = json.loads((self.root / "materials.json").read_text(encoding="utf-8-sig"))
        textures = {t["ResourceId"]: t for t in doc.get("Textures", [])}
        for n in doc.get("Nodes", []):
            if n.get("Type") == "TextureAsset" and n.get("TextureResource") in textures:
                self.by_asset.setdefault(n["Asset"].casefold(), (self.root, textures[n["TextureResource"]]))
        for folder in (self.root / "liveries" / "textures", *[Path(f) for f in extra_folders if f]):
            index = folder / "textures.json"
            if index.is_file():
                for t in json.loads(index.read_text(encoding="utf-8-sig")).get("Textures", []):
                    for alias in t.get("Aliases", []):
                        if t.get("Path"):
                            self.by_asset.setdefault(alias["Asset"].casefold(), (folder, t))

    def _path(self, root, relative):
        # Resolved once per file: resolving touches the disk, and a car asks for the same textures thousands of times.
        key = (str(root), relative)
        if key not in self.paths:
            base = Path(root).resolve()
            path = (base / relative).resolve()
            if not path.is_relative_to(base):
                raise ValueError("Texture path escapes its export folder")
            if not path.is_file():
                raise FileNotFoundError(str(path))
            self.paths[key] = path
        return self.paths[key]

    def load(self, root, record, asset=None):
        import bpy
        path = self._path(root, record["Path"])
        colorspace = "sRGB" if record.get("ColorSpace") == "sRGB" else "Non-Color"
        key = (str(path), colorspace)
        if key in self.cache:
            if asset and not self.cache[key].get("unbound_asset"):
                self.cache[key]["unbound_asset"] = asset
            return self.cache[key]
        image = next((im for im in bpy.data.images if im.get("unbound_source_path") == str(path)
                      and im.colorspace_settings.name == colorspace and im.alpha_mode == "CHANNEL_PACKED"), None)
        if image is None:
            image = bpy.data.images.load(str(path), check_existing=False)
            image["unbound_resource_id"] = record.get("ResourceId", "")
            image["unbound_source_path"] = str(path)
            image["unbound_source_colorspace"] = record.get("ColorSpace", "unspecified")
            image["unbound_format"] = record.get("Format", "")
            image.colorspace_settings.name = colorspace
            image.alpha_mode = "CHANNEL_PACKED"
        if asset:
            image["unbound_asset"] = asset
        if image.size[0] == 0 and not image.packed_file:
            # A reused image whose relative path broke when the .blend moved: point it back at the export file.
            image.filepath = str(path)
            image.reload()
        if image.size[0] == 0:
            raise ValueError("Blender could not decode " + path.name)
        self.cache[key] = image
        return image

    def resolve(self, source):
        """Image, or list of slice images for a 2D texture array."""
        kind, value = source
        if kind == "binding":
            if value.get("TextureType") == "TT_2dArray":
                return self.array_slices(self.root, value, value.get("Asset") or "binding")
            return self.load(self.root, value, value.get("Asset"))
        if kind == "default":
            hit = self.by_asset.get(value.casefold())
            if not hit:
                raise FileNotFoundError("Shader texture not found (the shared parts folder needs Shader textures): " + value)
            if hit[1].get("Slices"):
                return [self.load(hit[0], dict(hit[1], Path=s["Path"]), value + "[%d]" % i)
                        for i, s in enumerate(hit[1]["Slices"])]
            if hit[1].get("TextureType") == "TT_2dArray":
                return self.array_slices(hit[0], hit[1], value)
            return self.load(hit[0], hit[1], value)
        raise ValueError(value)

    def array_slices(self, root, record, asset):
        """Mip-0 slices of an uncompressed 2D texture array, taken from the exported raw resource.

        Frosty's DDS for texture arrays is not reliable, so the raw data is used: its size must equal the full mip
        chain of every slice, mip-major (verified for paintnormalarray: mip 1 of each slice is the 2x2 box filter of
        its mip 0). Slices become packed, lossless Blender images; values are unchanged."""
        import hashlib
        import bpy
        import numpy as np
        fmt = record.get("Format") or ""
        if not record.get("RawData") or not fmt.startswith("R8G8B8A8_UNORM"):
            raise Unsupported("2D texture array %s (%s) without usable raw data" % (asset, fmt))
        path = self._path(root, record["RawData"])
        key = ("array", str(path))
        if key in self.cache:
            return self.cache[key]
        raw = np.fromfile(str(path), dtype=np.uint8)
        digest = hashlib.sha256(raw.tobytes()).hexdigest()
        if record.get("RawSha256") and digest != record["RawSha256"]:
            raise ValueError("Raw texture data does not match its recorded hash: " + asset)
        w, h, n = int(record["Width"]), int(record["Height"]), int(record["Depth"])
        if len(raw) != n * sum(max(1, w >> i) * max(1, h >> i) * 4 for i in range(int(record["MipCount"]))):
            raise Unsupported("2D texture array %s: raw size does not match the mip-major layout" % asset)
        images = []
        for i in range(n):
            tag = "%s:%d" % (digest, i)
            im = next((x for x in bpy.data.images if x.get("unbound_raw_slice") == tag), None)
            if im is None:
                im = bpy.data.images.new("%s[%d]" % (asset.rsplit("/", 1)[-1], i), w, h, alpha=True)
                im.colorspace_settings.name = "sRGB" if "SRGB" in fmt else "Non-Color"
                im.alpha_mode = "CHANNEL_PACKED"
                px = raw[i * w * h * 4:(i + 1) * w * h * 4].reshape(h, w, 4)[::-1]  # Blender rows are bottom-up
                im.pixels.foreach_set((px.astype(np.float32) / 255.0).ravel())
                im.pack()
                im["unbound_raw_slice"] = tag
                im["unbound_asset"] = asset + "[%d]" % i
                im["unbound_source_path"] = str(path)
            images.append(im)
        self.cache[key] = images
        return images

    def uniform_source(self, source):
        kind, value = source
        if kind == "binding":
            return self.uniform(self.root, value)
        hit = self.by_asset.get(value.casefold())
        if not hit or hit[1].get("Slices"):
            return None
        return self.uniform(hit[0], dict(hit[1], Asset=value))

    def uniform(self, root, binding):
        """Decoded uniform RGBA (shader-visible, sRGB linearized) or None.

        Reading an image's pixels is the expensive part, so the answer is computed once per image file and kept in
        memory and on the image (keyed by file size and modification time, so a changed file is checked again)."""
        import numpy as np
        quick = (str(root), binding.get("Path"), binding.get("Asset"), binding.get("ColorSpace"))
        if quick in self.uniform_cache:
            return self.uniform_cache[quick]["Value"]
        image = self.load(root, binding, binding.get("Asset"))
        path = Path(image["unbound_source_path"])
        stat = path.stat()
        key = "%s|%d|%d|%s" % (image.colorspace_settings.name, stat.st_size, stat.st_mtime_ns, binding.get("ColorSpace"))
        cached = self.uniform_cache.get((str(path), key))
        if cached is None and image.get("unbound_uniform_key") == key:
            cached = json.loads(image["unbound_uniform_json"])
        if cached is None:
            px = np.empty(image.size[0] * image.size[1] * 4, dtype=np.float32)
            image.pixels.foreach_get(px)
            px = px.reshape(-1, 4)
            v = None
            if np.all(np.abs(px - px[0]) < 1e-6):
                v = [float(x) for x in px[0]]
                if binding.get("ColorSpace") == "sRGB" and not image.is_float:
                    v[:3] = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in v[:3]]
            cached = {"Value": v}
            image["unbound_uniform_key"] = key
            image["unbound_uniform_json"] = json.dumps(cached)
        self.uniform_cache[(str(path), key)] = self.uniform_cache[quick] = cached
        return cached["Value"]


# ------------------------------------------------------------------ object context
def color_bindings(section):
    """Mirror Frosty FBXExporter: Color0/Color1 become VColor1/2 in declaration traversal order."""
    out, n = {}, 0
    for attr in sorted(section.get("VertexAttributes", []), key=lambda a: a.get("StreamIndex", 0)):
        if attr["Usage"] in ("Color0", "Color1") and attr["Usage"] not in out:
            n += 1
            out[attr["Usage"]] = "VColor%d" % n
    return out


def axis_matrices(obj):
    import bpy
    for c in bpy.data.collections:
        if c.get("fbx_to_blender_matrix") and obj.name in c.all_objects:
            m = json.loads(c["fbx_to_blender_matrix"])
            r = [row[:3] for row in m[:3]]
            break
    else:
        r = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]  # Blender FBX importer Y-up -> Z-up default
    inv = [[r[j][i] for j in range(3)] for i in range(3)]  # rotation: inverse = transpose
    return [tuple(map(float, row)) for row in r], [tuple(map(float, row)) for row in inv]


def reachable(spec, outputs):
    seen, stack = set(), [v for v in outputs if isinstance(v, tuple)]
    while stack:
        v = stack.pop()
        if v[1] in seen:
            continue
        seen.add(v[1])
        rec = spec.nodes[v[1]]
        for a in rec.get("args", []) + rec.get("coords", []):
            if isinstance(a, tuple):
                stack.append(a)
            elif isinstance(a, list):
                stack.extend(x for x in a if isinstance(x, tuple))
    return seen


def is_geometric_normal(spec, comps):
    names = []
    for c in comps:
        if not isinstance(c, tuple) or spec.nodes[c[1]]["op"] != "input":
            return False
        names.append(spec.nodes[c[1]]["name"])
    return names == ["WorldNormal.x", "WorldNormal.y", "WorldNormal.z"]


def is_const(v, value=None):
    return not isinstance(v, tuple) and (value is None or _f(v) == value)


# ------------------------------------------------------------------ live runtime parameters
# Vehicle customization kept live, one control group per car: the paint colour and finish, the rims' primary and
# secondary colours, front and rear, and the window, headlight and taillight tints.
RIM_COLOR_FIELDS = tuple("%sRim%sColorParameter" % (axle, layer) for axle in ("Front", "Rear") for layer in ("Primary", "Secondary"))
TINT_FIELDS = (("WindowsTintParameter", "Window tint"), ("HeadlightsTintParameter", "Headlight tint"),
               ("TaillightsTintParameter", "Taillight tint"))
LIVE_FIELDS = ("PaintFacingColorParameter", "PaintMaterialParameter") + RIM_COLOR_FIELDS + tuple(f for f, _ in TINT_FIELDS)
# Paint finish (Ext_Carpaint_Material): x = finish type floor(16x), 0-13; types 3-13 sample layer (type - 3) of
# paintnormalarray. z = gloss level floor(16z): 0 clear coat smoothness 1.0, 1 coat 0.70, 2 and above no clear coat
# (measured on cs_pbr_carpaint_max), the garage's Gloss / Satin / Matte. y is left as the car has it. The game's
# type -> name table is in its code: names come from each layer's texture and the stock cars that use the type, and
# the descriptive ones are confirmed in the game capture (see the research notes).
# The game's paint menu, read in a frame capture of its garage: Ext_Carpaint_Material x = material / 15, y = colour
# shift / 15, z = glossiness (0, 0.075, 0.15); the paint shader uses floor(16 x), floor(16 y) and floor(16 z).
FINISHES = ((0, "Non-Metallic"), (1, "Chrome"), (2, "Metallic"), (3, "Fine Metalflake"), (4, "Brushed Metal"),
            (5, "Black Carbon"), (6, "Carbon"), (7, "Chequered Carbon"), (8, "Broad Carbon"), (9, "Forged Carbon"),
            (10, "Damascus"), (11, "Large Metalflake"), (12, "Honey-Comb Carbon"))
COLOR_SHIFTS = ((0, "Single"), (1, "Near"), (2, "Opposite"), (3, "Spectrum"), (4, "Iridescent"))
GLOSS_LEVELS = ((0, "Gloss"), (1, "Satin"), (2, "Matte"))
GLOSS_VALUES = (0.0, 0.075, 0.15)
# The game's preset finishes (its "Material" tab), exact values. Its "Satin" presets use 0.13, which the shader draws
# like Matte.
FINISH_PRESETS = (("Gloss", (0.0, 0.0, 0.0)), ("Metallic", (0.133, 0.0, 0.0)), ("Chrome", (0.066, 0.0, 0.13)),
                  ("Satin Metallic", (0.133, 0.0, 0.13)), ("Carbon", (0.333, 0.0, 0.0)), ("Matte Carbon", (0.333, 0.0, 0.13)),
                  ("Forged Carbon", (0.6, 0.0, 0.0)), ("Chameleon Flake", (0.2, 0.19, 0.0)), ("Color Shift", (0.0, 0.07, 0.13)),
                  ("Iridescent", (0.133, 0.26, 0.0)), ("Color Shift Carbon", (0.4, 0.13, 0.0)),
                  ("Damascus", (0.666, 0.19, 0.13)), ("Honey-Comb Carbon", (0.8, 0.0, 0.0)))


# Texture overrides a slot may go without: a livery shows wherever the shader can be built with it; a part whose shader
# can't (window glass reads an unknown forward-lighting constant once a livery is on) keeps its stock look.
OPTIONAL_OVERRIDES = ("Ext_T_Livery_Diffuse", "Ext_T_Livery_Material")


def live_fields(entry, runtime):
    """External parameters of an entry that the car's runtime customization keeps live, with their customization field
    (e.g. PaintFacingColorParameter)."""
    return {e["Name"]: runtime[e["Key"].casefold()]["Field"] for e in entry["Externals"]
            if runtime.get(e["Key"].casefold(), {}).get("Field") in LIVE_FIELDS}


def runtime_group(scope, name=None, field=None):
    """The car's control group for a live runtime parameter, by parameter name or customization field (scope: the
    car's export folder name), or None."""
    import bpy
    return next((g for g in bpy.data.node_groups if g.get("unbound_live_scope") == scope
                 and (name is None or g.get("unbound_live_parameter") == name)
                 and (field is None or g.get("unbound_live_field") == field)), None)


def runtime_rgb(group):
    """The RGB value socket of a control group."""
    return next(n for n in group.nodes if n.type == "RGB").outputs[0]


def live_group(name, value, scope, field=""):
    """One user-editable control per live runtime parameter and car (e.g. the vehicle paint)."""
    import bpy
    g = runtime_group(scope, name)
    if g:
        return g
    g = bpy.data.node_groups.new("Unbound | Runtime %s | %s" % (name, scope), "ShaderNodeTree")
    g["unbound_live_parameter"], g["unbound_live_scope"], g["unbound_live_field"] = name, scope, field
    g["unbound_stock_value"] = [float(v) for v in value]
    g["unbound_note"] = "Runtime vehicle input. Initial value from the vehicle data; set it in the An's Garage sidebar."
    for c in "xyzw":
        g.interface.new_socket(name=c, in_out="OUTPUT", socket_type="NodeSocketFloat")
    out = g.nodes.new("NodeGroupOutput")
    out.location = (400, 0)
    rgb = g.nodes.new("ShaderNodeRGB")
    rgb.label = name + ".xyz (linear shader value)"
    rgb.outputs[0].default_value = (value[0], value[1], value[2], 1.0)
    w = g.nodes.new("ShaderNodeValue")
    w.label = name + ".w"
    w.outputs[0].default_value = value[3]
    w.location = (0, -200)
    sep = g.nodes.new("ShaderNodeSeparateColor")
    sep.location = (200, 0)
    g.links.new(rgb.outputs[0], sep.inputs[0])
    for i in range(3):
        g.links.new(sep.outputs[i], out.inputs[i])
    g.links.new(w.outputs[0], out.inputs[3])
    g.use_fake_user = True
    return g


# ------------------------------------------------------------------ vehicle condition: dirt, dust, wet
# The game sets these per car while driving (console Client.SetDirt / Client.SetDust, the rain cycle); every material
# leaves them at 0, clean and dry. With the sidebar's condition controls they stay live, driven by three sliders:
#   Ext_DirtColor_Amt.w, Ext_DustColor_Amt.w: dirt and dust amount.
#   Ext_DirtColor_Amt.xyz, Ext_DustColor_Amt.xyz: dirt and dust colour, read only by the light-glass lenses and one cabin
#     shader. The game picks it at runtime; the car paint and body shaders bake their own instead (dirt 0.0331, dust
#     0.139 grey, linear), and the lenses get the same so lens and body dirt match.
#   WaterCycle.x: rain cycle phase, 0-2. Every shader turns it into the same wet ramp: 0 up to phase 0.6, 1 from 0.7 to
#     1.2, then drying. The Wet slider follows the rising edge (phase 0.6 + 0.1 x wet; 0 when dry).
CONDITIONS = {"Ext_DirtColor_Amt": ("Dirt", "ans_garage_dirt", 0.033104799687862396),
              "Ext_DustColor_Amt": ("Dust", "ans_garage_dust", 0.1389549970626831),
              "WaterCycle": ("Wet", "ans_garage_wet", None)}
WET_PHASE = (0.6, 0.1)


def finish_value(scope):
    """(material, colour shift, gloss level) of the car's paint now, and of its stock paint."""
    g = runtime_group(scope, "Ext_Carpaint_Material")
    if g is None:
        return None, None
    rgb = runtime_rgb(g).default_value
    stock = g["unbound_stock_value"]
    level = lambda v: int(math.floor(16 * v + 1e-6))
    return tuple(level(rgb[i]) for i in range(3)), tuple(level(stock[i]) for i in range(3))


def finish_preset(scope):
    """Name of the game's preset finish the car's paint is set to, or None."""
    g = runtime_group(scope, "Ext_Carpaint_Material")
    if g is None:
        return None
    rgb = runtime_rgb(g).default_value
    return next((name for name, v in FINISH_PRESETS if all(abs(rgb[i] - v[i]) < 1e-4 for i in range(3))), None)


def set_finish(scope, finish=None, gloss=None, shift=None, preset=None):
    """Set the car's paint finish: a game preset by name, and/or the material, colour shift and gloss level (as the
    game's own menu sets them); "Stock" restores the car's own value."""
    g = runtime_group(scope, "Ext_Carpaint_Material")
    if g is None:
        raise ValueError("This car's paint has no finish control (rebuild its materials)")
    rgb = runtime_rgb(g)
    value, stock = list(rgb.default_value), g["unbound_stock_value"]
    if preset is not None:
        value[:3] = stock[:3] if preset == "Stock" else dict(FINISH_PRESETS)[preset]
    for i, choice, values in ((0, finish, None), (1, shift, None), (2, gloss, GLOSS_VALUES)):
        if choice is not None:
            value[i] = stock[i] if choice == "Stock" else values[int(choice)] if values else int(choice) / 15.0
    rgb.default_value = value


def condition_group(name):
    """Shared control for one vehicle condition parameter; its Amount node is driven by the sidebar slider (a driver, so
    keyframed sliders play back and render)."""
    import bpy
    label, prop, color = CONDITIONS[name]
    gname = "Unbound | Runtime " + name
    g = bpy.data.node_groups.get(gname)
    if g and g.get("unbound_condition") == name:
        return g
    g = bpy.data.node_groups.new(gname, "ShaderNodeTree")
    g["unbound_condition"] = name
    g["unbound_note"] = "Vehicle condition set by the game at runtime; the %s slider in the An's Garage sidebar sets it." % label
    for c in "xyzw":
        g.interface.new_socket(name=c, in_out="OUTPUT", socket_type="NodeSocketFloat")
    out = g.nodes.new("NodeGroupOutput")
    out.location = (600, 0)
    amount = g.nodes.new("ShaderNodeValue")
    amount.name = "Amount"
    amount.label = label + " (sidebar slider)"
    amount.outputs[0].default_value = float(getattr(bpy.context.scene, prop, 0.0))
    driver = amount.outputs[0].driver_add("default_value").driver
    driver.type = "AVERAGE"
    var = driver.variables.new()
    var.targets[0].id_type, var.targets[0].id, var.targets[0].data_path = "SCENE", bpy.context.scene, prop
    if color is None:
        phase = g.nodes.new("ShaderNodeMath")
        phase.operation, phase.label = "MULTIPLY_ADD", "rising edge of the wet ramp"
        phase.inputs[1].default_value, phase.inputs[2].default_value = WET_PHASE[1], WET_PHASE[0]
        wet = g.nodes.new("ShaderNodeMath")
        wet.operation, wet.label = "GREATER_THAN", "dry: phase 0"
        wet.inputs[1].default_value = 0.0
        x = g.nodes.new("ShaderNodeMath")
        x.operation = "MULTIPLY"
        for i, n in enumerate((phase, wet, x)):
            n.location = (200 + 150 * i, -100 * (i % 2))
        g.links.new(amount.outputs[0], phase.inputs[0])
        g.links.new(amount.outputs[0], wet.inputs[0])
        g.links.new(phase.outputs[0], x.inputs[0])
        g.links.new(wet.outputs[0], x.inputs[1])
        g.links.new(x.outputs[0], out.inputs[0])
    else:
        rgb = g.nodes.new("ShaderNodeValue")
        rgb.label = label + " colour (car paint shader's own, linear)"
        rgb.outputs[0].default_value = color
        rgb.location = (0, 200)
        for i in range(3):
            g.links.new(rgb.outputs[0], out.inputs[i])
        g.links.new(amount.outputs[0], out.inputs[3])
    return g


def show_conditions(scene):
    """Write the sliders into the condition groups now (dragging); their drivers keep them in step on frame changes and
    renders."""
    import bpy
    for g in bpy.data.node_groups:
        name = g.get("unbound_condition")
        if name in CONDITIONS and "Amount" in g.nodes:
            g.nodes["Amount"].outputs[0].default_value = float(getattr(scene, CONDITIONS[name][1], 0.0))


def condition_leaves(live, n=4000):
    """Formula leaf values of the live condition parameters for the numeric checks (evaluate_spec): each sample and
    parameter takes the sliders' 0, 0.5 or 1, so the checks see only states the sliders can produce, in every mix."""
    import zlib
    import numpy as np
    out = {}
    for name in sorted({x for x, _ in live if x in CONDITIONS}):
        amount = np.random.default_rng(zlib.crc32(name.encode())).choice([0.0, 0.5, 1.0], n)
        color = CONDITIONS[name][2]
        for c in range(4):
            if color is None:
                v = np.where(amount > 0, WET_PHASE[0] + WET_PHASE[1] * amount, 0.0) if c == 0 else 0.0
            else:
                v = amount if c == 3 else color
            out["P:%s.%d" % (name, c)] = v
    return out


# ------------------------------------------------------------------ build one slot
OUTPUT_SOCKETS = (("Base Color", "NodeSocketColor"), ("Metallic", "NodeSocketFloat"), ("Roughness", "NodeSocketFloat"),
                  ("Normal", "NodeSocketVector"), ("Coat Weight", "NodeSocketFloat"), ("Coat Roughness", "NodeSocketFloat"),
                  ("Coat Normal", "NodeSocketVector"), ("Emission Color", "NodeSocketColor"), ("Alpha", "NodeSocketFloat"))


def texture_constants(profile, sources, images):
    """{slot: [r, g, b, a]} for sampled textures that are uniform (or zero by the static-state rule), with notes.
    Remembered per profile and texture sources for the resolver's lifetime (one build)."""
    key = (id(profile), json.dumps(sorted((k, v[0], v[1] if isinstance(v[1], str) else v[1].get("Path") or v[1].get("Asset"))
                                          for k, v in sources.items()), default=str))
    if key not in images.constants:
        images.constants[key] = _texture_constants(profile, sources, images)
    consts, notes = images.constants[key]
    return dict(consts), list(notes)


def _texture_constants(profile, sources, images):
    consts, notes = {}, []
    for slot, src in sources.items():
        if src[0] == "zero":
            consts[slot] = [0.0, 0.0, 0.0, 0.0]
            notes.append({"Slot": slot, "Value": consts[slot], "Reason": src[1]})
            continue
        if src[0] not in ("binding", "default") or profile["Slots"].get(str(slot), {}).get("Dim") != "2d":
            continue
        try:
            value = images.uniform_source(src)
        except Exception:
            value = None
        if value is not None:
            consts[slot] = value
            notes.append({"Slot": slot, "Value": [round(v, 6) for v in value],
                          "Reason": "bound texture's decoded texels are uniform (exact for every sample)"})
    return consts, notes


_SPECIALIZED = {}


def specialize(profile, values, live, input_consts, rename, tex_consts):
    """Specialized, simplified formulas; shared between slots whose inputs are identical (materials often differ only
    in name). The result is read-only after simplification."""
    names = {e["Name"] for e in profile["Externals"]}
    key = (id(profile), json.dumps([sorted([k[0], k[1], values[k]] for k in values if k[0] in names), sorted(live),
                                    sorted(input_consts.items()), sorted((rename or {}).items()),
                                    sorted((str(k), v) for k, v in (tex_consts or {}).items())]))
    if key not in _SPECIALIZED:
        spec = Spec(profile, values, live, input_consts, rename, tex_consts)
        _SPECIALIZED[key] = (spec, settle(spec, {k: spec.output(k) for k in profile["Outputs"]}, CONNECTED_OUTPUTS + ("Emissive",)))
    spec, outs = _SPECIALIZED[key]
    return spec, dict(outs)


# Permutation pairs told apart by one default texture, where the other version is a player customization. The license
# plate shader samples either the printed font (licenseplatefont_no, t2) or an LED mask
# (license_plate/licenseplate_ledmask_a, t6); every other instruction of the two programs is the same (checked in the
# disassembly). Compiled profiles keep the font slot, so the stock version is recognised by it.
STOCK_PERMUTATION_TEXTURES = {"licenseplate/licenseplatefont": ("printed license plate", "LED license plate")}


def full_forward_program(entry):
    """True for a forward (glass) entry whose programs are all the full variant (state bit 9 clear); profiles compiled
    before 1.1.0 don't record the bit (None)."""
    if entry.get("Kind") != "forward_transmittance" or "StateBit9" not in entry:
        return None
    return entry["StateBit9"] == [False]


def stock_permutation(entry):
    """(stock label, customization label) when a compiled entry samples a stock-marker texture, else None."""
    for slot in (entry.get("Slots") or {}).values():
        asset = (slot.get("DefaultAsset") or "").lower()
        for key, labels in STOCK_PERMUTATION_TEXTURES.items():
            if key in asset:
                return labels
    return None


# License plate text, as the plate shader reads it: seven character cells; Ext_LicensePlateText1.xyzw holds cells 1-4
# and Ext_LicensePlateText2.xyz cells 5-7 (its w picks one of the plate's two text layouts and is left as it is). Each
# value is a cell of the plate font (licenseplatefont_no, 22 per row): 0-9 are digits, 10-35 are A-Z, 36 is empty.
PLATE_TEXT_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PLATE_TEXT_CELLS = 7
PLATE_BLANK = 36.0


def plate_text_values(text):
    """Parameter overrides that put `text` (A-Z, 0-9, spaces; at most 7, centred) on a license plate."""
    chars = [c for c in (text or "").upper() if c in PLATE_TEXT_CHARS or c == " "][:PLATE_TEXT_CELLS]
    left = (PLATE_TEXT_CELLS - len(chars)) // 2
    cells = [" "] * left + chars + [" "] * (PLATE_TEXT_CELLS - left - len(chars))
    values = [PLATE_BLANK if c == " " else float(PLATE_TEXT_CHARS.index(c)) for c in cells]
    return {"Ext_LicensePlateText1": values[:4], "Ext_LicensePlateText2": values[4:]}


def view_node_name(constant):
    """Formula node of a view-buffer constant: cb2[44].w -> View:44.w (None for anything else)."""
    import re
    m = re.fullmatch(r"cb2\[(\d+)\]\.([xyzw])", constant)
    return "View:%s.%s" % m.groups() if m else None


def testable_unresolved(entry):
    """The entry's unresolved inputs that are view constants present in its formula, so the planner can test them."""
    present = {n.get("name") for n in entry.get("Nodes", []) if n.get("op") == "view"}
    return [u for u in entry.get("Unresolved", []) if view_node_name(u) in present]


def view_independence(profile, values, live, input_consts, rename, tex_consts):
    """Largest change of any connected output when the unresolved view constants sweep VIEW_CONSTANT_RANGE (unspecialized
    formula, so no constant proof hides a dependence)."""
    import numpy as np
    names = [view_node_name(u) for u in testable_unresolved(profile)]
    raw = Spec(profile, values, live, input_consts, rename, tex_consts)
    outs = {k: raw.output(k) for k in profile["Outputs"] if k in CONNECTED_OUTPUTS}
    worst, case = 0.0, condition_leaves(live)
    ref = evaluate_spec(raw, outs, fixed={**case, **{n: 1.0 for n in names}})
    for value in VIEW_CONSTANT_RANGE:
        other = evaluate_spec(raw, outs, fixed={**case, **{n: value for n in names}})
        for k, a in ref.items():
            d = np.abs(a - other[k])
            d = d[np.isfinite(d)]
            if d.size:
                worst = max(worst, float(d.max()))
    return worst


def plan(profile, state, runtime, live_fields, images, root, input_consts=None, rename=None, conditions=False):
    """Everything that does not depend on the object's geometry: parameters, specialization, textures."""
    values, applied, issues = parameter_values(profile, state, runtime)
    live = {(n, c) for n in live_fields for c in range(4)
            if any(a["Parameter"] == n for a in applied)}
    if conditions:
        live |= {(e["Name"], c) for e in profile["Externals"] if e["Name"] in CONDITIONS for c in range(4)}
    input_consts = dict(input_consts or {})
    sources, bind_issues = check_bindings(profile, state, root, images)
    issues += bind_issues
    tex_consts, tex_notes = texture_constants(profile, sources, images)
    spec, outs, input_consts, used, unsupported, engine, view = checked(profile, values, live, input_consts, rename, tex_consts)
    outs, input_consts = dict(outs), dict(input_consts)  # shared by every slot with the same formulas
    used_slots = {spec.nodes[i]["slot"] for i in used if spec.nodes[i]["op"] == "tex"}
    image_map, image_issues = {}, {}
    for slot in used_slots:
        src = sources.get(slot)
        try:
            if not src or src[0] == "unsupported":
                raise ValueError(src[1] if src else "no source")
            image_map[slot] = images.resolve(src)
        except Exception as exc:
            image_issues[slot] = str(exc)
    uses_frame = any(spec.nodes[i]["op"] == "frame" for i in used)
    inputs = sorted({spec.nodes[i]["name"] for i in used if spec.nodes[i]["op"] in ("input", "view")})
    return {"values": values, "applied": applied, "issues": issues, "spec": spec, "outs": outs,
            "input_consts": input_consts, "unsupported": unsupported, "engine": engine, "view": view,
            "images": image_map, "image_issues": image_issues, "uses_frame": uses_frame, "inputs": inputs,
            "live": live, "live_fields": dict(live_fields), "conditions": sorted({n for n, _ in live if n in CONDITIONS}), "folded_textures": tex_notes}


_CHECKED = {}


def checked(profile, values, live, input_consts, rename, tex_consts):
    """Specialized formulas and the checks that depend only on them (engine constants, view constants): (spec, outs,
    input constants, used nodes, unsupported reason, engine note, view note). Shared between slots whose formulas are
    identical (many materials differ only in name), like specialize()."""
    spec, outs = specialize(profile, values, live, input_consts, rename, tex_consts)
    if id(spec) not in _CHECKED:
        _CHECKED[id(spec)] = _check(profile, values, live, dict(input_consts), rename, tex_consts, spec, outs)
    return _CHECKED[id(spec)]


def _check(profile, values, live, input_consts, rename, tex_consts, spec, outs):
    connected = {k: outs[k] for k in CONNECTED_OUTPUTS + ("Emissive",) if k in outs}
    used = reachable(spec, [x for v in connected.values() for x in (v if isinstance(v, list) else [v])])
    names = {spec.nodes[i].get("name", "") for i in used if spec.nodes[i]["op"] in ("input", "view")}
    unsupported, engine = None, None
    known = {n: ENGINE_VALUES[n[7:]] for n in names if n.startswith("Engine:") and n[7:] in ENGINE_VALUES}
    if known:
        input_consts.update(known)
        spec, outs = specialize(profile, values, live, input_consts, rename, tex_consts)
        connected = {k: outs[k] for k in CONNECTED_OUTPUTS + ("Emissive",) if k in outs}
        used = reachable(spec, [x for v in connected.values() for x in (v if isinstance(v, list) else [v])])
        names = {spec.nodes[i].get("name", "") for i in used if spec.nodes[i]["op"] in ("input", "view")}
        engine = {"Constants": sorted(c[7:] for c in known), "Values": {c[7:]: v for c, v in known.items()},
                  "Reason": "Engine constant outside the shader database; value read from the game (frame capture)"}
    if any(n.startswith("Engine:") for n in names):
        # Engine constants outside the shader database: 0 only if the measured effect is small.
        import numpy as np
        consts = sorted(n for n in names if n.startswith("Engine:"))
        keys = [k for k in CONNECTED_OUTPUTS if k in outs]
        effect, case = 0.0, condition_leaves(live)
        base = evaluate_spec(spec, {k: outs[k] for k in keys}, fixed={**case, **{c: 0.0 for c in consts}})
        for value in (0.25, 1.0, 4.0):
            other = evaluate_spec(spec, {k: outs[k] for k in keys}, fixed={**case, **{c: value for c in consts}})
            for k, a in base.items():
                d = np.abs(a - other[k])
                if np.isfinite(d).any():
                    effect = max(effect, float(np.nanmax(d[np.isfinite(d)])))
        if effect <= ENGINE_ZERO_MAX_EFFECT:
            input_consts.update({c: 0.0 for c in consts})
            spec, outs = specialize(profile, values, live, input_consts, rename, tex_consts)
            connected = {k: outs[k] for k in CONNECTED_OUTPUTS + ("Emissive",) if k in outs}
            used = reachable(spec, [x for v in connected.values() for x in (v if isinstance(v, list) else [v])])
            names = {spec.nodes[i].get("name", "") for i in used if spec.nodes[i]["op"] in ("input", "view")}
            engine = {"Constants": [c[7:] for c in consts], "Value": 0.0, "MaxMeasuredEffect": effect,
                      "Reason": "Engine constant outside the shader database (forward-lighting block); "
                                "set to 0 because its measured effect on the specialized outputs is <= %.2f" % ENGINE_ZERO_MAX_EFFECT}
        else:
            unsupported = "Engine constants %s change the outputs by up to %.3f; not assumed" % (", ".join(c[7:] for c in consts), effect)
    vsconst = sorted(n for n in names if n.startswith("VSConst:"))
    if not unsupported and vsconst:
        unsupported = "; ".join(("Not mounted on an assembled wheel: per-wheel input %s unknown" % n)
                                if VS_CONSTANTS.get(tuple(n[8:].split(".", 1))) in ("Front", "Side")
                                else "Unknown per-instance vertex constant " + n for n in vsconst)
    if not unsupported and any(n.startswith(("Unresolved:", "View:")) for n in names):
        unsupported = "Unresolved runtime inputs after specialization: " + ", ".join(
            sorted(n.split(":", 1)[1] for n in names if n.startswith(("Unresolved:", "View:"))))
    view = None
    if not unsupported and testable_unresolved(profile):
        worst = view_independence(profile, values, live, input_consts, rename, tex_consts)
        constants = testable_unresolved(profile)
        if worst > 1e-6:
            unsupported = "Runtime view constants %s (camera exposure) change the outputs by up to %.4f; not assumed" % (
                ", ".join(constants), worst)
        else:
            view = {"Constants": constants, "Range": [VIEW_CONSTANT_RANGE[0], VIEW_CONSTANT_RANGE[-1]], "MaxDifference": worst,
                    "Reason": "Runtime view constant (camera exposure) the exporter cannot read; with this car's material "
                              "values no output changes across the range, so none is needed"}
    return spec, outs, input_consts, used, unsupported, engine, view


def build_group(profile, p, ctx, identity, label):
    import bpy
    existing = next((g for g in bpy.data.node_groups if g.get("unbound_profile_identity") == identity), None)
    if existing:
        return existing, json.loads(existing["unbound_connected_json"])
    g = bpy.data.node_groups.new(label, "ShaderNodeTree")
    b = None
    try:
        g["unbound_profile_identity"] = identity
        spec, outs = p["spec"], p["outs"]
        b = NodeBuilder(g, spec, dict(ctx, images=p["images"], image_issues=p["image_issues"]))
        live_nodes = {}
        for (name, c) in p["live"]:
            if name not in live_nodes:
                n = g.nodes.new("ShaderNodeGroup")
                if name in CONDITIONS:
                    n.node_tree = condition_group(name)
                    n.label = "Vehicle condition: " + CONDITIONS[name][0]
                else:
                    n.node_tree = live_group(name, [p["values"][(name, k)] for k in range(4)], ctx["live_scope"],
                                             p["live_fields"].get(name, ""))
                    n.label = "Runtime vehicle input: " + name
                n.location = (-2600, 1400 - 200 * len(live_nodes))
                live_nodes[name] = n
            b.ctx.setdefault("live", {})[(name, c)] = live_nodes[name].outputs[c]
        connected, results = [], {}
        if profile.get("Kind") == "forward_transmittance":
            results["Transmittance"] = b.combine([b.value(x) for x in outs["Transmittance"]], depth=32)
            if "Reflectance" in outs:
                results["Reflectance"] = b.math("ADD", b.value(outs["Reflectance"]), 0.0, clamp=True, depth=32,
                                                label="1 - common transmittance factor (program's Fresnel term)")
            return _finish_group(g, results, connected, (("Transmittance", "NodeSocketColor"), ("Reflectance", "NodeSocketFloat")), b)
        results["Base Color"] = b.combine([b.value(x) for x in outs["BaseColor"]], depth=32)
        results["Metallic"] = b.value(outs["Metallic"])
        results["Roughness"] = b.math("SUBTRACT", 1.0, b.math("ADD", b.value(outs["Smoothness"]), 0.0, clamp=True, depth=32),
                                      depth=33, label="Principled roughness = 1 - source smoothness")
        if not is_geometric_normal(spec, outs["Normal"]):
            results["Normal"] = b.to_blender([b.value(x) for x in outs["Normal"]])
        if "CoatSmoothness" in outs:
            results["Coat Weight"] = b.math("ADD", b.value(outs["RT2.x"]), 0.0, clamp=True, depth=32,
                                            label="RT2.x (fifth-target layout): interpreted as clear-coat weight")
            results["Coat Roughness"] = b.math("SUBTRACT", 1.0, b.math("ADD", b.value(outs["CoatSmoothness"]), 0.0, clamp=True, depth=32), depth=33)
            if "CoatNormal" in outs and not is_geometric_normal(spec, outs["CoatNormal"]):
                results["Coat Normal"] = b.to_blender([b.value(x) for x in outs["CoatNormal"]])
        if "Emissive" in outs and not all(is_const(x, 0.0) for x in outs["Emissive"]):
            results["Emission Color"] = b.combine([b.value(x) for x in outs["Emissive"]], depth=32)
        if "Discard" in outs and not is_const(outs["Discard"], 0.0):
            results["Alpha"] = b.math("SUBTRACT", 1.0, b.value(outs["Discard"]), depth=33, label="Source discard -> alpha")
        return _finish_group(g, results, connected, OUTPUT_SOCKETS, b)
    except Exception:
        for name in (b.parts if b else {}):
            bpy.data.node_groups.remove(bpy.data.node_groups[name])
        bpy.data.node_groups.remove(g)
        raise


def _finish_group(g, results, connected, sockets, b):
    results = {k: b.export(v) for k, v in results.items()}
    gout = g.nodes.new("NodeGroupOutput")
    gout.location = (3600, 0)
    for name, kind in sockets:
        if name in results:
            g.interface.new_socket(name=name, in_out="OUTPUT", socket_type=kind)
            v = results[name]
            if isinstance(v, (int, float)):
                val = g.nodes.new("ShaderNodeValue")
                val.outputs[0].default_value = float(v)
                v = val.outputs[0]
            g.links.new(v, gout.inputs[name])
            connected.append(name)
    g["unbound_connected_json"] = json.dumps(connected)
    g["unbound_node_count"] = sum(1 for _ in group_nodes(g))
    return g, connected


def make_profile_material(source, profile, group, connected, report_entry):
    import bpy
    mat = source.copy()
    try:
        mat.name = source.name + " | " + (profile.get("ShaderAsset") or profile["Shader"]).rsplit("/", 1)[-1]
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        frame = nodes.new("NodeFrame")
        frame.label = "Original source values / inactive inspection nodes"
        for node in list(nodes):
            if node != frame and node.parent is None:
                node.parent = frame
        frame.location = (-1600, -1400)
        for node in list(nodes):
            if node.type == "OUTPUT_MATERIAL":
                node.is_active_output = False
        gnode = nodes.new("ShaderNodeGroup")
        gnode.node_tree, gnode.location = group, (-300, 300)
        gnode.label = "Compiled source shader (static state)"
        if profile.get("Kind") == "forward_transmittance":
            transparent = nodes.new("ShaderNodeBsdfTransparent")
            transparent.location, transparent.label = (100, 400), "Source transmittance (dual-source target 1)"
            links.new(gnode.outputs["Transmittance"], transparent.inputs["Color"])
            shader = transparent.outputs[0]
            if "Reflectance" in connected:
                glossy = nodes.new("ShaderNodeBsdfGlossy")
                glossy.location, glossy.label = (100, 200), "Reflection weighted by the source Fresnel term"
                glossy.inputs["Roughness"].default_value = 0.0
                links.new(gnode.outputs["Reflectance"], glossy.inputs["Color"])
                add = nodes.new("ShaderNodeAddShader")
                add.location = (300, 300)
                links.new(transparent.outputs[0], add.inputs[0])
                links.new(glossy.outputs[0], add.inputs[1])
                shader = add.outputs[0]
            if hasattr(mat, "surface_render_method"):
                mat.surface_render_method = "DITHERED"
            out = nodes.new("ShaderNodeOutputMaterial")
            out.is_active_output, out.location = True, (500, 300)
            links.new(shader, out.inputs["Surface"])
            mat["unbound_surface_profile"] = "unbound-compiled-forward-transmittance-v1"
            mat["unbound_surface_key"] = report_entry["Identity"]
            mat["unbound_status"] = "Compiled source glass transmittance, static state"
            mat["unbound_surface_evidence_json"] = canonical(report_entry)
            return mat
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location, bsdf.label = (100, 300), "Principled translation of source G-buffer outputs"
        bsdf.inputs["IOR"].default_value = 1.5
        for name in connected:
            links.new(gnode.outputs[name], bsdf.inputs[name])
        if "Emission Color" in connected:
            bsdf.inputs["Emission Strength"].default_value = 1.0
        if "Alpha" in connected and hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "DITHERED"
        out = nodes.new("ShaderNodeOutputMaterial")
        out.is_active_output, out.location = True, (450, 300)
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        mat["unbound_surface_profile"] = "unbound-compiled-gbuffer-v1"
        mat["unbound_surface_key"] = report_entry["Identity"]
        mat["unbound_status"] = "Compiled source shader, static state; Principled translation"
        mat["unbound_surface_evidence_json"] = canonical(report_entry)
        return mat
    except Exception:
        bpy.data.materials.remove(mat)
        raise


# ------------------------------------------------------------------ program/layout entries (profile schema 2)
# Vertex-program constants passed straight to the pixel program, set per wheel instance at runtime. Values read in a
# frame capture (rear-right wheel: g_facingParam = g_brakeAndCaliperCustomizeParam.yz = -1, -1): front +1 / rear -1,
# left +1 / right -1 (the +1 sides by symmetry). The pixel programs compute lerp(rear, front, clamp(value)).
VS_CONSTANTS = {("g_facingParam", "x"): "Front", ("g_facingParam", "y"): "Side",
                ("g_brakeAndCaliperCustomizeParam", "y"): "Front", ("g_brakeAndCaliperCustomizeParam", "z"): "Side"}
CONNECTED_OUTPUTS = ("BaseColor", "Metallic", "Smoothness", "Normal", "CoatSmoothness", "CoatNormal", "RT2.x",
                     "Discard", "Transmittance", "Reflectance")


def section_layout(section):
    return [a["Usage"] for a in section.get("VertexAttributes", []) if a["Usage"] != "Unknown"]


def section_formats(section):
    return [a["Format"] for a in section.get("VertexAttributes", []) if a["Usage"] != "Unknown"]


def entries_for(profile, layout, formats=None):
    """Entries serving this section: by vertex declaration (vehicle-agnostic profiles) or usage layout (schema 2)."""
    out = []
    for e in profile.get("Entries", []):
        if (formats is not None and formats in e.get("Formats", [])) or layout in e.get("Layouts", []):
            e.setdefault("Kind", profile.get("Kind", "gbuffer"))
            e.setdefault("Shader", profile.get("Name") or profile["Shader"])
            out.append(e)
    if any(layout in e.get("Layouts", []) for e in out):
        # A usage-named entry exists for this layout: it replaces element entries whose vertex programs are stubs.
        out = [e for e in out if not e.get("StubVertexPrograms")]
    return out


def element_inputs(entry, layout):
    """Map declaration-element inputs (Elem<i>.<k>) to this section's usages; verify assumed element roles."""
    for element, usage in (entry.get("AssumedUsages") or {}).items():
        i = int(element)
        if i >= len(layout) or layout[i] != usage:
            raise Unsupported("Profile assumes vertex element %d is %s; this section has %s"
                              % (i, usage, layout[i] if i < len(layout) else "no such element"))
    rename = {}
    for n in entry["Nodes"]:
        name = n.get("name", "") if n["op"] == "input" else ""
        if not name.startswith("Elem"):
            continue
        element, _, comp = name[4:].partition(".")
        i, k = int(element), int(comp)
        if i >= len(layout):
            raise Unsupported("Profile input %s has no vertex element in this section" % name)
        u = layout[i]
        letters = "uv??" if u.startswith("TexCoord") else "rgba" if u.startswith("Color") else "xyzw"
        rename[name] = ("ObjectPos" if u == "Pos" else u) + "." + letters[k]
    return rename


def wheel_facing(obj, assembly_doc):
    """Facing of the wheel an assembled part belongs to (assembly Wheels[].Facing: Front, Left), or None."""
    o = obj
    while o is not None and not o.get("wheel_side"):
        o = o.parent
    if o is None or not assembly_doc:
        return None
    wheels = [w for w in assembly_doc.get("Wheels", []) if w.get("Name") == o["wheel_side"]]
    if len(wheels) != 1 or not isinstance(wheels[0].get("Facing"), dict):
        return None
    return wheels[0]["Facing"]


def input_constants(entry, obj, assembly_doc):
    """Per-object values for the vertex-constant inputs whose meaning is known. Unknown ones stay symbolic: plan()
    reports the slot unsupported only if one still reaches an output after specialization."""
    values = {}
    for n in entry["Nodes"]:
        if n["op"] == "input" and n["name"].startswith("VSConst:"):
            name, _, comp = n["name"][8:].partition(".")
            role = VS_CONSTANTS.get((name, comp))
            facing = wheel_facing(obj, assembly_doc) if role else None
            if facing is not None:
                values[n["name"]] = 1.0 if facing.get("Front" if role == "Front" else "Left") else -1.0
    return values


def evaluate_spec(spec, roots, n=4000, seed=11, fixed=None):
    """Numeric evaluation of specialized nodes with shared random leaves (used to compare alternatives)."""
    import zlib
    import numpy as np
    leaves, memo = {}, {}

    def leaf(name):
        # Deterministic per leaf name, independent of traversal order (alternatives must see identical inputs).
        if fixed and name in fixed:
            return np.broadcast_to(np.asarray(fixed[name], dtype=float), (n,))
        if name not in leaves:
            rng = np.random.default_rng(zlib.crc32(name.encode()) + seed)
            leaves[name] = (np.floor(rng.random(n) * 256) / 255.0 if name.startswith("Color")
                            else rng.uniform(-0.5, 1.5, n))
        return leaves[name]

    def val(v):
        if not isinstance(v, tuple):
            return np.full(n, _f(v))
        i = v[1]
        if i in memo:
            return memo[i]
        rec = spec.nodes[i]
        op = rec["op"]
        with np.errstate(all="ignore"):
            if op in ("input", "view"):
                r = leaf(rec["name"])
            elif op == "param":
                r = leaf("P:%s.%d" % (rec["name"], rec["c"]))
            elif op == "tex":
                co = [val(c) for c in rec["coords"]]
                h = 0.37 * rec["slot"] + sum(c * (3.1 + 1.7 * k) for k, c in enumerate(co))
                r = [0.5 + 0.5 * np.sin(h + 0.7 * k) for k in range(4)]
            elif op == "ch":
                r = val(rec["args"][0])[rec["args"][1]]
            elif op == "frame":
                a = [val(x) for x in rec["args"]]
                cols = [leaf("%s.%s" % (b, "xyz"[rec["k"]])) for b in ("T", "B", "N")]
                r = cols[0] * a[0] + cols[1] * a[1] + cols[2] * a[2]
            else:
                r = _np_op(op, [val(x) for x in rec["args"]], rec)
        memo[i] = r
        return r
    out = {}
    for k, v in roots.items():
        for j, x in enumerate(v if isinstance(v, list) else [v]):
            out["%s%d" % (k, j)] = val(x)
    return out


BOOL_OPS = ("and", "or", "not", "xor")


def prove_constants(spec, roots, n=4096, rounds=3):
    """Specialized nodes whose value is identical over random inputs (several seeds) -> {index: constant}.

    Same rule as the offline simplifier (dag_tools.prove_constants), applied after the material's parameters are
    known. Inputs, view values and live parameters are random leaves (branch-covering mixtures; vertex colours as
    bytes). Every texture sample is an independent random value per evaluation, so nothing that depends on texture
    contents is ever folded."""
    import numpy as np
    candidates = None
    for rnd in range(rounds):
        rng = np.random.default_rng(1009 + rnd)
        leaves, memo = {}, {}

        def leaf(name):
            if name not in leaves:
                if name.startswith("Color"):
                    leaves[name] = np.floor(rng.random(n) * 256) / 255.0
                else:
                    kind = rng.random(n)
                    leaves[name] = np.where(kind < 0.6, rng.random(n), np.where(kind < 0.85, rng.uniform(-1, 1, n),
                                   np.where(kind < 0.93, rng.uniform(-30, 30, n), rng.integers(0, 2, n).astype(float))))
            return leaves[name]

        def val(v):
            if not isinstance(v, tuple):
                return np.full(n, _f(v))
            i = v[1]
            if i in memo:
                return memo[i]
            rec = spec.nodes[i]
            op = rec["op"]
            with np.errstate(all="ignore"):
                if op in ("input", "view"):
                    r = leaf(rec["name"])
                elif op == "param":
                    r = leaf("P:%s.%d" % (rec["name"], rec["c"]))
                elif op == "tex":
                    for c in rec["coords"]:
                        val(c)
                    r = [rng.random(n) for _ in range(4)]
                elif op == "ch":
                    r = val(rec["args"][0])[rec["args"][1]]
                elif op == "frame":
                    a = [val(x) for x in rec["args"]]
                    cols = [leaf("%s.%s" % (b, "xyz"[rec["k"]])) for b in ("T", "B", "N")]
                    r = cols[0] * a[0] + cols[1] * a[1] + cols[2] * a[2]
                else:
                    r = _np_op(op, [val(x) for x in rec["args"]], rec)
            memo[i] = r
            return r
        try:
            for v in roots:
                val(v)
        except Unsupported:
            return {}
        found = {}
        for i, v in memo.items():
            op = spec.nodes[i]["op"]
            if op in ("input", "view", "param", "tex", "ch") or isinstance(v, list):
                continue
            v = np.asarray(v, dtype=float)
            if np.isfinite(v[0]) and np.all(v == v[0]):
                c = float(v[0])
                found[i] = bool(c) if op in BOOL_OPS or op.startswith(("fcmp_", "icmp_")) else c
        candidates = found if candidates is None else {k: c for k, c in candidates.items() if found.get(k) == c}
        if not candidates:
            break
    return candidates or {}


def settle(spec, outs, keys):
    """Constant proof to a fixed point; returns re-read outputs."""
    for _ in range(4):
        roots = [x for k in keys if k in outs for x in (outs[k] if isinstance(outs[k], list) else [outs[k]])]
        consts = prove_constants(spec, roots)
        if not consts:
            break
        spec.substitute(consts)
        outs = {k: spec.output(k) for k in spec.profile["Outputs"]}
    return outs


def _np_op(op, a, rec):
    import numpy as np
    if op in ("add", "iadd"): return a[0] + a[1]
    if op in ("sub", "isub"): return a[0] - a[1]
    if op in ("mul", "imul"): return a[0] * a[1]
    if op == "div": return a[0] / a[1]
    if op == "neg": return -a[0]
    if op in ("max", "binop37", "binop39"): return np.maximum(a[0], a[1])
    if op in ("min", "binop38", "binop40"): return np.minimum(a[0], a[1])
    if op == "abs": return np.abs(a[0])
    if op == "saturate": return np.clip(a[0], 0, 1)
    if op == "sqrt": return np.sqrt(a[0])
    if op == "rsqrt": return 1 / np.sqrt(a[0])
    if op == "exp2": return np.exp2(a[0])
    if op == "log2": return np.log2(a[0])
    if op == "frac": return a[0] - np.floor(a[0])
    if op == "floor": return np.floor(a[0])
    if op == "ceil": return np.ceil(a[0])
    if op in ("trunc", "fptoui_i32", "fptosi_i32"): return np.trunc(np.nan_to_num(a[0]))
    if op == "round_ne": return np.round(a[0])
    if op in ("sin", "cos", "tan"): return getattr(np, op)(a[0])
    if op in ("fmod", "isrem"): return np.fmod(a[0], a[1])
    if op == "select": return np.where(a[0] > 0.5, a[1], a[2])
    if op == "and": return a[0] * a[1]
    if op == "or": return np.maximum(a[0], a[1])
    if op == "not": return 1 - a[0]
    if op in ("uitofp_float", "sitofp_float", "zext_i32"): return a[0]
    if op.startswith(("fcmp_", "icmp_")):
        x, y = a
        p = op[5:]
        r = {"olt": x < y, "ult": x < y, "slt": x < y, "ogt": x > y, "ugt": x > y, "sgt": x > y,
             "ole": x <= y, "ule": x <= y, "sle": x <= y, "oge": x >= y, "uge": x >= y, "sge": x >= y,
             "oeq": x == y, "ueq": x == y, "one": x != y, "une": x != y, "eq": x == y, "ne": x != y}[p]
        return r.astype(float)
    if op == "ishl": return a[0] * 2.0 ** a[1]
    if op == "ilshr": return np.floor(a[0] / 2.0 ** a[1])
    if op == "iand":
        m = int(a[1][0]) & 0xffffffff
        return np.mod(a[0], m + 1) if m & (m + 1) == 0 else a[0] - np.mod(a[0], 2)
    if op == "lookup":
        t = np.array(rec["table"])
        return t[np.clip(np.nan_to_num(a[0]).astype(int), 0, len(t) - 1)]
    raise Unsupported("No numeric evaluation for " + op)


def choose_entry(candidates, plans):
    """Alternatives for one layout must agree after specialization; a single bounded difference is noted."""
    import numpy as np
    primary = plans[0]
    notes = []
    keys = [k for k in CONNECTED_OUTPUTS if k in primary["outs"]]
    case = condition_leaves(primary["live"])
    ref = evaluate_spec(primary["spec"], {k: primary["outs"][k] for k in keys}, fixed=case)
    for entry, p in zip(candidates[1:], plans[1:]):
        if set(k for k in CONNECTED_OUTPUTS if k in p["outs"]) != set(keys):
            raise Unsupported("Alternative programs expose different outputs for this vertex layout")
        alt = evaluate_spec(p["spec"], {k: p["outs"][k] for k in keys}, fixed=case)
        diff = {}
        for k, a in ref.items():
            b = alt[k]
            ok = np.isfinite(a) & np.isfinite(b)
            d = float(np.max(np.abs(a[ok] - b[ok]))) if ok.any() else 0.0
            if d > 1e-4:
                diff[k.rstrip("0123456789")] = max(d, diff.get(k.rstrip("0123456789"), 0.0))
        if not diff:
            continue
        coat_only = set(diff) <= {"CoatSmoothness", "RT2.x"}
        glass_only = set(diff) <= {"Transmittance", "Reflectance"}
        limit = PERMUTATION_GLASS_MAX if glass_only else PERMUTATION_MAX
        if (len(diff) == 1 or coat_only or glass_only) and max(diff.values()) <= limit + 1e-6:
            notes.append({"AlternateProgram": entry["Programs"][0], "Outputs": sorted(diff),
                          "MaxDifference": max(diff.values()),
                          "Status": "bounded difference between permutations (%s, at most %.2f); "
                                    "entry with most solutions used"
                                    % ("glass transmittance/reflectance" if glass_only else "one finish constant", limit)})
        else:
            raise Unsupported("Permutations disagree for this vertex layout (%s); selection key unknown"
                             % ", ".join(sorted(diff)))
    return notes
