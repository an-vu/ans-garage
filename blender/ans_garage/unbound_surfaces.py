"""Verified shader profiles applied to existing source material slots.

This module never edits geometry or guesses a UV layer from its ordinal/name.
Version 0.5.0 supports the static base layer of one exact Unbound tire shader.
Version 0.6.0 adds compiled source-shader profiles (unbound_profiles.py) for the other deferred shaders.
"""
import hashlib
import json
from pathlib import Path

VERSION = "0.8.1"
PROFILE = json.loads(Path(__file__).with_name("tire_shader_evidence.json").read_text(encoding="utf-8"))
CORE_TEXTURES = ("RGB_Color_A_Smoothness", "RG_Normal_A_AO")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def supported(state):
    shader = state.get("Shader") or {}
    expected = PROFILE["ShaderFileGuid"].replace("-", "") + ":" + PROFILE["ShaderClassGuid"].replace("-", "")
    return (shader.get("Asset", "").casefold() == PROFILE["ShaderAsset"].casefold()
            and shader.get("Node", "").lower() == expected)


def validate_parameters(state):
    """Fail closed on overrides whose effect the static profile cannot reproduce."""
    params = state.get("Parameters", {})
    for kind in ("BoolParameters", "ConditionalParameters", "VectorArrayParameters"):
        if params.get(kind):
            raise ValueError("Unsupported " + kind + "; source material preserved")
    defaults = {k.casefold(): v for k, v in PROFILE["Defaults"].items()}
    for key, parameter in params.get("VectorParameters", {}).items():
        value = parameter.get("Value", {})
        if not isinstance(value, dict) or key not in defaults:
            raise ValueError("Unverified vector override: " + key)
        actual = [value.get(c, 0) for c in "xyzw"]
        if any(abs(a-b) > 1e-6 for a, b in zip(actual, defaults[key])):
            raise ValueError("Non-default runtime parameter is unsupported: " + key)
    allowed = {x.casefold() for x in CORE_TEXTURES} | {"rg_normalblur_a_aoblur"}
    for b in state.get("TextureBindings", []):
        if b["Parameter"].casefold() not in allowed:
            raise ValueError("Unverified texture layer: " + b["Parameter"])
    bindings = {b["Parameter"].casefold(): b for b in state["TextureBindings"]}
    for name in CORE_TEXTURES:
        if name.casefold() not in bindings:
            raise ValueError("Missing required texture: " + name)
    cs, no = (bindings[n.casefold()] for n in CORE_TEXTURES)
    if cs.get("ColorSpace") != "sRGB" or cs.get("Format") != "BC7_SRGB":
        raise ValueError("Unverified color/smoothness format or transfer function")
    if no.get("Format") != "BC7_UNORM":
        raise ValueError("Unverified normal/AO format")
    return cs, no


def source_uv(obj):
    bindings = json.loads(obj.get("unbound_uv_bindings_json", "[]"))
    usage = PROFILE["UV"][CORE_TEXTURES[0]]["SourceUsage"]
    if PROFILE["UV"][CORE_TEXTURES[1]]["SourceUsage"] != usage:
        raise ValueError("Profile needs separate texture UVs")
    matches = [b for b in bindings if b.get("SourceUsage") == usage]
    if len(matches) != 1 or matches[0].get("BlenderLayer") not in obj.data.uv_layers:
        raise ValueError("Missing/ambiguous " + usage + " mapping; no default UV chosen")
    return matches[0]["BlenderLayer"]


def _inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Source path escapes export folder")
    return path


def locate_export(obj, state, explicit, documents):
    """Recover a moved folder only after matching mesh and texture identities."""
    import bpy
    candidates = []
    if explicit:
        p = Path(explicit).resolve()
        candidates.append(p if p.is_dir() else p.parent)
    else:
        if obj.get("unbound_materials_path"):
            candidates.append(Path(obj["unbound_materials_path"]).parent)
        if bpy.context.scene.get("unbound_export_root"):
            candidates.append(Path(bpy.context.scene["unbound_export_root"]))
        if bpy.data.filepath:
            candidates.append(Path(bpy.data.filepath).parent)
    for root in dict.fromkeys(candidates):
        manifest = root / "materials.json"
        if not manifest.is_file():
            continue
        if manifest not in documents:
            documents[manifest] = json.loads(manifest.read_text(encoding="utf-8-sig"))
        doc = documents[manifest]
        meshes = [m for m in doc.get("Meshes", []) if m["MeshId"] == obj.get("unbound_mesh_id")]
        if len(meshes) != 1:
            continue
        textures = {t["ResourceId"]: t for t in doc.get("Textures", [])}
        if all(b.get("ResourceId") in textures and textures[b["ResourceId"]].get("Path") == b.get("Path")
               for b in state["TextureBindings"]):
            bpy.context.scene["unbound_export_root"] = str(root)
            return root, meshes[0]
    raise ValueError("Matching export folder not found. Use Locate export manifest in the Unbound panel")


