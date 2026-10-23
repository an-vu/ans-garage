"""Moving parts: doors, windows, hood, boot and active aero (wings, vents, airbrakes) as 0-1 sliders.

Everything comes from the vehicle blueprint's own animation graph in assembly.json (field names are Frosty field-name
hashes, resolved below); nothing is posed by hand.
- Doors, windows, hood, boot: NamedAnimationPropertyEntityData.Value drives TransformAnimationEntityData.T. Its curves
  (degrees, metres) turn and move the part about the entity's Origin; its Transform reaches the part through
  AnimateComponentEntityData.
- Active aero: AnimationComponentData drives SequenceEntityData.ExternalTime (the airbrake through a MathEntityData).
  The sequence's transform tracks (keys in TrackData) reach a component's Transform or TransformOffset through
  TransformBlendEntityData (In2, weighted by the spoiler item's AnimationExtent: stock 1, aftermarket 0),
  TransformMultiplierEntityData (In1, then In2) and RealmTransformCombinerEntityData (ClientTransform).
- Pop-up headlights: two sequences played by light events (no ExternalTime) feed a TransformHubEntityData, which passes
  on whichever played last. The one starting at rest opens the lights and becomes the slider; the other is its reverse.
A slider is one source input from 0 to 1: the property's T, or the sequence time across its keys. The game's speed
logic (when a wing rises) and light switching are not reproduced.

In Blender each moving component is an empty; a slider drives its Action constraint (evaluation time), so no Python
drivers are needed. Body parts follow their bone (PART_<physics part index>) through a Child Of constraint; item
meshes (mirrors, hood, boot, spoiler) are parented to the empty.
"""
import json
import math

from .unbound_assembly import matrix_from_basis, world_matrix

SAMPLES = 100
# Euler order of TransformPart / Rotate* channels: yaw (Y), then pitch (X), then roll (Z). Not stated by the data; of
# the six orders only those applying roll last open the P1's dihedral doors upward (the others swing them out at
# waist height). The remaining roll-last orders differ by under 5 cm there.
EULER_ORDER = "ZXY"
PROPERTY_LABELS = {"ldooropen": ("Doors", "Left door"), "rdooropen": ("Doors", "Right door"),
                   "ldoorwindowopen": ("Windows", "Left window"), "rdoorwindowopen": ("Windows", "Right window"),
                   "hoodopen": ("Hood and boot", "Hood"), "bootopen": ("Hood and boot", "Boot"),
                   "ldoorrearopen": ("Doors", "Left rear door"), "rdoorrearopen": ("Doors", "Right rear door"),
                   "ldoorrearwindowopen": ("Windows", "Left rear window"),
                   "rdoorrearwindowopen": ("Windows", "Right rear window")}
GROUPS = ("Active aero", "Lights", "Doors", "Windows", "Hood and boot", "Other")
CHANNELS = {"TranslationX": ("T", 0), "TranslationY": ("T", 1), "TranslationZ": ("T", 2),
            "RotationX": ("R", 0), "RotationY": ("R", 1), "RotationZ": ("R", 2)}


class Unsupported(Exception):
    pass


def field(name):
    """Frosty field-name hash, as connection fields are stored ("0x%08x")."""
    h = 5381
    for c in name.encode():
        h = ((h * 33) ^ c) & 0xFFFFFFFF
    return "0x%08x" % h


def _ref(r):
    return r.get("Node") if isinstance(r, dict) else None


class Graph:
    def __init__(self, data):
        self.data = data
        self.nodes = {n["Id"]: n for n in data["Nodes"]}
        root = self.nodes[data["Vehicle"]["Node"]]["Raw"]
        self.props = [(_ref(c["Source"]), c.get("SourceField"), _ref(c["Target"]), c.get("TargetField"), c.get("SourceFieldId"))
                      for c in root.get("PropertyConnections") or []]
        self.links = [(_ref(c["Source"]), _ref(c["Target"])) for c in root.get("LinkConnections") or []]
        self.comps = {c["Node"]: c for c in data.get("Components", [])}

    def type(self, node):
        return (self.nodes.get(node) or {}).get("Type")

    def raw(self, node):
        return self.nodes[node]["Raw"]

    def into(self, node, name):
        return [(s, sf) for s, sf, t, tf, _ in self.props if t == node and tf == field(name)]

    def out(self, node, name):
        return [(t, tf) for s, sf, t, tf, _ in self.props if s == node and sf == field(name)]

    def ancestors(self, comp):
        """The component and its parents, leaf first."""
        chain = []
        while comp in self.comps and comp not in chain:
            chain.append(comp)
            comp = self.comps[comp].get("Parent")
        return chain


