"""Builds each source material slot from its compiled source-shader profile (unbound_profiles.py).

This module never edits geometry or guesses a UV layer from its ordinal/name. Shaders without a resolved profile stay
unconnected and are reported.
"""
import functools
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)



@functools.lru_cache(maxsize=8192)
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
    from .unbound_materials import parsed_fbx
    cache_key = (obj.data.as_pointer(), layer, str(root), obj.get("unbound_fbx_geometry_id"))
    if cache_key in cache:
        return cache[cache_key]
    try:
        tree = parsed_fbx(_inside(root, mesh_record["Fbx"]))
        def child(node, name):
            return next((x for x in node.elems if x.id == name), None)
        objects = child(tree, b"Objects")
        geometries = [g for g in objects.elems if g.id == b"Geometry"
                      and str(g.props[0]) == str(obj.get("unbound_fbx_geometry_id"))]
        if len(geometries) != 1:
            raise ValueError("FBX section identity missing")
        g = geometries[0]
        source_positions = np.asarray(child(g, b"Vertices").props[0]).reshape(-1, 3)
        positions = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
        obj.data.vertices.foreach_get("co", positions)
        positions = positions.reshape(-1, 3)
        if source_positions.shape != positions.shape or not np.allclose(source_positions, positions, atol=1e-6, rtol=0):
            raise ValueError("Mesh positions differ from source FBX")
        obj.data.calc_tangents(uvmap=layer)
        loops = obj.data.loops
        indices = np.empty(len(loops), dtype=np.int64)
        loops.foreach_get("vertex_index", indices)
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
            blender = np.empty(len(loops) * 3, dtype=np.float32)
            loops.foreach_get(attr, blender)
            blender = blender.reshape(-1, 3)
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



LAST_REPORT = {"report": None}


def last_report():
    """The surface report of the last import or full build (rebuilds of a few slots don't replace it); the readable
    version is in the car's An's Garage report."""
    return LAST_REPORT["report"]


def apply_supported_surfaces(objects=None, export_path=None):
    """Build every supported slot now."""
    steps = surface_steps(objects, export_path)
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def surface_steps(objects=None, export_path=None):
    """Generator form of apply_supported_surfaces: yields (done, total) per object, returns the report."""
    import bpy
    objects = list(objects if objects is not None else bpy.context.scene.objects)
    from . import bl_info
    report = {"Version": ".".join(map(str, bl_info["version"])), "Built": [], "AlreadyBuilt": [],
              "Unsupported": [], "Issues": [],
              "CompiledProfiles": "Static-state source G-buffer formulas translated to Principled; "
                                  "see each built material's unbound_surface_evidence_json."}
    documents, basis_cache, material_cache, caches = {}, {}, {}, {}
    caches["conditions"] = bool(bpy.context.scene.get("ans_garage_conditions"))
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
                # Parsed once per material per build; each slot gets its own top level (overrides are set on it).
                skey = ("state", material.name)
                if skey not in caches:
                    caches[skey] = json.loads(material["unbound_source_json"])
                state = dict(caches[skey])
                if obj.get("unbound_texture_overrides_json"):
                    # Per-object shader texture overrides (tire library lettering): parameter -> texture asset.
                    state["TextureOverrides"] = json.loads(obj["unbound_texture_overrides_json"])
                if obj.get("unbound_parameter_overrides_json"):
                    # Per-object values the player sets in the game (license plate text): parameter -> values.
                    state["ParameterOverrides"] = json.loads(obj["unbound_parameter_overrides_json"])
                profile_slot(obj, index, slot, material, state, export_path, documents, basis_cache,
                             material_cache, caches, report)
            except Exception as exc:
                report["Issues"].append({"Object": obj.name, "Slot": index, "Issue": str(exc)})
    report["Summary"] = summarize(report)
    from .unbound_materials import FBX_TREES
    FBX_TREES.clear()
    LAST_REPORT["report"] = report
    return report


def profiles_module():
    from . import unbound_profiles
    return unbound_profiles


def set_texture_overrides(obj, overrides):
    """Merge parameter -> texture asset overrides into an object (None removes one), so plates and liveries on the
    same part keep each other's."""
    current = json.loads(obj.get("unbound_texture_overrides_json", "{}"))
    for k, v in overrides.items():
        if v is None:
            current.pop(k, None)
        else:
            current[k] = v
    if current:
        obj["unbound_texture_overrides_json"] = json.dumps(current, sort_keys=True)
    elif "unbound_texture_overrides_json" in obj:
        del obj["unbound_texture_overrides_json"]