def tangent_basis(obj, mesh_record, root, layer, cache):
    """Compare this actual mesh's FBX basis with Blender, before wiring normals."""
    import numpy as np
    from io_scene_fbx import parse_fbx
    cache_key = (obj.data.as_pointer(), layer, str(root), obj.get("unbound_fbx_geometry_id"))
    if cache_key in cache:
        return cache[cache_key]
    try:
        tree, _ = parse_fbx.parse(str(_inside(root, mesh_record["Fbx"])))
        def child(node, name):
            return next((x for x in node.elems if x.id == name), None)
        objects = child(tree, b"Objects")
        geometries = [g for g in objects.elems if g.id == b"Geometry"
                      and str(g.props[0]) == str(obj.get("unbound_fbx_geometry_id"))]
        if len(geometries) != 1:
            raise ValueError("FBX section identity missing")
        g = geometries[0]
        source_positions = np.asarray(child(g, b"Vertices").props[0]).reshape(-1, 3)
        positions = np.array([v.co[:] for v in obj.data.vertices])
        if source_positions.shape != positions.shape or not np.allclose(source_positions, positions, atol=1e-6, rtol=0):
            raise ValueError("Mesh positions differ from source FBX")
        obj.data.calc_tangents(uvmap=layer)
        loops = list(obj.data.loops)
        indices = [loop.vertex_index for loop in loops]
        result = {"Status": "verified_against_source_fbx", "MinimumDot": {}, "Signs": []}
        for name, field, attr in ((b"LayerElementTangent", b"Tangents", "tangent"),
                                  (b"LayerElementBinormal", b"Binormals", "bitangent"),
                                  (b"LayerElementNormal", b"Normals", "normal")):
            element = child(g, name)
            if element is None:
                raise ValueError("Source FBX basis is missing " + name.decode())
            if child(element, b"MappingInformationType").props[0] != b"ByVertice":
                raise ValueError("Unsupported FBX basis mapping")
            if child(element, b"ReferenceInformationType").props[0] != b"Direct":
                raise ValueError("Unsupported FBX basis indexing")
            values = np.asarray(child(element, field).props[0]).reshape(-1, 3)[indices]
            blender = np.array([getattr(l, attr)[:] for l in loops])
            denom = np.linalg.norm(values, axis=1) * np.linalg.norm(blender, axis=1)
            if np.any(denom < 1e-12):
                raise ValueError("Degenerate source/Blender tangent basis")
            dots = np.sum(values * blender, axis=1) / denom
            sign = 1 if np.median(dots) >= 0 else -1
            minimum = float(np.min(dots * sign))
            if minimum < .99 or (attr == "normal" and sign != 1):
                raise ValueError("Inconsistent source/Blender basis: " + attr)
            result["MinimumDot"][attr] = minimum
            result["Signs"].append(sign)
        cache[cache_key] = result
    except Exception as exc:
        cache[cache_key] = {"Status": "disabled", "Reason": str(exc), "Signs": None}
    return cache[cache_key]


def load_texture(binding, root, colorspace):
    import bpy
    path = _inside(root, binding["Path"])
    if not path.is_file():
        raise FileNotFoundError("Missing texture: " + str(path))
    for im in bpy.data.images:
        if (im.get("unbound_resource_id") == binding["ResourceId"]
                and im.get("unbound_source_path") == str(path)
                and im.colorspace_settings.name == colorspace
                and im.alpha_mode == "CHANNEL_PACKED" and im.size[0] > 0):
            return im
    im = bpy.data.images.load(str(path), check_existing=False)
    im["unbound_resource_id"] = binding["ResourceId"]
    im["unbound_source_path"] = str(path)
    im["unbound_source_colorspace"] = binding["ColorSpace"]
    im.colorspace_settings.name = colorspace
    im.alpha_mode = "CHANNEL_PACKED"
    if im.size[0] == 0:
        raise ValueError("Blender could not decode DDS: " + str(path))
    return im