# ------------------------------------------------------------------ curves
def curve_value(curve, t):
    """CurveData: CurveType_Zero or CurveType_Basic_Linear, constant outside its keys."""
    kind = (curve.get("CurveType") or {}).get("Name")
    times, values = curve.get("Time") or [], curve.get("Value") or []
    if kind == "CurveType_Zero":
        return 0.0
    if kind != "CurveType_Basic_Linear" or not times or len(times) != len(values):
        raise Unsupported("Curve type %s is not supported" % kind)
    if t <= times[0]:
        return values[0]
    for i in range(1, len(times)):
        if t <= times[i]:
            u = (t - times[i - 1]) / (times[i] - times[i - 1]) if times[i] > times[i - 1] else 1.0
            return values[i - 1] + (values[i] - values[i - 1]) * u
    return values[-1]


def track_value(keys, t):
    """Sequence track keys (time, value, in-tangent x/y, out-tangent x/y): cubic Hermite, constant outside."""
    if not keys:
        return 0.0
    if t <= keys[0][0]:
        return keys[0][1]
    for a, b in zip(keys, keys[1:]):
        if t <= b[0]:
            span = b[0] - a[0]
            if span <= 0:
                return b[1]
            if abs(a[4]) < 1e-9 or abs(b[2]) < 1e-9:
                raise Unsupported("Vertical tangent in a sequence track")
            m0, m1 = a[5] / a[4] * span, b[3] / b[2] * span
            u = (t - a[0]) / span
            u2, u3 = u * u, u * u * u
            return ((2 * u3 - 3 * u2 + 1) * a[1] + (u3 - 2 * u2 + u) * m0 + (-2 * u3 + 3 * u2) * b[1] + (u3 - u2) * m1)
    return keys[-1][1]


def _trs(translation, degrees):
    from mathutils import Matrix
    rotation = Matrix.Identity(4)
    for axis in EULER_ORDER:
        rotation = rotation @ Matrix.Rotation(math.radians(degrees["XYZ".index(axis)]), 4, axis)
    return Matrix.Translation(translation) @ rotation


def factor_matrix(factor, s):
    """Source transform (Frostbite axes, column vectors) of one factor at slider value s in 0..1."""
    from mathutils import Matrix
    if factor["Kind"] == "Curves":
        t = factor["Start"] + (factor["End"] - factor["Start"]) * s
        c = factor["Curves"]
        m = _trs([curve_value(c["Translate" + a], t) for a in "XYZ"], [curve_value(c["Rotate" + a], t) for a in "XYZ"])
        origin = matrix_from_basis(factor["Origin"])
        return origin @ m @ origin.inverted()
    t = factor["Start"] + (factor["End"] - factor["Start"]) * s
    values = {"T": [0.0, 0.0, 0.0], "R": [0.0, 0.0, 0.0]}
    for name, keys in factor["Channels"].items():
        kind, axis = CHANNELS[name]
        values[kind][axis] = track_value(keys, t)
    return _trs(values["T"], values["R"]) if values else Matrix.Identity(4)


