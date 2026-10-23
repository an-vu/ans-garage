"""Wheel fit: the game's tire and rim resize, per vertex, as a geometry-nodes modifier.

The wheel vertex shaders (tires and rims alike) move each vertex along its wheel radius by
lerp(W.y, W.x + W.z, Color0.b), W (g_wheelCustomizeParam) being offsets from the mesh as modelled, and along the axle:
rims (g_facingParam.w = 1) by (0.5 - Color0.a) * 2 * W.w, tires (g_facingParam.w = 0) by -W.w * Color0.a, so only one
sidewall moves. On a tire, blue 0 is the tread, blue 1 the bead and alpha 0 / 1 the two sidewalls; on an aftermarket
rim, blue rises from the hub (0 on most rims) to the barrel and lip (1), and alpha 1 is the back lip. Factory rims are
shown as modelled (W = 0).

Checked in a frame capture (Lotus Evija rear wheel): tire W = (rim diameter - InnerDiameter) / 2, (tire diameter -
OuterDiameter) / 2, 0, rim width - Width, the sidewall size picked by the rim/tire ratio; factory rim W = 0.

Brake discs and calipers: their vertex shaders scale the whole mesh about the wheel centre by
g_brakeAndCaliperCustomizeParam.x = rim diameter x the rim's BrakeDiscRatio / 0.4 (a 0.4 m reference disc; same
capture: 0.57221 x 0.77 / 0.4 = 1.1015). Done here by a "Brake size" modifier.
"""
GROUP = "Unbound | Wheel fit"
MODIFIER = "Wheel fit"
VERSION = 2
INPUTS = ("Radial offset at blue 0 (W.y)", "Radial offset at blue 1 (W.x + W.z)", "Axle offset (W.w)")
BRAKE_GROUP = "Unbound | Brake size"
BRAKE_MODIFIER = "Brake size"
BRAKE_REFERENCE_DISC = 0.4


def factory_rims(data):
    """{axle: the car's factory rim item (raw)} from its assembly."""
    rims = {}
    for i in data["Items"]:
        if i["Type"] == "RimsItemData" and i["Default"] and i.get("Location"):
            rims[i["Location"].replace("ItemPosition_", "")] = i["Raw"]
    return rims


def rim_diameter(data, tire_config, axle):
    """Diameter of the rim the tire sits on: the car's factory rim on that axle, else the tire configuration's."""
    rim = factory_rims(data).get(axle)
    return rim["Diameter"] if rim and rim.get("Diameter") else tire_config.get("RimDiameter" + axle)


def rim_width(data, tire_config, axle):
    """Width of the rim the tire sits on: the car's factory rim on that axle, else the tire's section width."""
    rim = factory_rims(data).get(axle)
    return rim["Width"] if rim and rim.get("Width") else tire_config.get("SectionWidth" + axle, 0) / 1000.0


def brake_scale(rim, diameter=None):
    """g_brakeAndCaliperCustomizeParam.x for a rim (raw item or library entry) at `diameter` (default its own), or None
    when the rim has no BrakeDiscRatio."""
    ratio = (rim or {}).get("BrakeDiscRatio")
    size = diameter or (rim or {}).get("Diameter")
    return size * ratio / BRAKE_REFERENCE_DISC if ratio and size else None


def tire_size(sizes, rim, diameter, small_to_med, med_to_large):
    """The tire mesh size the game shows for a rim/tire diameter ratio: the small sidewall at SmallToMedRatio or above,
    the large one below MedToLargeRatio, else the medium one. `sizes` are TireMeshInfos (or library sizes)."""
    ordered = sorted(sizes, key=lambda s: -s["InnerDiameter"])
    ratio = rim / diameter
    k = 0 if ratio >= small_to_med else 1 if ratio >= med_to_large else 2
    return ordered[min(k, len(ordered) - 1)]


def tire_offsets(size, diameter, rim, width):
    """W for a tire mesh: tread to the tire diameter, bead to the rim diameter, one sidewall out to the rim width."""
    return (diameter - size["OuterDiameter"]) / 2, (rim - size["InnerDiameter"]) / 2, width - size["Width"]