def static_tire_group():
    import bpy
    identity = PROFILE["Profile"] + "-math"
    existing = next((g for g in bpy.data.node_groups if g.get("unbound_profile_math") == identity), None)
    if existing:
        return existing
    g = bpy.data.node_groups.new("Unbound | Source tire base v1", "ShaderNodeTree")
    g["unbound_profile_math"] = identity
    for name, kind, direction in (
        ("Source Color", "NodeSocketColor", "INPUT"), ("Smoothness", "NodeSocketFloat", "INPUT"),
        ("Normal RG", "NodeSocketColor", "INPUT"), ("AO", "NodeSocketFloat", "INPUT"),
        ("Base Color", "NodeSocketColor", "OUTPUT"), ("Roughness", "NodeSocketFloat", "OUTPUT"),
        ("Normal XYZ", "NodeSocketVector", "OUTPUT")):
        g.interface.new_socket(name=name, in_out=direction, socket_type=kind)
    n, links = g.nodes, g.links
    source = n.new("NodeGroupInput")
    source.location = (-800, 100)
    output = n.new("NodeGroupOutput")
    output.location = (700, 100)
    def math(op, a, b=None, label=""):
        node = n.new("ShaderNodeMath")
        node.operation, node.label = op, label
        for i, value in enumerate((a, b)):
            if value is None:
                continue
            if isinstance(value, (int, float)):
                node.inputs[i].default_value = value
            else:
                links.new(value, node.inputs[i])
        return node
    ao = math("ADD", source.outputs["AO"], .05, "PS: AO + 0.05")
    ao.location = (-500, 400)
    sqrt = math("SQRT", ao.outputs[0], label="PS: sqrt(AO + 0.05)")
    sqrt.location = (-300, 400)
    color = n.new("ShaderNodeVectorMath")
    color.operation, color.label = "SCALE", "Static source base color"
    color.location = (200, 400)
    links.new(source.outputs["Source Color"], color.inputs[0])
    links.new(sqrt.outputs[0], color.inputs["Scale"])
    links.new(color.outputs["Vector"], output.inputs["Base Color"])
    rough = math("SUBTRACT", 1, source.outputs["Smoothness"], "Principled translation: 1 - smoothness")
    rough.use_clamp = True
    rough.location = (200, 200)
    links.new(rough.outputs[0], output.inputs["Roughness"])
    split = n.new("ShaderNodeSeparateColor")
    split.mode, split.location = "RGB", (-600, -100)
    links.new(source.outputs["Normal RG"], split.inputs["Color"])
    components = []
    for i, channel in enumerate(("Red", "Green")):
        mul = math("MULTIPLY", split.outputs[channel], 2)
        mul.location = (-400, -i*150-100)
        sub = math("SUBTRACT", mul.outputs[0], 1, "Source " + "XY"[i])
        sub.location = (-200, -i*150-100)
        components.append(sub.outputs[0])
    product = math("MULTIPLY", *components, label="Source: saturate(X*Y)")
    product.use_clamp = True
    product.location = (0, -400)
    z = math("SUBTRACT", 1, product.outputs[0], "Source Z (not the usual square root)")
    z.location = (200, -400)
    combine = n.new("ShaderNodeCombineXYZ")
    combine.location = (200, -100)
    for socket, value in zip(combine.inputs, components + [z.outputs[0]]):
        links.new(value, socket)
    normalize = n.new("ShaderNodeVectorMath")
    normalize.operation, normalize.location = "NORMALIZE", (400, -100)
    links.new(combine.outputs[0], normalize.inputs[0])
    links.new(normalize.outputs["Vector"], output.inputs["Normal XYZ"])
    return g


