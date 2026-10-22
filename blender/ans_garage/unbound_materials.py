"""Source-identity material reconstruction. Unknown shader inputs stay disconnected.

No vehicle IDs, coordinates, material-name substring guesses or default UV choices.
Pure Python resolution functions are also usable by inspection/test scripts.
"""
import functools
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

VERSION = "0.4.0"
PARAMETERS = ("BoolParameters", "VectorParameters", "TextureParameters",
              "ConditionalParameters", "VectorArrayParameters")
FAMILIES = ("Car Paint", "Glass", "Rubber", "Metal", "Plastic", "Carbon Fiber", "Lights")
# Shader identity is evidence of family only; it does not specify BSDF constants.
SHADER_FAMILIES = {
    "cs_pbr_carpaint_max": "Car Paint",
    "cs_pbr_glass_max": "Glass", "cs_pbr_glass_low": "Glass",
    "cs_pbr_lightglassnormal_max": "Glass", "cs_pbr_lightglassnormal_low": "Glass",
    "cs_pbr_lightglass_max": "Glass", "cs_pbr_lightglass_low": "Glass",
    "cs_pbr_tire_max_lookdev": "Rubber",
    "cs_pbr_light_max": "Lights", "cs_pbr_lightbucket_max": "Lights",
}
# These names explicitly describe channel contents. They do NOT establish sampling
# coordinates, color transfer function, normal handedness, or shader combination.
EXPLICIT_CHANNELS = {
    "rgb_color_a_smoothness": {"RGB": "Color", "A": "Smoothness"},
    "rg_normal_a_ao": {"RG": "Normal components", "B": None, "A": "Ambient occlusion"},
    "rg_normalblur_a_aoblur": {"RG": "Blurred normal components", "B": None, "A": "Blurred ambient occlusion"},
}