def rim_offsets(rim, diameter, width):
    """W for an aftermarket rim resized to `diameter` x `width`: the barrel moves to the new radius, the hub and spokes by
    their blue weight, the back lip along the axle."""
    return 0.0, (diameter - rim["Diameter"]) / 2, width - rim["Width"]


def node_group():
    """The shared geometry-nodes group (built once per .blend)."""
    import bpy
    g = bpy.data.node_groups.get(GROUP)
    if g is not None and g.get("unbound_wheel_fit_version") == VERSION:
        return g
    if g is None:
        g = bpy.data.node_groups.new(GROUP, "GeometryNodeTree")
    g.nodes.clear()
    g.interface.clear()
    g["unbound_wheel_fit_version"] = VERSION
    io = g.interface
    io.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    io.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    for name in INPUTS:
        io.new_socket(name, in_out="INPUT", socket_type="NodeSocketFloat").subtype = "DISTANCE"
    io.new_socket("Colour attribute", in_out="INPUT", socket_type="NodeSocketString")
    io.new_socket("Byte colour (sRGB)", in_out="INPUT", socket_type="NodeSocketBool")
    io.new_socket("Tire (one sidewall moves)", in_out="INPUT", socket_type="NodeSocketBool")
    nodes, link = g.nodes, g.links.new
    gi, go = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")

    def math(op, a, b, c=None):
        n = nodes.new("ShaderNodeMath")
        n.operation = op
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                link(v, n.inputs[i])
        return n.outputs[0]

    attr = nodes.new("GeometryNodeInputNamedAttribute")
    attr.data_type = "FLOAT_COLOR"
    link(gi.outputs["Colour attribute"], attr.inputs["Name"])
    rgba = nodes.new("FunctionNodeSeparateColor")
    link(attr.outputs["Attribute"], rgba.inputs["Color"])
    # The shader reads the raw bytes; a byte colour attribute stores them as sRGB, so encode blue back.
    b = rgba.outputs["Blue"]
    high = math("MULTIPLY_ADD", math("POWER", b, 1 / 2.4), 1.055, -0.055)
    encoded = math("MULTIPLY_ADD", math("LESS_THAN", b, 0.0031308), math("SUBTRACT", math("MULTIPLY", b, 12.92), high), high)
    blue = math("MULTIPLY_ADD", gi.outputs["Byte colour (sRGB)"], math("SUBTRACT", encoded, b), b)
    # P.yz += normalize(P.yz) * lerp(W.y, W.x + W.z, blue)
    w_y, w_xz, w_w = (gi.outputs[n] for n in INPUTS)
    radial = math("MULTIPLY_ADD", blue, math("SUBTRACT", w_xz, w_y), w_y)
    pos = nodes.new("ShaderNodeSeparateXYZ")
    link(nodes.new("GeometryNodeInputPosition").outputs[0], pos.inputs[0])
    yz = nodes.new("ShaderNodeCombineXYZ")
    link(pos.outputs["Y"], yz.inputs["Y"])
    link(pos.outputs["Z"], yz.inputs["Z"])
    unit = nodes.new("ShaderNodeVectorMath")
    unit.operation = "NORMALIZE"
    link(yz.outputs[0], unit.inputs[0])
    out = nodes.new("ShaderNodeVectorMath")
    out.operation = "SCALE"
    link(unit.outputs["Vector"], out.inputs[0])
    link(radial, out.inputs["Scale"])
    # Rims: P.x += (0.5 - alpha) * 2 * W.w; tires: P.x -= alpha * W.w
    alpha = rgba.outputs["Alpha"]
    both = math("MULTIPLY_ADD", alpha, -2.0, 1.0)
    side = math("MULTIPLY_ADD", gi.outputs["Tire (one sidewall moves)"], math("SUBTRACT", math("MULTIPLY", alpha, -1.0), both), both)
    axial = nodes.new("ShaderNodeCombineXYZ")
    link(math("MULTIPLY", side, w_w), axial.inputs["X"])
    offset = nodes.new("ShaderNodeVectorMath")
    offset.operation = "ADD"
    link(out.outputs["Vector"], offset.inputs[0])
    link(axial.outputs[0], offset.inputs[1])
    setpos = nodes.new("GeometryNodeSetPosition")
    link(gi.outputs["Geometry"], setpos.inputs["Geometry"])
    link(offset.outputs["Vector"], setpos.inputs["Offset"])
    link(setpos.outputs["Geometry"], go.inputs["Geometry"])
    return g