def make_material(source, state, layer, images, basis, identity):
    import bpy
    mat = source.copy()
    try:
        mat.name = source.name + " | Tire base"
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        # Preserve all original raw nodes, but place them inside an inspection frame.
        frame = nodes.new("NodeFrame")
        frame.label = "Original source values / inactive inspection nodes"
        for node in list(nodes):
            if node != frame and node.parent is None:
                node.parent = frame
        frame.location = (-1600, -1000)
        uv = nodes.new("ShaderNodeUVMap")
        uv.uv_map, uv.label, uv.location = layer, "Verified source TexCoord0 → " + layer, (-900, 400)
        samples = []
        for i, (parameter, image) in enumerate(zip(CORE_TEXTURES, images)):
            tex = nodes.new("ShaderNodeTexImage")
            tex.image, tex.label, tex.location = image, parameter, (-650, 400-i*320)
            tex.extension = "REPEAT"
            tex["unbound_parameter_name"] = parameter
            links.new(uv.outputs["UV"], tex.inputs["Vector"])
            samples.append(tex)
        cs, no = samples
        math = nodes.new("ShaderNodeGroup")
        math.node_tree, math.location = static_tire_group(), (-300, 400)
        links.new(cs.outputs["Color"], math.inputs["Source Color"])
        links.new(cs.outputs["Alpha"], math.inputs["Smoothness"])
        links.new(no.outputs["Color"], math.inputs["Normal RG"])
        links.new(no.outputs["Alpha"], math.inputs["AO"])
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location, bsdf.label = (350, 400), "Partial tire base / Principled approximation"
        bsdf.inputs["Metallic"].default_value = 0
        bsdf.inputs["IOR"].default_value = 1.5
        links.new(math.outputs["Base Color"], bsdf.inputs["Base Color"])
        links.new(math.outputs["Roughness"], bsdf.inputs["Roughness"])
        if basis["Signs"]:
            scale = nodes.new("ShaderNodeVectorMath")
            scale.operation, scale.location = "MULTIPLY", (-50, -150)
            scale.inputs[1].default_value = tuple(.5*x for x in basis["Signs"])
            links.new(math.outputs["Normal XYZ"], scale.inputs[0])
            bias = nodes.new("ShaderNodeVectorMath")
            bias.operation, bias.location = "ADD", (150, -150)
            bias.inputs[1].default_value = (.5, .5, .5)
            links.new(scale.outputs["Vector"], bias.inputs[0])
            normal = nodes.new("ShaderNodeNormalMap")
            normal.space, normal.uv_map, normal.location = "TANGENT", layer, (350, -150)
            normal.label = "Source basis checked against this mesh's FBX"
            links.new(bias.outputs["Vector"], normal.inputs["Color"])
            links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
        output = nodes.new("ShaderNodeOutputMaterial")
        output.is_active_output, output.location = True, (700, 400)
        links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
        mat["unbound_surface_profile"] = PROFILE["Profile"]
        mat["unbound_surface_key"] = identity
        mat["unbound_status"] = "Partial tire base: original textures; Principled approximation"
        mat["unbound_surface_evidence_json"] = canonical({
            "Profile": PROFILE["Profile"], "ShaderDatabaseSHA256": PROFILE["DatabaseSHA256"],
            "UVLayer": layer, "Basis": basis, "Unsupported": PROFILE["Unsupported"],
            "RendererChoices": PROFILE["RendererChoices"]})
        return mat
    except Exception:
        bpy.data.materials.remove(mat)
        raise


def apply_supported_surfaces(objects=None, export_path=None, progress=None):
    """Build every supported slot now; progress(done, total) is called per object."""
    steps = surface_steps(objects, export_path)
    while True:
        try:
            done, total = next(steps)
        except StopIteration as stop:
            return stop.value
        if progress:
            progress(done, total)


