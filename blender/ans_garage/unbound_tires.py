"""Tire library: swap a car's tires for real-brand tires (Falken, Toyo) at the car's own stock tire size.

The library is exported once by An's Garage for Frosty (Tools > An's Garage > Export tire library...) and imported
once per .blend into a hidden collection: each tire mesh in a plain and a brand-lettered version. Choosing a tire
hides the car's stock tire instances and places the library tire the same way the stock tire is placed: the size
whose inner (rim) diameter matches the stock tire, scaled to the car's tire configuration, on the wheel's rotation
empty. Nothing about the car's wheel or tire size changes.
"""
import json
import math
from pathlib import Path

LIBRARY = "An's Garage tire library"
STOCK = "Stock"


def load_index(folder):
    path = Path(folder) / "tires.json"
    if not path.is_file():
        raise FileNotFoundError("No tires.json in %s (export it in Frosty: Tools > An's Garage > Export tire library...)" % folder)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def tire_names(index):
    names = []
    for t in index["Tires"]:
        if t["Name"] not in names:
            names.append(t["Name"])
    return names


def _addon():
    import importlib
    return importlib.import_module(__package__)


def ensure_library(folder):
    """Import the library once (hidden collection): {(mesh asset, lettering): [template objects]}."""
    import bpy
    folder = Path(folder).resolve()
    index = load_index(folder)
    lib = bpy.data.collections.get(LIBRARY)
    if lib is None or lib.get("ans_garage_tire_library") != str(folder):
        if lib is not None:
            for o in list(lib.all_objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.collections.remove(lib)
        lib = bpy.data.collections.new(LIBRARY)
        bpy.context.scene.collection.children.link(lib)
        lib["ans_garage_tire_library"] = str(folder)
        overrides = index["ShaderOverrides"]
        for brand in index["Brands"]:
            manifest = folder / brand / "manifest.json"
            before = set(bpy.data.objects)
            steps = _addon().import_steps(manifest, assemble=False, materials=False)
            for _ in steps:
                pass
            plain = [o for o in bpy.data.objects if o not in before]
            # Material slots from the source data, then a lettered copy of every object.
            _addon().materials_module().reconstruct(manifest, plain)
            records = {m["Id"]: m for m in json.loads(manifest.read_text(encoding="utf-8-sig"))["Meshes"]}
            lettered = []
            for o in plain:
                c = o.copy()
                bpy.context.scene.collection.objects.link(c)
                lettered.append(c)
                for x in (o, c):
                    x["unbound_compiled_profile_only"] = True
                    x["unbound_override_textures"] = str(folder / "override-textures")
                o["ans_garage_lettering"], c["ans_garage_lettering"] = "Plain", "Brand"
            remap = dict(zip(plain, lettered))
            for o, c in remap.items():
                if o.parent in remap:
                    c.parent = remap[o.parent]
                for m in c.modifiers:
                    if m.type == "ARMATURE" and m.object in remap:
                        m.object = remap[m.object]
            # Brand lettering = the brand's tirebomb override, per mesh blueprint.
            mesh_by_blueprint = index["Blueprints"]
            for c in lettered:
                asset = records.get(c.get("unbound_mesh_id"), {}).get("Asset", "")
                textures = {}
                for ov in overrides.values():
                    if brand not in ov["Asset"].lower().replace("toyoproxies", "toyo"):
                        continue
                    for m in ov["Mappings"]:
                        if mesh_by_blueprint.get(m["BlueprintGuid"], "").lower() == asset.lower():
                            textures.update(m["Textures"])
                if textures:
                    c["unbound_texture_overrides_json"] = json.dumps(textures)
            for o in plain + lettered:
                o["ans_garage_tire_mesh"] = records.get(o.get("unbound_mesh_id"), {}).get("Asset", "")
                for col in list(o.users_collection):
                    col.objects.unlink(o)
                lib.objects.link(o)
            _addon().surfaces_module().apply_supported_surfaces(plain + lettered, manifest)
        for col in [c for c in bpy.data.collections if c.name.startswith("Unbound | ") and not c.all_objects]:
            for parent in [p for p in bpy.data.collections if col.name in p.children] + [bpy.context.scene.collection]:
                if col.name in parent.children:
                    parent.children.unlink(col)
        layer = bpy.context.view_layer.layer_collection.children.get(LIBRARY)
        if layer:
            layer.exclude = True
    templates = {}
    for o in lib.all_objects:
        templates.setdefault((o.get("ans_garage_tire_mesh", "").lower(), o.get("ans_garage_lettering")), []).append(o)
    return index, templates


def apply_tire(root, name, lettering, folder):
    """Show the named library tire (or the car's stock tire) on all four wheels."""
    import bpy
    from mathutils import Matrix
    for c in list(root.children_recursive):
        if c.get("ans_garage_library_tire"):
            for o in list(c.all_objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.collections.remove(c)
    stock_instances = [c for c in root.children_recursive if c.get("source_item") and c.get("unbound_tire_stock")]
    if not stock_instances:
        stock_instances = [c for c in root.children_recursive
                           if (json.loads(c.get("source_item_json", "{}")).get("Type") == "TiresItemData")]
        for c in stock_instances:
            c["unbound_tire_stock"] = True
    root["ans_garage_tire_json"] = json.dumps({"Name": name, "Lettering": lettering})
    for c in stock_instances:
        c.hide_viewport = c.hide_render = name != STOCK
    if name == STOCK:
        return []
    assembly = Path(root["unbound_assembly_path"])
    if not assembly.is_file():
        raise FileNotFoundError("This car's export folder has moved: %s is missing. Put the export back where it was "
                                "imported from to change its tires." % assembly)
    index, templates = ensure_library(folder)
    data = json.loads(assembly.read_text(encoding="utf-8-sig"))
    nodes = {n["Id"]: n for n in data["Nodes"]}
    tire_config = nodes[data["TireConfig"]]["Raw"] if data.get("TireConfig") in nodes else {}
    conversion = Matrix([tuple(r) for r in json.loads(root["fbx_to_blender_matrix"])])
    inverse = conversion.inverted()
    notes = []
    stock_items = [i for i in data["Items"] if i["Type"] == "TiresItemData" and i["Default"]]
    for wheel in data["Wheels"]:
        facing = wheel["Facing"]
        axle = "Front" if facing["Front"] else "Rear"
        side = "left" if facing["Left"] else "right"
        spin = next((o for o in root.all_objects if o.name.startswith(wheel["Name"] + " | Rotation")), None)
        wheel_col = next((c for c in root.children_recursive if c.name.split(".")[0] == wheel["Name"]), None)
        if spin is None or wheel_col is None:
            notes.append("%s: wheel controls not found" % wheel["Name"])
            continue
        # Stock tire size on this wheel: the TireMeshInfo holding the stock mesh placed there.
        stock_inner = None
        for item in stock_items:
            for perm in item["Permutations"][:1]:
                for desc in perm["Meshes"]:
                    if (desc.get("Facing") or {}).get("Name") != wheel["Name"]:
                        continue
                    for info in (item.get("TireMeshInfos") or []):
                        if any(m["MeshGuid"] == desc["BlueprintGuid"] for m in info["Meshes"]):
                            stock_inner = info["InnerDiameter"]
        tire = next((t for t in index["Tires"] if t["Name"] == name and t["Lettering"] == lettering
                     and t["Position"] == "ItemPosition_" + axle), None)
        if tire is None or stock_inner is None:
            notes.append("%s: %s" % (wheel["Name"], "no library tire for this axle" if tire is None else "stock tire size unknown"))
            continue
        size = min(tire["Sizes"], key=lambda s: abs(s["InnerDiameter"] - stock_inner))
        desc = next((m for m in size["Meshes"] if side in (m.get("Tag") or "").lower()), size["Meshes"][0])
        sources = templates.get((desc["Mesh"].lower(), lettering), [])
        if not sources:
            notes.append("%s: library mesh %s not imported" % (wheel["Name"], desc["Mesh"]))
            continue
        rotation = Matrix.Rotation(math.pi, 4, "Y") if desc["Rotate"] else Matrix.Identity(4)
        outer, width = tire_config.get("Diameter" + axle), tire_config.get("SectionWidth" + axle)
        scaling = (Matrix.Diagonal((width / 1000.0 / size["Width"], outer / size["OuterDiameter"], outer / size["OuterDiameter"], 1))
                   if outer and width else Matrix.Identity(4))
        local = conversion @ rotation @ scaling @ inverse
        inst = bpy.data.collections.new("Tire | " + name)
        wheel_col.children.link(inst)
        inst["ans_garage_library_tire"] = True
        inst["source_item"] = tire["Asset"]
        inst["dimension_status"] = "Library tire at the stock tire's rim size (inner diameter %.3f m), scaled to the car's tire configuration" % size["InnerDiameter"]
        mapping = {}
        for s in sources:
            c = s.copy()
            inst.objects.link(c)
            mapping[s] = c
            c["unbound_assembled"] = True
        for s, c in mapping.items():
            if s.parent in mapping:
                c.parent = mapping[s.parent]
                c.matrix_parent_inverse = s.matrix_parent_inverse.copy()
                c.matrix_basis = s.matrix_basis.copy()
            else:
                c.parent = spin
                c.matrix_parent_inverse = Matrix.Identity(4)
                c.matrix_basis = local @ s.matrix_world
            for m in c.modifiers:
                if m.type == "ARMATURE" and m.object in mapping:
                    m.object = mapping[m.object]
    return notes