def rebuild(slots):
    """Rebuild (object, slot index) pairs from their source materials with the current overrides and settings; returns
    (built, failed) report rows of those slots. The car's full surface report stays the current one."""
    steps = rebuild_steps(slots)
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def rebuild_steps(slots):
    """Generator form of rebuild: yields (done, total) objects, returns (built, failed)."""
    import bpy
    objects = []
    for o, i in slots:
        o.material_slots[i].link = "DATA"  # the source material; rebuilt below
        if o not in objects:
            objects.append(o)
    previous = LAST_REPORT["report"]
    report = yield from surface_steps(objects)
    if previous is not None:
        LAST_REPORT["report"] = previous
    wanted = {(o.name, i) for o, i in slots}
    built = [b for b in report["Built"] if (b["Object"], b["Slot"]) in wanted]
    failed = [u for u in report["Unsupported"] + report["Issues"] if (u.get("Object"), u.get("Slot")) in wanted]
    return built, failed


_READS_CONDITIONS = {}


def reads_conditions(source):
    """True when the source material's shader reads dirt, dust or wet (cached per source material)."""
    key = source.get("unbound_source_json", "")
    if key not in _READS_CONDITIONS:
        P = profiles_module()
        profile = P.profile_for(json.loads(key or "{}"))
        _READS_CONDITIONS[key] = bool(profile and any(e["Name"] in P.CONDITIONS for x in profile["Entries"] for e in x["Externals"]))
    return _READS_CONDITIONS[key]


def stale_condition_slots(objects=None, visible_only=True):
    """(object, slot) of built slots whose shader reads dirt/dust/wet but were built with the other setting. Hidden
    parts (other part options) are left until they are shown (catch_up)."""
    import bpy
    want = bool(bpy.context.scene.get("ans_garage_conditions"))
    slots = []
    for o in (objects if objects is not None else bpy.context.scene.objects):
        if o.type != "MESH" or not o.get("unbound_mesh_id") or (visible_only and not o.visible_get()):
            continue
        for i, s in enumerate(o.material_slots):
            source = o.data.materials[i] if i < len(o.data.materials) else None
            if s.link != "OBJECT" or not (s.material and s.material.get("unbound_surface_profile")) or not source:
                continue
            if bool(s.material.get("unbound_conditions_state")) != want and reads_conditions(source):
                slots.append((o, i))
    return slots


def set_conditions_steps(enabled):
    """Turn the scene's Dirt, Dust and Wet controls on or off: rebuild the visible slots whose shader reads them
    (yields progress, returns (slots, built, failed)). Hidden part options catch up when they are shown."""
    import bpy
    bpy.context.scene["ans_garage_conditions"] = bool(enabled)
    slots = stale_condition_slots()
    built, failed = yield from rebuild_steps(slots)
    return len(slots), built, failed


def set_conditions(enabled):
    """set_conditions_steps in one go (scripts, background runs)."""
    steps = set_conditions_steps(enabled)
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def catch_up(objects=None):
    """Rebuild the visible parts among `objects` that were hidden when dirt/dust/wet were last switched: returns the
    number of slots rebuilt."""
    slots = stale_condition_slots(objects)
    if slots:
        rebuild(slots)
    return len(slots)