def surface_steps(objects=None, export_path=None):
    """Generator form of apply_supported_surfaces: yields (done, total) per object, returns the report."""
    import bpy
    objects = list(objects if objects is not None else bpy.context.scene.objects)
    report = {"Version": VERSION, "Profile": PROFILE["Profile"], "Built": [], "AlreadyBuilt": [],
              "Unsupported": [], "Issues": [], "Scope": PROFILE["Scope"],
              "CompiledProfiles": "Static-state source G-buffer formulas translated to Principled; "
                                  "see each built material's unbound_surface_evidence_json."}
    documents, basis_cache, material_cache, caches = {}, {}, {}, {}
    for done, obj in enumerate(objects):
        yield done, len(objects)
        if obj.type != "MESH" or not obj.get("unbound_mesh_id"):
            continue
        # Only occupied slots; unused slots may refer to a different section's UVs.
        slots = sorted({p.material_index for p in obj.data.polygons})
        for k, index in enumerate(slots):
            if k:
                yield done + k / len(slots), len(objects)  # many-slot parts: let the UI redraw between slots
            if index >= len(obj.material_slots):
                report["Issues"].append({"Object": obj.name, "Issue": "Face material index out of range"})
                continue
            slot, material = obj.material_slots[index], obj.material_slots[index].material
            if not material or not material.get("unbound_source_json"):
                report["Unsupported"].append({"Object": obj.name, "Slot": index, "Reason": "No restored source identity"})
                continue
            if material.get("unbound_surface_profile"):
                report["AlreadyBuilt"].append({"Object": obj.name, "Slot": index})
                continue  # Preserve user node edits, including edits to a generated graph.
            try:
                state = json.loads(material["unbound_source_json"])
                if not supported(state):
                    profile_slot(obj, index, slot, material, state, export_path, documents, basis_cache,
                                 material_cache, caches, report)
                    continue
                if material.node_tree and any(n.type == "OUTPUT_MATERIAL" and n.inputs["Surface"].is_linked
                                              for n in material.node_tree.nodes):
                    raise ValueError("Existing connected surface preserved")
                cs, no = validate_parameters(state)
                layer = source_uv(obj)
                root, mesh = locate_export(obj, state, export_path, documents)
                images = (load_texture(cs, root, "sRGB"), load_texture(no, root, "Non-Color"))
                basis = tangent_basis(obj, mesh, root, layer, basis_cache)
                identity = hashlib.sha256(canonical({
                    "State": state, "Layer": layer, "Signs": basis["Signs"], "Root": str(root),
                    "Profile": PROFILE["Profile"]}).encode()).hexdigest()
                if identity not in material_cache:
                    material_cache[identity] = make_material(material, state, layer, images, basis, identity)
                slot.link = "OBJECT"
                slot.material = material_cache[identity]
                obj["unbound_materials_path"] = str(root / "materials.json")
                obj["unbound_surface_uv_json"] = canonical([
                    {"Parameter": p, "SourceUsage": PROFILE["UV"][p]["SourceUsage"], "BlenderLayer": layer,
                     "Evidence": PROFILE["Profile"]} for p in CORE_TEXTURES])
                report["Built"].append({"Object": obj.name, "Slot": index, "MeshId": obj["unbound_mesh_id"],
                    "Material": slot.material.name, "UV": layer, "Basis": basis, "ExportRoot": str(root)})
                if basis["Status"] == "disabled":
                    report["Issues"].append({"Object": obj.name, "Issue": "Normal map disabled: " + basis["Reason"]})
            except Exception as exc:
                report["Issues"].append({"Object": obj.name, "Slot": index, "Issue": str(exc)})
    report["Limits"] = PROFILE["Unsupported"]
    report["Summary"] = summarize(report)
    text = bpy.data.texts.new("An's Garage surface report")
    text.write(json.dumps(report, indent=2))
    bpy.context.scene["unbound_surface_report"] = text.name
    return report