# ------------------------------------------------------------------ source graph
def _named_properties(g, moving, controls, skipped, issues):
    for node, n in g.nodes.items():
        if n["Type"] != "NamedAnimationPropertyEntityData" or not any(s == node for s, *_ in g.props):
            continue
        key = ((n["Raw"].get("Info") or {}).get("Asset") or node).rsplit("/", 1)[-1].split("propertyinfo_")[-1].lower()
        for target, tf in g.out(node, "Value"):
            if g.type(target) != "TransformAnimationEntityData" or tf != field("T"):
                skipped.append({"Control": key, "Reason": "drives %s (a runtime effect, not a moving part)" % g.type(target)})
                continue
            raw = g.raw(target)
            try:
                curves = {}
                for kind in ("Translate", "Rotate"):
                    for a in "XYZ":
                        ref = _ref(raw.get(kind + a + "CurveData"))
                        if ref not in g.nodes:
                            raise Unsupported("Missing %s%s curve" % (kind, a))
                        curves[kind + a] = g.raw(ref)
                times = [t for c in curves.values() if (c.get("CurveType") or {}).get("Name") != "CurveType_Zero" for t in c["Time"]]
                factor = {"Kind": "Curves", "Origin": raw["Origin"]["Basis"], "Curves": curves,
                          "Start": min(times) if times else 0.0, "End": max(times) if times else 1.0}
                factor_matrix(factor, 0.5)  # every curve type is supported
                comps = []
                for animate, af in g.out(target, "Transform"):
                    if g.type(animate) == "AnimateComponentEntityData" and af == field("Transform"):
                        comps += [t for s, t in g.links if s == animate and t in g.comps]
                if len(comps) != 1:
                    raise Unsupported("Expected one animated component, found %d" % len(comps))
                _add(moving, comps[0], "Transform", key, factor, 0, None)
                group, label = PROPERTY_LABELS.get(key, ("Other", key))
                if not any(c["Key"] == key for c in controls):
                    controls.append({"Key": key, "Label": label, "Group": group, "Source": "NamedAnimationProperty " + key})
            except (Unsupported, KeyError, TypeError) as exc:
                issues.append("%s: %s" % (key, exc))


def _follow(g, node, infield, path, out):
    """From a sequence output into the transform graph, down to a component field."""
    typ = g.type(node)
    if node in g.comps and infield in (field("Transform"), field("TransformOffset")):
        out.append((node, "Transform" if infield == field("Transform") else "TransformOffset", path))
        return
    if typ == "TransformBlendEntityData" and infield == field("In2"):
        if g.into(node, "In1") or any(abs(a - b) > 1e-6 for a, b in zip(g.raw(node)["In1"]["Basis"], [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0])):
            raise Unsupported("Transform blend with a non-identity In1")
        weights = g.into(node, "BlendValue")
        if len(weights) != 1 or weights[0][1] != field("AnimationExtent") or weights[0][0] not in g.comps:
            raise Unsupported("Transform blend weight is not a component's AnimationExtent")
        path = path + [("Extent", weights[0][0])]
    elif typ == "TransformMultiplierEntityData" and infield in (field("In1"), field("In2")):
        path = path + [("Multiply", 1 if infield == field("In1") else 0)]
    elif typ == "TransformHubEntityData" and infield in (field("In1"), field("In2")):
        # Passes on whichever input changed last: an opening and a closing sequence share it.
        path = path + [("Hub", node)]
    elif not (typ == "RealmTransformCombinerEntityData" and infield == field("ClientTransform")):
        raise Unsupported("Sequence output reaches %s.%s" % (typ, infield))
    for target, tf in g.out(node, "Out"):
        _follow(g, target, tf, path, out)