def _set_input(modifier, identifier, value):
    inputs = getattr(getattr(modifier, "properties", None), "inputs", None)
    if inputs is not None:  # Blender 5
        getattr(inputs, identifier).value = value
    else:
        modifier[identifier] = value


def fit(objects, offsets, tire=False):
    """Give each mesh with vertex colours a Wheel fit modifier with these offsets in metres (W.y, W.x + W.z, W.w), as a
    tire (one sidewall moves) or a rim. Meshes without vertex colours are left as modelled. Returns the fitted objects."""
    group = node_group()
    ids = {i.name: i.identifier for i in group.interface.items_tree if getattr(i, "in_out", None) == "INPUT"}
    fitted = []
    for o in objects:
        if o.type != "MESH" or not o.data.color_attributes:
            continue
        colour = o.data.color_attributes[0]  # Color0, the mesh's first vertex colour stream
        m = o.modifiers.get(MODIFIER) or o.modifiers.new(MODIFIER, "NODES")
        m.node_group = group
        for name, value in zip(INPUTS, offsets):
            _set_input(m, ids[name], float(value))
        _set_input(m, ids["Colour attribute"], colour.name)
        _set_input(m, ids["Byte colour (sRGB)"], colour.data_type == "BYTE_COLOR")
        _set_input(m, ids["Tire (one sidewall moves)"], bool(tire))
        o["unbound_wheel_fit"] = [float(v) for v in offsets]
        o["unbound_wheel_fit_tire"] = bool(tire)
        fitted.append(o)
    return fitted


def brake_group():
    """The shared geometry-nodes group scaling a brake disc or caliper about the wheel centre (built once per .blend)."""
    import bpy
    g = bpy.data.node_groups.get(BRAKE_GROUP)
    if g is not None and g.get("unbound_wheel_fit_version") == VERSION:
        return g
    if g is None:
        g = bpy.data.node_groups.new(BRAKE_GROUP, "GeometryNodeTree")
    g.nodes.clear()
    g.interface.clear()
    g["unbound_wheel_fit_version"] = VERSION
    g.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    g.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    size = g.interface.new_socket("Scale (g_brakeAndCaliperCustomizeParam.x)", in_out="INPUT", socket_type="NodeSocketFloat")
    size.default_value = 1.0
    nodes, link = g.nodes, g.links.new
    gi, go = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    scaled = nodes.new("ShaderNodeVectorMath")
    scaled.operation = "SCALE"
    link(nodes.new("GeometryNodeInputPosition").outputs[0], scaled.inputs[0])
    link(gi.outputs[1], scaled.inputs["Scale"])
    setpos = nodes.new("GeometryNodeSetPosition")
    link(gi.outputs[0], setpos.inputs["Geometry"])
    link(scaled.outputs["Vector"], setpos.inputs["Position"])
    link(setpos.outputs["Geometry"], go.inputs[0])
    return g


def size_brakes(objects, scale):
    """Give each brake mesh a Brake size modifier at `scale` (updated when it already has one). Returns the objects."""
    group = brake_group()
    ident = next(i.identifier for i in group.interface.items_tree
                 if getattr(i, "in_out", None) == "INPUT" and i.socket_type == "NodeSocketFloat")
    sized = []
    for o in objects:
        if o.type != "MESH":
            continue
        m = o.modifiers.get(BRAKE_MODIFIER) or o.modifiers.new(BRAKE_MODIFIER, "NODES")
        m.node_group = group
        _set_input(m, ident, float(scale))
        o["unbound_brake_scale"] = float(scale)
        sized.append(o)
    return sized