def profiles_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("unbound_profiles", Path(__file__).with_name("unbound_profiles.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def profile_slot(obj, index, slot, material, state, export_path, documents, basis_cache, material_cache, caches, report):
    """Build one occupied slot from a compiled source-shader profile, or report exactly why not."""
    if "module" not in caches:
        caches["module"] = profiles_module()
    P = caches["module"]
    shader = (state.get("Shader") or {}).get("Asset")
    profile = P.profile_for(state)
    if profile is None:
        status = P.report_for(shader)
        report["Unsupported"].append({"Object": obj.name, "Slot": index, "Shader": state.get("Shader"),
                                      "Reason": status.get("Reason") or status.get("Status") or "No compiled profile"})
        return
    if material.node_tree and any(n.type == "OUTPUT_MATERIAL" and n.inputs["Surface"].is_linked
                                  for n in material.node_tree.nodes):
        raise ValueError("Existing connected surface preserved")
    root, mesh = locate_export(obj, state, export_path, documents)
    section = next(s for s in mesh["Sections"] if str(s["SectionIndex"]) == str(obj.get("unbound_section_index")))
    layout = P.section_layout(section)
    formats = P.section_formats(section)
    candidates = P.entries_for(profile, layout, formats)
    if not candidates:
        report["Unsupported"].append({"Object": obj.name, "Slot": index, "Shader": state.get("Shader"),
                                      "Reason": "No compiled program for vertex layout " + "/".join(layout)})
        return
    renames = []
    for entry in candidates:
        entry["ShaderAsset"] = shader
        try:
            renames.append(P.element_inputs(entry, layout))
        except P.Unsupported as exc:
            report["Unsupported"].append({"Object": obj.name, "Slot": index, "Shader": state.get("Shader"), "Reason": str(exc)})
            return
    unresolved = sorted({u for e in candidates for u in e["Unresolved"]})
    if unresolved:
        report["Unsupported"].append({"Object": obj.name, "Slot": index, "Shader": state.get("Shader"),
                                      "Reason": "Unresolved runtime inputs: " + ", ".join(unresolved)})
        return
    if ("images", str(root)) not in caches:
        import bpy
        caches[("images", str(root))] = P.Images(root, [bpy.context.scene.get("unbound_shader_defaults_path", "")])
        caches[("runtime", str(root))] = P.runtime_values(root / "assembly.json")
    images = caches[("images", str(root))]
    runtime, runtime_notes, assembly_doc = caches[("runtime", str(root))]
    plans = []
    for entry, rename in zip(candidates, renames):
        try:
            consts = P.input_constants(entry, obj, assembly_doc)
        except P.Unsupported as exc:
            report["Unsupported"].append({"Object": obj.name, "Slot": index, "Shader": state.get("Shader"), "Reason": str(exc)})
            return
        live_names = {e["Name"] for e in entry["Externals"]
                      if runtime.get(e["Key"].casefold(), {}).get("Field") == "PaintFacingColorParameter"}
        pkey = (shader, material.get("unbound_state_key"), str(root), id(entry), tuple(sorted(consts.items())),
                tuple(sorted(rename.items())))
        if pkey not in caches:
            caches[pkey] = P.plan(entry, state, runtime, live_names, images, root, consts, rename)
        if caches[pkey]["issues"]:
            raise ValueError("; ".join(caches[pkey]["issues"]))
        if caches[pkey]["unsupported"]:
            report["Unsupported"].append({"Object": obj.name, "Slot": index, "Shader": state.get("Shader"),
                                          "Reason": caches[pkey]["unsupported"]})
            return
        plans.append(caches[pkey])
    akey = ("choice", shader, material.get("unbound_state_key"), "/".join(layout), tuple(sorted(plans[0]["input_consts"].items())))
    if akey not in caches:
        try:
            caches[akey] = P.choose_entry(candidates, plans) if len(plans) > 1 else []
        except P.Unsupported as exc:
            caches[akey] = exc
    if isinstance(caches[akey], P.Unsupported):
        report["Unsupported"].append({"Object": obj.name, "Slot": index, "Shader": state.get("Shader"), "Reason": str(caches[akey])})
        return
    permutation_notes = caches[akey]
    entry, p = candidates[0], plans[0]
    uv = {b["SourceUsage"]: b["BlenderLayer"] for b in json.loads(obj.get("unbound_uv_bindings_json", "[]"))
          if b.get("BlenderLayer") in obj.data.uv_layers}
    colors = {}
    for usage, name in P.color_bindings(section).items():
        attr = obj.data.color_attributes.get(name)
        if attr is not None:
            colors[usage] = {"name": name, "byte": attr.data_type == "BYTE_COLOR"}
    fb_to_blender, blender_to_fb = P.axis_matrices(obj)
    ctx = {"uv": uv, "colors": colors, "tangent_uv": uv.get("TexCoord0", ""), "fb_to_blender": fb_to_blender,
           "blender_to_fb": blender_to_fb, "notes": []}
    basis = None
    if p["uses_frame"]:
        if ctx["tangent_uv"]:
            basis = tangent_basis(obj, mesh, root, ctx["tangent_uv"], basis_cache)
        else:
            basis = {"Status": "disabled", "Reason": "No TexCoord0 layer", "Signs": None}
        ctx["basis_signs"], ctx["basis_reason"] = basis.get("Signs"), basis.get("Reason", "")
    identity = hashlib.sha256(canonical({
        "Programs": entry["Programs"], "Nodes": p["spec"].nodes, "Outputs": p["outs"],
        "Images": {str(k): [i.get("unbound_source_path") for i in (v if isinstance(v, list) else [v])]
                   for k, v in p["images"].items()},
        "UV": uv, "Colors": colors, "Signs": ctx.get("basis_signs"), "Axes": fb_to_blender,
        "Live": sorted(map(list, p["live"]))}).encode()).hexdigest()
    label = "Unbound | %s | %s" % (shader.rsplit("/", 1)[-1], identity[:8])
    group, connected = P.build_group(entry, p, ctx, identity, label)
    unsupported = [{"Output": k, "Reason": v} for k, v in P.UNSUPPORTED_OUTPUTS.items() if k in entry["Outputs"]]
    for k, why in entry.get("OmittedOutputs", {}).items():
        unsupported.append({"Output": k, "Reason": P.OMITTED_REASON, "Needs": why})
    if entry.get("Kind") == "forward_transmittance":
        unsupported.append({"Output": "RT0", "Reason": "Forward lit colour (reflections, dirt scattering, emissive) depends on "
                                                        "the game's lighting loops; only the pre-lighting transmittance and Fresnel weight are used"})
    if entry.get("Targets") == 4 and "RT2.x" in entry["Outputs"]:
        rt2x = p["spec"].output("RT2.x")
        if isinstance(rt2x, tuple) or float(rt2x) != 0.0:
            unsupported.append({"Output": "RT2.x", "Reason": "Non-zero fourth-target channel with unknown deferred meaning"})
    entry_report = {"Identity": identity, "Shader": shader, "PixelPrograms": entry["Programs"], "VertexLayout": layout,
                    "ShaderDatabaseSHA256": P.profiles()["DatabaseSHA256"], "Connected": connected,
                    "RuntimeInputs": p["applied"], "RuntimeNotes": runtime_notes,
                    "PerInstanceInputs": {k: {"Value": v, "Evidence": "wheel facing from assembly; pixel program lerps "
                                                                      "rear->front parameters by this value"}
                                          for k, v in p["input_consts"].items()},
                    "FoldedTextures": entry["FoldedSlots"] + p.get("folded_textures", []), "Inputs": p["inputs"],
                    "VertexElements": renames[0],
                    "Basis": basis, "Notes": ctx["notes"], "Unsupported": unsupported,
                    "RendererChoices": ["Roughness = 1 - smoothness (Frostbite perceptual roughness convention)",
                                        "Dielectric IOR 1.5 (F0 0.04)", "Static state: time 0, dry, clean, undamaged",
                                        "No specular anti-aliasing (screen-space derivatives) and no mip bias",
                                        "Texture sampling: Blender linear filtering, repeat wrap"]}
    if entry.get("Kind") == "forward_transmittance":
        entry_report["RendererChoices"] = ["Dual-source target 1 interpreted as per-channel transmittance (blend state not decoded)",
                                           "Reflection lobe: Glossy, roughness 0 (not recovered); weight = program's Fresnel term",
                                           "Static state: time 0, dry, clean"]
    if entry.get("StaticOverrides"):
        entry_report["StaticStateOverrides"] = {k: {"Value": v, "Reason": "runtime damage state fixed to undamaged; "
                                                                        "the program gates the damage texture with it"}
                                                for k, v in entry["StaticOverrides"].items()}
    if "Coat Weight" in connected:
        entry_report["RendererChoices"].append("RT2.x -> Coat Weight and fifth-target smoothness/normal -> coat: "
                                               "interpretation of the G-buffer layout, not verified against deferred lighting")
    if permutation_notes:
        entry_report["PermutationNotes"] = permutation_notes
    if p.get("engine"):
        entry_report["EngineConstantAssumption"] = p["engine"]
    key = (material.name, identity)
    if key not in material_cache:
        material_cache[key] = P.make_profile_material(material, entry, group, connected, entry_report)
    slot.link = "OBJECT"
    slot.material = material_cache[key]
    obj["unbound_materials_path"] = str(root / "materials.json")
    report["Built"].append({"Object": obj.name, "Slot": index, "MeshId": obj["unbound_mesh_id"],
                            "Material": slot.material.name, "Shader": shader, "Group": group.name,
                            "Connected": connected, "Notes": ctx["notes"], "PermutationNotes": permutation_notes})


def summarize(report):
    from collections import Counter
    built = Counter((b.get("Shader") or PROFILE["ShaderAsset"]).rsplit("/", 1)[-1] for b in report["Built"])
    unsupported = Counter(((u.get("Shader") or {}).get("Asset") or "none").rsplit("/", 1)[-1] for u in report["Unsupported"])
    issues = Counter(i.get("Issue", "")[:120] for i in report["Issues"])
    return {"BuiltSlots": sum(built.values()), "BuiltByShader": dict(built),
            "UnsupportedSlots": sum(unsupported.values()), "UnsupportedByShader": dict(unsupported),
            "IssueSlots": len(report["Issues"]), "IssueReasons": dict(issues)}