def _sequences(g, moving, controls, skipped, issues):
    tracks_data = g.data.get("TrackData") or {}
    for node, n in g.nodes.items():
        if n["Type"] != "SequenceEntityData" or not any(node in (s, t) for s, _, t, *_ in g.props):
            continue
        drivers = g.into(node, "ExternalTime")
        source = g.type(drivers[0][0]) if len(drivers) == 1 else None
        if source == "AnimationComponentData":
            key, group = "aero", "Active aero"
        elif source == "MathEntityData" and any(g.type(s) == "AnimationComponentData" for s, _ in g.into(drivers[0][0], "Value")):
            key, group = "airbrake", "Active aero"
        elif source == "LogicPrefabReferenceObjectData" and "spoiler" in (
                (g.raw(drivers[0][0]).get("Blueprint") or {}).get("Asset") or "").lower():
            key, group = "aero", "Active aero"  # the spoiler-stage prefab (vehicles/CarSpoilerAnim_3Stages) sets the time
        elif not drivers:
            key, group = None, None  # played by events (e.g. pop-up headlights): decided below
        else:
            skipped.append({"Control": "sequence " + node.rsplit(":", 1)[-1], "Reason": "not driven by the vehicle's animation component"})
            continue
        try:
            by_id, names, times = {}, [], []
            for ref in n["Raw"].get("PropertyTracks") or []:
                track = g.raw(_ref(ref))
                if track.get("Type") != "TransformPartPropertyTrackData":
                    raise Unsupported("Track type %s" % track.get("Type"))
                part = (track.get("TransformPart") or {}).get("Name", "").replace("TransformPart_", "")
                if part not in CHANNELS:
                    raise Unsupported("Track channel %s" % part)
                res = tracks_data.get(track["Resource"])
                if res is None:
                    raise Unsupported("Track keys missing: export the vehicle again with An's Garage for Frosty 1.0.0")
                f = res["Floats"]
                start, count = track["KeyStartIndex"], track["KeyCount"]
                keys = [f[i * 6:i * 6 + 6] for i in range(start, start + count)]
                if any(len(k) != 6 for k in keys):
                    raise Unsupported("Track keys out of range")
                by_id.setdefault(track["Id"], {})[part] = keys
                names.append(res["Name"].rsplit("/", 1)[-1].split("_", 1)[-1].lower())  # "<guid>_headlight_l" -> "headlight_l"
                times += [k[0] for k in keys]
            if not times:
                raise Unsupported("Sequence without keys")
            reached = []
            for track_id, channels in by_id.items():
                factor = {"Kind": "Tracks", "Channels": channels, "Start": min(times), "End": max(times)}
                factor_matrix(factor, 0.5)
                for s, sf, target, tf, sid in g.props:
                    if s != node or sid != track_id:
                        continue
                    found = []
                    _follow(g, target, tf, [], found)
                    reached += [(comp, fld, factor, path) for comp, fld, path in found]
            if not reached:
                raise Unsupported("No component reached")
            if key is None:
                # Event-played sequences come in pairs through a transform hub: the one that starts at rest opens the
                # part (the slider); the other plays it back closed.
                if not all(any(kind == "Hub" for kind, _ in path) for *_, path in reached):
                    skipped.append({"Control": "sequence " + node.rsplit(":", 1)[-1], "Reason": "played by events without a transform hub"})
                    continue
                if not all(_is_identity(factor_matrix(f, 0.0)) for _, _, f, _ in reached):
                    skipped.append({"Control": "sequence " + node.rsplit(":", 1)[-1] + " (" + ", ".join(sorted(set(names))) + ")",
                                    "Reason": "closing sequence: plays the opening one back"})
                    continue
                if any("headlight" in x for x in names):
                    key, group, label = "popup_headlights", "Lights", "Pop-up headlights"
                elif any("arial" in x or "aerial" in x or "antenna" in x for x in names):
                    key, group, label = "antenna", "Other", "Antenna"  # the game's tracks spell it "arial"
                else:
                    key, group, label = "sequence_" + node.rsplit(":", 1)[-1], "Other", ", ".join(sorted(set(names)))
            elif key == "aero":
                label = "Rear wing" if any("spoiler" in x or "wing" in x for x in names) else \
                    "Air vents" if any("vent" in x for x in names) else "Active aero"
            else:
                label = "Airbrake"
            for comp, fld, factor, path in reached:
                extent = next((c for kind, c in path if kind == "Extent"), None)
                order = next((o for kind, o in path if kind == "Multiply"), 0)
                _add(moving, comp, fld, key, factor, order, extent)
            if not any(c["Key"] == key for c in controls):
                controls.append({"Key": key, "Label": label, "Group": group, "Source": "SequenceEntity " + ", ".join(sorted(set(names)))})
        except (Unsupported, KeyError, TypeError) as exc:
            issues.append("%s sequence: %s" % (key, exc))