def plain(value):
    if isinstance(value, dict) and value.get("Type") in ("CString", "FileRef"):
        return value.get("Value", "")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def key(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def uv_bindings(section):
    """Mirror Frosty FBXExporter: stream order, then declaration order, not suffix.

    RadiosityTexCoord consumes an ordinal too. DisplacementMapTexCoord is ignored
    by the native exporter. New manifests supply the exact exporter traversal.
    """
    if "FbxUvBindings" in section:
        return section["FbxUvBindings"]
    attrs = section.get("VertexAttributes", section.get("UvAttributes", []))
    seen = set()
    result = []
    handled = {"Unknown", "Pos", "BinormalSign", "Normal", "Binormal", "Tangent",
               "TangentSpace", "Color0", "Color1", "DisplacementMapTexCoord"}
    for attr in sorted(attrs, key=lambda a: a.get("StreamIndex", 0)):
        usage = attr["Usage"]
        regular = bool(re.fullmatch(r"TexCoord[0-7]", usage))
        extra = usage not in handled and attr.get("Format") in ("Half2", "Float2", "Short2N")
        if usage in seen or not (regular or usage == "RadiosityTexCoord" or extra):
            continue
        ordinal = len(result)
        result.append({"SourceUsage": usage, "BlenderLayer": "UVChannel" + str(ordinal) if regular else usage,
                       "Evidence": "Frosty FBXExporter stream/declaration order; legacy manifest reconstruction"})
        seen.add(usage)
    return result


class Resolver:
    def __init__(self, document):
        if document.get("Schema") != 1:
            raise ValueError("Unsupported materials manifest schema")
        self.document = document
        self.nodes = {n["Id"]: n for n in document["Nodes"]}
        self.textures = {t["ResourceId"]: t for t in document["Textures"]}
        self.meshes = {m["MeshId"]: m for m in document["Meshes"]}

    def node(self, ref):
        identity = (ref or {}).get("Node")
        if identity not in self.nodes:
            raise ValueError("Missing source node: " + str(identity))
        return self.nodes[identity]

    def shader(self, instance, state=None, stack=()):
        state = state or {"Shader": None, "Parameters": {p: {} for p in PARAMETERS}, "Layers": []}
        ref = instance.get("Shader", {})
        if ref.get("Kind") != "Null" and ref.get("Node"):
            n = self.node(ref)
            if n["Id"] in stack:
                raise ValueError("Cyclic shader preset: " + n["Id"])
            if n["Type"] == "SurfaceShaderPreset":
                self.shader(n["Raw"]["ShaderPreset"], state, stack + (n["Id"],))
            else:
                state["Shader"] = {"Node": n["Id"], "Asset": n["Asset"], "Type": n["Type"]}
            state["Layers"].append(n["Id"])
        for kind in PARAMETERS:
            for parameter in instance.get(kind, []):
                name = plain(parameter.get("ParameterName"))
                pkey = name.casefold() if isinstance(name, str) else canonical(parameter.get("ConditionalAsset"))
                state["Parameters"][kind][pkey] = parameter
        return state

    def resolve(self, mesh, slot, variant=None):
        base = self.node(slot["Source"])
        state = self.shader(base["Raw"]["Shader"])
        state["BaseNode"] = base["Id"]
        if variant:
            matches = [a for a in variant["Assignments"] if slot["Index"] in a["Slots"]]
            if len(matches) > 1:
                raise ValueError("Conflicting DB assignments to slot " + str(slot["Index"]))
            if matches:
                assignment = matches[0]
                if assignment.get("Material", {}).get("Node") != base["Id"]:
                    raise ValueError("Variant base-material identity mismatch")
                override = self.node(assignment["Override"])
                shader = override["Raw"]["Shader"]
                # Matches Frosty's MeshMaterialCollection shader replacement policy.
                if shader.get("Shader", {}).get("Kind") not in (None, "Null"):
                    state["Parameters"] = {p: {} for p in PARAMETERS}
                self.shader(shader, state)
                state["OverrideNode"] = override["Id"]
            # Some Frostbite profiles store DB texture parameters separately.
            for row in variant.get("Raw", {}).get("Materials", []):
                if row.get("Material", {}).get("Node") == base["Id"]:
                    for p in row.get("TextureParameters", []):
                        state["Parameters"]["TextureParameters"][plain(p["ParameterName"]).casefold()] = p
        shader_asset = (state["Shader"] or {}).get("Asset", "")
        state["Family"] = SHADER_FAMILIES.get(shader_asset.rsplit("/", 1)[-1].casefold())
        state["FamilyEvidence"] = "Exact shader identity" if state["Family"] else "Unresolved; no classification from mesh display names"
        state["TextureBindings"] = []
        for pname, parameter in state["Parameters"]["TextureParameters"].items():
            ref = parameter.get("Value", {})
            node = self.nodes.get(ref.get("Node"), {})
            texture = self.textures.get(node.get("TextureResource"), {})
            state["TextureBindings"].append({
                "Parameter": plain(parameter["ParameterName"]), "TextureNode": ref.get("Node"),
                "ResourceId": node.get("TextureResource"), "Asset": node.get("Asset"),
                "Path": texture.get("Path"), "Format": texture.get("Format"),
                "ColorSpace": texture.get("ColorSpace", "unspecified"),
                "Channels": EXPLICIT_CHANNELS.get(pname),
                "ChannelEvidence": "Explicit source TextureShaderParameter name" if pname in EXPLICIT_CHANNELS else None,
                "SourceUvUsage": None, "UvEvidence": None,
                "Unresolved": ["Texture sampling UV, tiling and shader composition are absent from the extracted ShaderGraph",
                               "Normal decoding/handedness unverified"] if "normal" in pname else
                              ["Texture sampling UV, tiling and shader composition are absent from the extracted ShaderGraph"],
            })
        displacement = base["Raw"].get("DisplacementMap", {})
        if displacement.get("Kind") not in (None, "Null"):
            n = self.nodes.get(displacement.get("Node"), {})
            t = self.textures.get(n.get("TextureResource"), {})
            channel = base["Raw"].get("DisplacementMapTexCoord")
            state["TextureBindings"].append({
                "Parameter": "DisplacementMap", "TextureNode": n.get("Id"), "ResourceId": n.get("TextureResource"),
                "Asset": n.get("Asset"), "Path": t.get("Path"), "ColorSpace": t.get("ColorSpace", "unspecified"),
                "SourceUvUsage": "TexCoord" + str(channel) if isinstance(channel, int) else None,
                "UvEvidence": "MeshMaterial.DisplacementMapTexCoord", "Channels": None,
                "Unresolved": ["Displacement decoding/tessellation not implemented; no geometry displacement applied"],
            })
        state["Unresolved"] = ["Compiled shader graph/default constants are unavailable",
                               "Runtime paint, damage, dirt, lights and wetness are not evaluated"]
        return state

    @staticmethod
    def appearance_key(state):
        # Distinct override object identities with identical appearance are equivalent.
        return key({k: state[k] for k in ("Shader", "Parameters")})

    def choose_root(self, mesh, slot):
        roots = [v for v in mesh.get("Variants", []) if v["Hash"] == "00000000"]
        if not roots:
            return self.resolve(mesh, slot), [], "base_only_no_root_db"
        states = [self.resolve(mesh, slot, v) for v in roots]
        if len({self.appearance_key(s) for s in states}) != 1:
            return self.resolve(mesh, slot), roots, "ambiguous_root_db_base_preserved"
        return states[0], roots, "equivalent_root_db"


def _signature(vertices, counts, indices):
    """SHA-256 of the vertices as little-endian float32 (FBX doubles store the exact source float values; Blender stores
    floats), then every face as its vertex count and vertex indices (uint32)."""
    import numpy as np
    h = hashlib.sha256()
    h.update(np.asarray(vertices, dtype=np.float64).astype("<f4").tobytes())
    counts = np.asarray(counts, dtype=np.int64)
    starts = np.cumsum(counts) - counts
    h.update(np.insert(np.asarray(indices, dtype=np.int64), starts, counts).astype("<u4").tobytes())
    return h.hexdigest()


def mesh_signature(mesh):
    """_signature of a Blender mesh, read in bulk."""
    import numpy as np
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    counts = np.empty(len(mesh.polygons), dtype=np.int64)
    starts = np.empty(len(mesh.polygons), dtype=np.int64)
    mesh.polygons.foreach_get("loop_total", counts)
    mesh.polygons.foreach_get("loop_start", starts)
    corners = np.empty(len(mesh.loops), dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", corners)
    if not np.array_equal(starts, np.cumsum(counts) - counts):  # corners not stored in face order
        corners = np.concatenate([corners[s:s + c] for s, c in zip(starts, counts)]) if len(counts) else corners
    return _signature(co.reshape(-1, 3), counts, corners)


FBX_TREES = {}


def parsed_fbx(filepath):
    """The parsed FBX tree of a part file, read once per import (FBX_TREES is cleared when an import or surface build
    ends): the slot restore and the tangent check both need it."""
    from io_scene_fbx import parse_fbx
    key = str(Path(filepath).resolve())
    if key not in FBX_TREES:
        FBX_TREES[key] = parse_fbx.parse(key)[0]
    return FBX_TREES[key]


def fbx_sections(filepath, record):
    """Match native FBX section nodes by connection order and source names."""
    import numpy as np
    tree = parsed_fbx(filepath)
    objects = next(e for e in tree.elems if e.id == b"Objects")
    connections = next(e for e in tree.elems if e.id == b"Connections")
    geometries = {e.props[0]: e for e in objects.elems if e.id == b"Geometry" and e.props[-1] == b"Mesh"}
    models = {e.props[0]: e for e in objects.elems if e.id == b"Model"}
    geometry_model = {}
    child_parent = {}
    for c in connections.elems:
        if c.props[0] == b"OO":
            child_parent[c.props[1]] = c.props[2]
            if c.props[1] in geometries:
                geometry_model[c.props[2]] = c.props[1]
    ordered = [c.props[1] for c in connections.elems if c.props[0] == b"OO" and c.props[1] in geometry_model]
    expected = [s for s in record["Sections"] if s["Renderable"]]
    if len(ordered) != len(expected):
        raise ValueError("FBX/source section count mismatch")
    result = []
    for mid, section in zip(ordered, expected):
        model = models[mid]
        name = model.props[1].split(b"\x00")[0].decode()
        parent = models.get(child_parent[mid])
        parentname = parent.props[1].split(b"\x00")[0].decode() if parent else None
        if name != section["FbxNodeName"] or parentname != section["FbxLodParent"]:
            raise ValueError("FBX/source section order or LOD parent mismatch")
        geom = geometries[geometry_model[mid]]
        fields = {e.id: e for e in geom.elems}
        values = fields[b"Vertices"].props[0]
        vertices = np.asarray(values, dtype=np.float64).reshape(-1, 3)
        faces, pending, removed, duplicates, seen = [], [], [], [], set()
        for index in fields[b"PolygonVertexIndex"].props[0]:
            pending.append(index if index >= 0 else ~index)
            if index < 0:
                if len(set(pending)) < 3:
                    removed.append(pending)
                elif frozenset(pending) in seen:
                    # Blender's mesh validation drops a face whose vertex set repeats an earlier face
                    # (verified on four M3 E46 exhaust sections: signatures match exactly after this removal).
                    duplicates.append(pending)
                else:
                    seen.add(frozenset(pending))
                    faces.append(pending)
                pending = []
        if len(faces) + len(removed) + len(duplicates) != section["PrimitiveCount"]:
            raise ValueError("FBX/source primitive count mismatch")
        result.append({"Section": section, "Signature": _signature(vertices, [len(f) for f in faces], [i for f in faces for i in f]),
                       "FbxGeometryId": str(geom.props[0]), "RemovedDegenerateIndices": removed,
                       "RemovedDuplicateFaces": duplicates})
    return result


def match_object(obj, candidates):
    signature = mesh_signature(obj.data)
    matches = [c for c in candidates if c["Signature"] == signature]
    if len(matches) > 1:
        # Existing imports retain this name; assembled copies retain original_name.
        name = obj.get("unbound_original_name", obj.name)
        matches = [c for c in matches if name == c["Section"]["Name"] or
                   re.fullmatch(re.escape(c["Section"]["Name"]) + r"\.\d{3,}", name)]
    if len(matches) > 1:
        # Repeated identical sections (same name, geometry, material slot and vertex layout): every choice yields
        # the same slot, material and inputs, so the lowest section index stands for all of them.
        keys = {json.dumps([c["Section"]["Name"], c["Section"]["MaterialSlot"], c["Section"].get("VertexAttributes")],
                           sort_keys=True) for c in matches}
        if len(keys) == 1:
            return dict(min(matches, key=lambda c: c["Section"]["SectionIndex"]),
                        EquivalentSections=sorted(c["Section"]["SectionIndex"] for c in matches))
    if len(matches) != 1:
        raise ValueError("Ambiguous/unmatched native FBX geometry signature: " + obj.name)
    return matches[0]


def principled_group(family):
    """Reusable wiring, deliberately no invented family-specific constants."""
    import bpy
    name = "Unbound | " + family + " | source inputs"
    group = bpy.data.node_groups.get(name)
    if group:
        return group
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    group["unbound_template"] = VERSION
    group["status"] = "Template only; no family defaults or source equivalence claimed"
    principled = group.nodes.new("ShaderNodeBsdfPrincipled")
    principled.label = "Only evidence-backed inputs may be bound"
    inputs = group.nodes.new("NodeGroupInput")
    output = group.nodes.new("NodeGroupOutput")
    socket_names = ("Base Color", "Metallic", "Roughness", "IOR", "Alpha", "Normal",
                    "Coat Weight", "Coat Roughness", "Transmission Weight",
                    "Emission Color", "Emission Strength")
    for n in socket_names:
        socket = principled.inputs.get(n)
        if socket is None:
            continue
        socket_type = {"RGBA": "NodeSocketColor", "VECTOR": "NodeSocketVector"}.get(socket.type, "NodeSocketFloat")
        if hasattr(group, "interface"):
            interface = group.interface.new_socket(name=n, in_out="INPUT", socket_type=socket_type)
        else:
            interface = group.inputs.new(socket_type, n)
        if hasattr(socket, "default_value"):
            interface.default_value = socket.default_value
        group.links.new(inputs.outputs[n], socket)
    if hasattr(group, "interface"):
        group.interface.new_socket(name="BSDF", in_out="OUTPUT", socket_type="NodeSocketShader")
    else:
        group.outputs.new("NodeSocketShader", "BSDF")
    group.links.new(principled.outputs["BSDF"], output.inputs["BSDF"])
    inputs.location = (-300, 0)
    output.location = (300, 0)
    return group


@functools.lru_cache(maxsize=16384)
def _safe_texture(root, relative):
    if not relative:
        raise ValueError("Missing exported texture path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Texture path escapes export folder")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def build_material(state, root, label, diagnostics):
    import bpy
    identity = key(state)
    existing = next((m for m in bpy.data.materials if m.get("unbound_state_key") == identity
                     and not m.get("unbound_surface_profile")), None)
    if existing:
        return existing
    mat = bpy.data.materials.new(label)
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    mat["unbound_state_key"] = identity
    mat["unbound_source_json"] = canonical(state)
    mat["unbound_material_node"] = state["BaseNode"]
    mat["unbound_shader"] = (state["Shader"] or {}).get("Asset", "")
    mat["unbound_family"] = state["Family"] or "Unresolved"
    mat["unbound_status"] = "Source identity restored; surface output intentionally unconnected"
    output = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
    output.label = "UNRESOLVED shader — not a reconstructed appearance"
    output.location = (700, 0)
    if state["Family"]:
        node = mat.node_tree.nodes.new("ShaderNodeGroup")
        node.node_tree = principled_group(state["Family"])
        node.label = state["Family"] + " template (inactive; missing source inputs)"
        node.location = (400, 0)
    # Retain typed source values for inspection, without assigning unsupported meaning.
    for index, (name, parameter) in enumerate(state["Parameters"]["VectorParameters"].items()):
        ptype = parameter.get("ParameterType", {}).get("Name")
        val = parameter.get("Value", {})
        if ptype == "ShaderParameterType_Scalar":
            node = mat.node_tree.nodes.new("ShaderNodeValue")
            node.outputs[0].default_value = val.get("x", 0)
        elif ptype == "ShaderParameterType_Color":
            node = mat.node_tree.nodes.new("ShaderNodeRGB")
            node.outputs[0].default_value = tuple(val.get(a, 0) for a in "xyzw")
        else:
            continue
        node.label = plain(parameter["ParameterName"]) + " (raw source)"
        node["unbound_parameter"] = canonical(parameter)
        node.location = (-800, -index * 140)
    for index, binding in enumerate(state["TextureBindings"]):
        frame = mat.node_tree.nodes.new("NodeFrame")
        frame.label = binding["Parameter"] + " | UV: " + (binding.get("SourceUvUsage") or "UNKNOWN")
        frame["source_binding_json"] = canonical(binding)
        frame.location = (-300, -index * 370)
        node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        node.parent = frame
        node.label = binding["Asset"] or "Missing texture reference"
        node["sampling_enabled"] = False
        try:
            texturepath = _safe_texture(root, binding.get("Path"))
            image = next((im for im in bpy.data.images if im.get("unbound_resource_id") == binding["ResourceId"] and
                          im.get("unbound_source_path") == str(texturepath)), None)
            if image is None:
                image = bpy.data.images.load(str(texturepath), check_existing=False)
                image["unbound_resource_id"] = binding["ResourceId"]
                image["unbound_source_path"] = str(texturepath)
                image["unbound_source_colorspace"] = binding["ColorSpace"]
                # Raw inspection for unknown transfer function; not a semantic assertion.
                image.colorspace_settings.name = "sRGB" if binding["ColorSpace"] == "sRGB" else "Non-Color"
                image.alpha_mode = "CHANNEL_PACKED"
                if image.size[0] == 0:
                    raise ValueError("Blender cannot decode this DDS; original file retained")
            node.image = image
        except Exception as exc:
            diagnostics.append({"Material": label, "Texture": binding, "Issue": str(exc)})
        if binding.get("Channels"):
            separate = mat.node_tree.nodes.new("ShaderNodeSeparateColor")
            separate.mode = "RGB"
            separate.parent = frame
            separate.location = (300, 0)
            separate.label = canonical(binding["Channels"])
            mat.node_tree.links.new(node.outputs["Color"], separate.inputs["Color"])
        # No vector input link: sampling is not used anywhere in a rendered surface.
        # Even a single available UV channel is not evidence the shader uses it.
    return mat


def reconstruct(filepath, objects=None):
    """Restore every mesh's original material slots now."""
    steps = reconstruct_steps(filepath, objects)
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def reconstruct_steps(filepath, objects=None):
    """Generator form of reconstruct: yields (done, total) per source mesh, returns the report."""
    import bpy
    path = Path(filepath).resolve()
    if path.name != "materials.json":
        path = path.with_name("materials.json")
    root = path.parent
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    resolver = Resolver(document)
    objects = list(objects if objects is not None else bpy.context.scene.objects)
    report = {"Schema": 1, "Version": VERSION, "Source": str(path),
              "Objects": [], "Materials": [], "Issues": [], "GeometryPolicy": "Only material slots and per-face material indices are modified"}
    diagnostics = report["Issues"]
    grouped = defaultdict(list)
    for obj in objects:
        if obj.type == "MESH" and obj.get("unbound_mesh_id") in resolver.meshes:
            grouped[obj["unbound_mesh_id"]].append(obj)
    for family in FAMILIES:
        principled_group(family).use_fake_user = True
    for done, (meshid, members) in enumerate(grouped.items()):
        yield done, len(grouped)
        mesh = resolver.meshes[meshid]
        try:
            fbx = _safe_texture(root, mesh["Fbx"])
            candidates = fbx_sections(fbx, mesh)
            # Preflight an entire source mesh before creating/changing its slots.
            assignments = [(o, match_object(o, candidates)) for o in members]
            slots = sorted(mesh["Slots"], key=lambda s: s["Index"])
            if [s["Index"] for s in slots] != list(range(len(slots))):
                raise ValueError("Non-contiguous original material slots")
            states = [resolver.choose_root(mesh, s) for s in slots]
            for o, c in assignments:
                if c["Section"]["MaterialSlot"] not in range(len(slots)):
                    raise ValueError("Source section material slot out of range")
                if o.data.materials and not o.data.get("unbound_slots_restored"):
                    raise ValueError("Existing user material slots preserved; use a fresh copy/import")
            materials = []
            for slot, (state, roots, status) in zip(slots, states):
                names = sorted({s["Name"] for s in mesh["Sections"] if s["MaterialSlot"] == slot["Index"]})
                label = (names[0] if len(names) == 1 else "Slot " + str(slot["Index"])) + " | " + slot["Source"]["Node"][-8:]
                material = build_material(state, root, label, diagnostics)
                materials.append(material)
                report["Materials"].append({"MeshId": meshid, "Slot": slot["Index"], "Material": material.name,
                                            "Resolution": status, "State": state,
                                            "RootRows": [{"DatabaseGuid": v["DatabaseGuid"], "Row": v["Row"]} for v in roots]})
                if status.startswith("ambiguous"):
                    diagnostics.append({"MeshId": meshid, "Slot": slot["Index"], "Issue": status})
            modified = set()
            for obj, candidate in assignments:
                section = candidate["Section"]
                if obj.data not in modified:
                    obj.data.materials.clear()
                    for material in materials:
                        obj.data.materials.append(material)
                    for poly in obj.data.polygons:
                        poly.material_index = section["MaterialSlot"]
                    obj.data["unbound_slots_restored"] = VERSION
                    modified.add(obj.data)
                # Object-linked slots allow future variation overrides on shared geometry.
                for i, material in enumerate(materials):
                    obj.material_slots[i].link = "OBJECT"
                    obj.material_slots[i].material = material
                bindings = uv_bindings(section)
                missing = [b["BlenderLayer"] for b in bindings if b["BlenderLayer"] not in obj.data.uv_layers]
                if missing:
                    diagnostics.append({"Object": obj.name, "Issue": "Expected source UV layers missing", "Layers": missing})
                obj["unbound_section_index"] = section["SectionIndex"]
                obj["unbound_fbx_geometry_id"] = candidate["FbxGeometryId"]
                if candidate.get("EquivalentSections"):
                    obj["unbound_equivalent_sections_json"] = canonical(candidate["EquivalentSections"])
                obj["unbound_uv_bindings_json"] = canonical(bindings)
                obj["unbound_material_slot"] = section["MaterialSlot"]
                obj["unbound_material_source"] = slots[section["MaterialSlot"]]["Source"]["Node"]
                obj["unbound_materials_path"] = str(path)
                report["Objects"].append({"Object": obj.name, "MeshId": meshid, "SectionIndex": section["SectionIndex"],
                    "MaterialSlot": section["MaterialSlot"], "FacesAssigned": len(obj.data.polygons),
                    "UVBindings": bindings,
                    "RemovedDegenerateIndices": candidate["RemovedDegenerateIndices"]})
        except Exception as exc:
            diagnostics.append({"MeshId": meshid, "Issue": str(exc), "Severity": "assignment_failed"})
    text = bpy.data.texts.new("An's Garage material slot report")
    text.write(json.dumps(report, indent=2))
    text["unbound_report"] = VERSION
    return report