def profile_slot(obj, index, slot, material, state, export_path, documents, basis_cache, material_cache, caches, report):
    """Build one occupied slot from a compiled source-shader profile, or report exactly why not."""
    if "module" not in caches:
        caches["module"] = profiles_module()
    P = caches["module"]
    shader = (state.get("Shader") or {}).get("Asset")
    if (shader or "").lower().endswith("licenseplate_max") and "ParameterOverrides" not in state:
        # The plate text is a player setting in the game, not vehicle data: blank until one is typed in the sidebar
        # (the shader's own default, 0 in every cell, would read "0000000").
        state["ParameterOverrides"] = P.plate_text_values("")
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
    # Permutations that only a player customization selects (the LED license plate) give way to the stock one.
    stock = [e for e in candidates if P.stock_permutation(e)]
    customization_notes = []
    if stock and len(stock) < len(candidates):
        labels = P.stock_permutation(stock[0])
        customization_notes = [{"AlternateProgram": e["Programs"][0], "Status": "%s permutation: a player customization; "
                                "the stock %s is built" % (labels[1], labels[0])}
                               for e in candidates if e not in stock]
        candidates = stock
    # Forward (glass) pairs: the game draws the full program, state bit 9 clear (frame capture of its light lenses);
    # the reduced one is for other views.
    full = [e for e in candidates if P.full_forward_program(e)]
    if full and len(full) < len(candidates):
        customization_notes += [{"AlternateProgram": e["Programs"][0], "Status": "reduced program (state bit 9 set); the "
                                 "game draws the full one in its main view (frame capture)"}
                                for e in candidates if e not in full]
        candidates = full
    renames = []
    for entry in candidates:
        entry["ShaderAsset"] = shader
        try:
            renames.append(P.element_inputs(entry, layout))
        except P.Unsupported as exc:
            report["Unsupported"].append({"Object": obj.name, "Slot": index, "Shader": state.get("Shader"), "Reason": str(exc)})
            return
    # View constants present in the formula are tested by the planner (after specialization); anything else unresolved
    # stops here.
    unresolved = sorted({u for e in candidates for u in e["Unresolved"] if u not in P.testable_unresolved(e)})
    if unresolved:
        report["Unsupported"].append({"Object": obj.name, "Slot": index, "Shader": state.get("Shader"),
                                      "Reason": "Unresolved runtime inputs: " + ", ".join(unresolved)})
        return
    # A library part placed on a car (rims) takes the car's runtime values, wheel facing, controls and shared shader
    # default textures (library exports have none of their own).
    car = Path(obj["unbound_car_assembly"]) if obj.get("unbound_car_assembly") else root / "assembly.json"
    scope = car.parent.name
    # One resolver per export, car and extra texture folder (plate and tire libraries are per object).
    ikey = ("images", str(root), str(car), obj.get("unbound_override_textures", ""))
    if ikey not in caches:
        import bpy
        import importlib
        shader_textures = importlib.import_module(__package__).library_folder(bpy.context, "shader")
        caches[ikey] = P.Images(root, [shader_textures, obj.get("unbound_override_textures", "")])
    if ("runtime", str(car)) not in caches:
        caches[("runtime", str(car))] = P.runtime_values(car)
    images = caches[ikey]
    runtime, runtime_notes, assembly_doc = caches[("runtime", str(car))]

    def planned(conditions):
        """(plans, permutation notes) for the candidates, or the reason they can't be built."""
        plans = []
        for entry, rename in zip(candidates, renames):
            consts = P.input_constants(entry, obj, assembly_doc)
            live_fields = P.live_fields(entry, runtime)
            pkey = (shader, material.get("unbound_state_key"), str(root), str(car), id(entry), tuple(sorted(consts.items())),
                    tuple(sorted(rename.items())), json.dumps(state.get("TextureOverrides"), sort_keys=True),
                    json.dumps(state.get("ParameterOverrides"), sort_keys=True), conditions)
            if pkey not in caches:
                caches[pkey] = P.plan(entry, state, runtime, live_fields, images, root, consts, rename, conditions)
            if caches[pkey]["issues"]:
                raise ValueError("; ".join(caches[pkey]["issues"]))
            if caches[pkey]["unsupported"]:
                return caches[pkey]["unsupported"]
            plans.append(caches[pkey])
        akey = ("choice",) + tuple(id(p["spec"]) for p in plans)  # depends only on the specialized formulas
        if akey not in caches:
            try:
                caches[akey] = P.choose_entry(candidates, plans) if len(plans) > 1 else []
            except P.Unsupported as exc:
                caches[akey] = exc
        return str(caches[akey]) if isinstance(caches[akey], P.Unsupported) else (plans, caches[akey])

    def attempt():
        result, issue = planned(caches["conditions"]), None
        if isinstance(result, str) and caches["conditions"]:
            # Built clean and dry rather than not at all; the reason goes in the surface evidence.
            result, issue = planned(False), result
        return result, issue

    override_issue = None
    try:
        result, condition_issue = attempt()
        optional = [k for k in state.get("TextureOverrides") or {} if k in P.OPTIONAL_OVERRIDES]
        if isinstance(result, str) and optional:
            state["TextureOverrides"] = {k: v for k, v in state["TextureOverrides"].items() if k not in optional}
            override_issue = {"Overrides": optional, "Reason": result}
            result, condition_issue = attempt()
    except P.Unsupported as exc:
        result = str(exc)
    if isinstance(result, str):
        report["Unsupported"].append({"Object": obj.name, "Slot": index, "Shader": state.get("Shader"), "Reason": result})
        return
    plans, choice = result
    permutation_notes = customization_notes + choice
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
           "live_scope": scope,
           "blender_to_fb": blender_to_fb, "notes": []}
    basis = None
    if p["uses_frame"]:
        if ctx["tangent_uv"]:
            basis = tangent_basis(obj, mesh, root, ctx["tangent_uv"], basis_cache)
        else:
            basis = {"Status": "disabled", "Reason": "No TexCoord0 layer", "Signs": None}
        ctx["basis_signs"], ctx["basis_reason"] = basis.get("Signs"), basis.get("Reason", "")
    fkey = ("formula", id(p["spec"]))
    if fkey not in caches:  # the formula part, hashed once per specialized formula
        caches[fkey] = hashlib.sha256(canonical({"Programs": entry["Programs"], "Nodes": p["spec"].nodes,
                                                 "Outputs": p["outs"]}).encode()).hexdigest()
    identity = hashlib.sha256(canonical({
        "Formula": caches[fkey],
        "Images": {str(k): [i.get("unbound_source_path") for i in (v if isinstance(v, list) else [v])]
                   for k, v in p["images"].items()},
        "UV": uv, "Colors": colors, "Signs": ctx.get("basis_signs"), "Axes": fb_to_blender,
        "Live": sorted(map(list, p["live"])),
        # Runtime controls are per car: a group with live paint belongs to its car.
        "Scope": scope if any(n not in P.CONDITIONS for n, _ in p["live"]) else None}).encode()).hexdigest()
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
    if p.get("view"):
        entry_report["ViewConstantIndependence"] = p["view"]
    if override_issue:
        entry_report["LiveryNotApplied"] = dict(override_issue, Status="this part keeps its stock look")
    if condition_issue:
        entry_report["VehicleCondition"] = {"Status": "not applied: built clean and dry", "Reason": condition_issue}
    if p.get("conditions"):
        entry_report["RendererChoices"] = [c for c in entry_report["RendererChoices"] if not c.startswith("Static state")]
        entry_report["RendererChoices"].append("Static state: time 0, undamaged")
        entry_report["VehicleCondition"] = {
            "Parameters": p["conditions"],
            "Reason": "set by the game while driving; driven by the sidebar's Dirt, Dust and Wet sliders (0 = clean and dry)",
            "Colours": "dirt/dust colour where the shader reads one: the car paint shader's own (dirt 0.0331, dust 0.139)",
            "Wet": "rain cycle phase 0.6 + 0.1 x Wet (the rising edge of the shaders' wet ramp); 0 when dry"}
    key = (material.name, identity)
    if key not in material_cache:
        material_cache[key] = P.make_profile_material(material, entry, group, connected, entry_report)
        material_cache[key]["unbound_conditions_state"] = bool(caches["conditions"])
    slot.link = "OBJECT"
    slot.material = material_cache[key]
    obj["unbound_materials_path"] = str(root / "materials.json")
    report["Built"].append({"Object": obj.name, "Slot": index, "MeshId": obj["unbound_mesh_id"],
                            "Material": slot.material.name, "Shader": shader, "Group": group.name,
                            "Connected": connected, "Notes": ctx["notes"], "PermutationNotes": permutation_notes})


def summarize(report):
    from collections import Counter
    built = Counter((b.get("Shader") or "?").rsplit("/", 1)[-1] for b in report["Built"])
    unsupported = Counter(((u.get("Shader") or {}).get("Asset") or "none").rsplit("/", 1)[-1] for u in report["Unsupported"])
    issues = Counter(i.get("Issue", "")[:120] for i in report["Issues"])
    return {"BuiltSlots": sum(built.values()), "BuiltByShader": dict(built),
            "UnsupportedSlots": sum(unsupported.values()), "UnsupportedByShader": dict(unsupported),
            "IssueSlots": len(report["Issues"]), "IssueReasons": dict(issues)}