def _is_identity(m, tolerance=1e-5):
    return all(abs(m[i][j] - (1.0 if i == j else 0.0)) <= tolerance for i in range(4) for j in range(4))


def _add(moving, comp, fld, key, factor, order, extent):
    entry = moving.setdefault(comp, {"Field": fld, "Factors": []})
    if entry["Field"] != fld:
        raise Unsupported("Component driven through both Transform and TransformOffset")
    entry["Factors"].append({"Control": key, "Factor": factor, "Order": order, "Extent": extent})


def analyse(data):
    """Moving components and their sliders from the assembly's source graph (no Blender data needed)."""
    g = Graph(data)
    moving, controls, skipped, issues = {}, [], [], []
    _named_properties(g, moving, controls, skipped, issues)
    _sequences(g, moving, controls, skipped, issues)
    for entry in moving.values():
        # Column order: TransformMultiplier In2 is applied after In1 (In1 * In2 in Frostbite's row-vector form).
        entry["Factors"].sort(key=lambda f: f["Order"])
    controls.sort(key=lambda c: (GROUPS.index(c["Group"]), c["Key"] == "airbrake", c["Label"]))
    return {"Graph": g, "Moving": moving, "Controls": controls, "Skipped": skipped, "Issues": issues}


def moving_owner(g, moving, comp):
    return next((c for c in g.ancestors(comp) if c in moving), None)


# ------------------------------------------------------------------ Blender
def _action(name, obj, frames):
    """Object action with location and Euler keys at frames 0..SAMPLES (linear). Euler, not quaternion: the Action
    constraint evaluates an object's quaternion channels wrongly (checked in Blender 5.2), Euler channels exactly."""
    import bpy
    act = bpy.data.actions.new(name)
    if hasattr(act, "layers"):
        slot = act.slots.new(id_type="OBJECT", name=obj.name)
        strip = act.layers.new("Layer").strips.new(type="KEYFRAME")
        bag = strip.channelbag(slot, ensure=True)
        new = bag.fcurves.new
    else:
        slot, new = None, act.fcurves.new
    for path, count in (("location", 3), ("rotation_euler", 3)):
        series = []
        previous = None
        for m in frames:
            if path == "location":
                series.append(list(m.to_translation()))
            else:
                previous = m.to_euler("XYZ", previous) if previous is not None else m.to_euler("XYZ")
                series.append(list(previous))
        for index in range(count):
            fc = new(path, index=index)
            fc.keyframe_points.add(len(frames))
            co = [x for i, row in enumerate(series) for x in (float(i), row[index])]
            fc.keyframe_points.foreach_set("co", co)
            fc.keyframe_points.foreach_set("interpolation", [1] * len(frames))  # LINEAR
            fc.update()
    return act, slot


def _drive(constraint, controls_obj, key):
    curve = constraint.driver_add("eval_time")
    driver = curve.driver
    driver.type = "AVERAGE"
    var = driver.variables.new()
    var.type = "SINGLE_PROP"
    var.targets[0].id_type = "OBJECT"
    var.targets[0].id = controls_obj
    var.targets[0].data_path = '["%s"]' % key
    for m in list(curve.modifiers):
        curve.modifiers.remove(m)


def _body_armature(root):
    body = next((c for c in root.children if c.name.split(".")[0] == "Body"), None)
    for inst in (body.children if body else []):
        arms = [o for o in inst.all_objects if o.type == "ARMATURE"]
        if arms:
            return arms[0]
    return None


def build(root):
    """Sliders and rig for the moving parts of an assembled vehicle. Returns the report (also on the root)."""
    import bpy
    from collections import defaultdict
    from mathutils import Matrix
    data = json.loads(open(root["unbound_assembly_path"], encoding="utf-8-sig").read())
    result = analyse(data)
    g, moving = result["Graph"], result["Moving"]
    issues = list(result["Issues"])
    conv = Matrix(json.loads(root["fbx_to_blender_matrix"]))
    inv = conv.inverted()
    report = {"Controls": [], "Skipped": result["Skipped"], "Issues": issues, "EulerOrder": EULER_ORDER}
    old = bpy.data.objects.get(root.get("ans_garage_controls", ""))
    if old is not None:
        raise ValueError("Moving parts already exist for %s" % root.name)
    if not moving:
        root["ans_garage_moving_parts_json"] = json.dumps(report)
        return report
    rig = bpy.data.collections.new(root.name + " | Moving parts rig")
    root.children.link(rig)
    controls_obj = bpy.data.objects.new(root.name + " | Moving parts", None)
    controls_obj.empty_display_size = 0.01
    rig.objects.link(controls_obj)
    for c in result["Controls"]:
        controls_obj[c["Key"]] = 0.0
        ui = controls_obj.id_properties_ui(c["Key"])
        ui.update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, step=1, precision=2,
                  description="%s: 0 closed, 1 fully open (source: %s)" % (c["Label"], c["Source"]))

    def local_matrix(comp, values):
        m = Matrix.Identity(4)
        for f in moving[comp]["Factors"]:
            m = m @ factor_matrix(f["Factor"], values.get(f["Control"], 0.0))
        return m

    def world(comp, values):
        """Car-space transform of a component with the sliders at the given values."""
        m = Matrix.Identity(4)
        for c in reversed(g.ancestors(comp)):
            if c in moving:
                if moving[c]["Field"] == "TransformOffset":
                    m = m @ matrix_from_basis(g.comps[c]["Transform"])
                m = m @ local_matrix(c, values)
            else:
                m = m @ matrix_from_basis(g.comps[c]["Transform"])
        return m

    # One empty chain per moving component: a fixed base (static transforms since the nearest moving ancestor), then
    # one empty per factor, each keyed over its slider. Ancestors first so parents exist.
    frames_of = {}
    ends = {}
    order = sorted(moving, key=lambda c: len(g.ancestors(c)))
    label_of = {c["Key"]: c["Label"] for c in result["Controls"]}
    for comp in order:
        try:
            owner = moving_owner(g, moving, g.comps[comp].get("Parent"))
            static = Matrix.Identity(4)
            for c in reversed(g.ancestors(comp)):
                if owner is not None and c in g.ancestors(owner):
                    continue
                if c == comp and moving[comp]["Field"] == "Transform":
                    continue
                static = static @ matrix_from_basis(g.comps[c]["Transform"])
            names = sorted({label_of[f["Control"]] for f in moving[comp]["Factors"]})
            base = bpy.data.objects.new("Moving | %s | %s" % (" + ".join(names), comp.rsplit(":", 1)[-1]), None)
            base.empty_display_size = 0.05
            rig.objects.link(base)
            base.parent = ends.get(owner)
            base.matrix_basis = conv @ static @ inv
            parent = base
            for f in moving[comp]["Factors"]:
                e = bpy.data.objects.new(base.name + " | " + label_of[f["Control"]], None)
                e.empty_display_size = 0.05
                rig.objects.link(e)
                e.parent = parent
                frames = [conv @ factor_matrix(f["Factor"], i / SAMPLES) @ inv for i in range(SAMPLES + 1)]
                act, slot = _action(e.name, e, frames)
                con = e.constraints.new("ACTION")
                con.action = act
                if slot is not None and hasattr(con, "action_slot"):
                    con.action_slot = slot
                con.use_eval_time = True
                con.frame_start, con.frame_end = 0, SAMPLES
                _drive(con, controls_obj, f["Control"])
                parent = e
            ends[comp] = parent
            frames_of[comp] = world(comp, {})
        except Exception as exc:
            issues.append("%s: %s" % (comp.rsplit(":", 1)[-1], exc))
    attached = defaultdict(int)

    def needs_extent(comp, item):
        """False when the selected item turns the motion off (AnimationExtent 0, like every aftermarket spoiler)."""
        gated = [f for c in g.ancestors(comp) if c in moving for f in moving[c]["Factors"] if f["Extent"]]
        if not gated:
            return True
        extent = (item or {}).get("Raw", {}).get("AnimationExtent")
        if extent in (0, 0.0):
            return False
        if extent in (1, 1.0):
            return True
        raise Unsupported("AnimationExtent %s between 0 and 1" % extent)

    # Body parts: bones PART_<physics part index> of the body armature.
    arm = _body_armature(root)
    phys = next((n for n in data["Nodes"] if n["Type"] == "RaceVehiclePhysicsComponentData"), None)
    parts = [_ref(p.get("TransformNode")) for p in (phys["Raw"].get("Parts") or [])] if phys else []
    if arm is not None:
        for index, part in enumerate(parts):
            comp = moving_owner(g, moving, part) if part else None
            bone = arm.pose.bones.get("PART_%d" % index)
            if comp is None or comp not in ends or bone is None:
                continue
            # The bone moves relative to its imported pose (which already places parts modelled around their own
            # origin, e.g. the Murciélago's vents). A bone's Child Of gives empty(s) @ inverse @ pose basis, so with
            # inverse = empty(0)^-1 @ bone rest the bone follows the empty's motion since slider 0.
            rest = world_matrix(arm) @ bone.bone.matrix_local
            con = bone.constraints.new("CHILD_OF")
            con.name = "An's Garage moving part"
            con.target = ends[comp]
            con.inverse_matrix = (conv @ frames_of[comp] @ inv).inverted() @ rest
            con.set_inverse_pending = False
            attached[comp] += 1
    else:
        issues.append("Body armature not found; body parts stay still")

    # Item meshes on moving components (or below them): parented to the component's last empty.
    items = {i["Asset"]: i for i in data["Items"]}
    owners = data.get("BlueprintComponents") or {}
    for inst in [c for c in bpy.data.collections if c.get("source_blueprint_guid")]:
        if not any(inst.name in p.children for p in _collections(root)):
            continue
        bp = inst["source_blueprint_guid"]
        comps = {moving_owner(g, moving, o["Component"]) for o in owners.get(bp, [])}
        comps.discard(None)
        if not comps:
            continue
        if len(comps) > 1:
            issues.append("%s: placed on several moving components; kept still" % inst.name)
            continue
        comp = comps.pop()
        if comp not in ends:
            continue
        variant = next((p for p in _collections(root) if inst.name in p.children), None)
        try:
            if not needs_extent(comp, items.get(variant.get("unbound_item") if variant else None)):
                continue
        except Unsupported as exc:
            issues.append("%s: %s" % (inst.name, exc))
            continue
        rest = conv @ frames_of[comp] @ inv
        for o in inst.all_objects:
            if o.parent is None or o.parent.name not in inst.all_objects:
                matrix = world_matrix(o)
                o["ans_garage_rest_matrix_json"] = json.dumps([list(r) for r in matrix])
                o.parent = ends[comp]
                o.matrix_parent_inverse = rest.inverted()
                o.matrix_basis = matrix
        attached[comp] += 1
    for c in result["Controls"]:
        comps = [comp for comp, entry in moving.items() if any(f["Control"] == c["Key"] for f in entry["Factors"])]
        moved = sum(attached[comp] for comp in comps)
        entry = dict(c, Components=[x.rsplit(":", 1)[-1] for x in comps], Attached=moved)
        if moved:
            report["Controls"].append(entry)
        else:
            issues.append("%s: no geometry found on its components; slider not shown" % c["Label"])
            del controls_obj[c["Key"]]
    root["ans_garage_controls"] = controls_obj.name
    root["ans_garage_moving_parts_json"] = json.dumps(report)
    layer = _layer(bpy.context.view_layer.layer_collection, rig)
    if layer is not None:
        layer.hide_viewport = True
    return report


def _collections(root):
    yield root
    for child in root.children:
        yield from _collections(child)


def _layer(layer, collection):
    if layer.collection == collection:
        return layer
    for child in layer.children:
        found = _layer(child, collection)
        if found is not None:
            return found
    return None


def controls(root):
    """(controls object, [control dicts]) of a vehicle with moving parts, else (None, [])."""
    import bpy
    obj = bpy.data.objects.get(root.get("ans_garage_controls", ""))
    if obj is None:
        return None, []
    return obj, json.loads(root.get("ans_garage_moving_parts_json") or "{}").get("Controls", [])
