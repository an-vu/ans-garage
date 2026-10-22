"""Non-destructive, source-backed vehicle assembly for the existing FBX importer.

Only imported object copies and collection memberships change. Mesh datablocks,
UVs, color attributes, split normals, groups and the original hierarchy are reused.
"""
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from . import unbound_wheels as wheels


def category(item):
    """Presentation labels use actual item type/location, never compatibility guesses."""
    kind, location = item["Type"], item.get("Location", "")
    end = "Front" if location == "ItemPosition_Front" else "Rear" if location == "ItemPosition_Rear" else ""
    names = {"BumperItemData": end + " Bumper", "FendersItemData": end + " Fenders",
             "LightsItemData": "Headlights" if end == "Front" else "Taillights" if end == "Rear" else "Lights",
             "SideSkirtsItemData": "Side Skirts", "WingMirrorsItemData": "Mirrors",
             "HoodItemData": "Hood", "TrunkLidItemData": "Boot", "SpoilerItemData": "Spoiler",
             "SplitterItemData": "Front Splitter", "DiffuserItemData": "Rear Diffuser",
             "ExhaustItemData": "Exhaust", "CanardsItemData": end + " Canards"}
    return names.get(kind, re.sub(r"(?<!^)(?=[A-Z])", " ", kind.removesuffix("ItemData"))).strip()


def set_code(asset):
    """Source set code from the asset name (e.g. setb, setrzr); kept for traceability next to in-game names."""
    m = re.search(r"_(set[^_/]+(?:_alt[a-z])?)(?:_mesh)?$", asset.rsplit("/", 1)[-1], re.I)
    return m.group(1).lower() if m else None


def ui_category(item):
    return ((item.get("UI") or {}).get("Category")) or None


# Brands whose names the game's localized text doesn't contain, spelled by hand (only used when the exporter found none).
BRAND_SPELLINGS = {"bigcountrylabs": "Big Country Labs"}


def brand_title(ui):
    """Kit brand for parts without a localized name: the exporter's brand title (the game's own text for the logo
    key, 1.0.1+), else a hand-spelled name for brands the text lacks, else the logo key itself, title-cased."""
    if ui.get("BrandTitle"):
        return ui["BrandTitle"]
    key = (ui.get("BrandKey") or "").removeprefix("t_custombrand_")
    return BRAND_SPELLINGS.get(key) or (key.replace("_", " ").title() if key else None)


def item_label(item):
    """(in-game option name, status). Exporter 0.5.0+ records ItemUI names from the game's localization table."""
    ui = item.get("UI") or {}
    if ui.get("DisplayName") and ui["DisplayName"] != ui.get("Category"):  # early 0.5.0 builds fell back to the category
        return ui["DisplayName"], "localized"
    if ui:
        cat = ui.get("Category") or category(item)
        brand = brand_title(ui)
        status = "no localized name (category + brand from the game's text)" if ui.get("BrandTitle") else \
            "no localized name (category + brand logo key)"
        return cat + (" · " + brand if brand else ""), status
    return None, "exported before 0.5.0 (no in-game names)"


def preset_label(preset, items_by_asset):
    """Preset name: its own localized name, else the brand every sub-item shares, else set code + logo key."""
    ui = preset.get("UI") or {}
    if ui.get("DisplayName"):
        return ui["DisplayName"]
    code = set_code(preset["Asset"]) or preset["Asset"].rsplit("/", 1)[-1]
    brands = {((items_by_asset.get((s.get("Asset") or "").lower()) or {}).get("UI") or {}).get("BrandName")
              for s in preset.get("SubItems", [])}
    if len(brands) == 1 and None not in brands:
        return "Body kit: " + brands.pop() + " (" + code + ")"
    if ui.get("BrandKey"):
        return "Body kit: " + brand_title(ui) + " (" + code + ")"
    return "Body kit " + code


def option_name(item):
    name = item["Asset"].rsplit("/", 1)[-1]
    match = re.search(r"_(set[^_]+(?:_.*)?)$", name, re.I)
    return "Stock" if item.get("Default") else (match.group(1).replace("_", " ").title() if match else name)


def matrix_from_basis(values):
    from mathutils import Matrix
    if len(values) != 12 or not all(math.isfinite(x) for x in values):
        raise ValueError("Invalid authored transform")
    return Matrix(((values[0], values[3], values[6], values[9]),
                   (values[1], values[4], values[7], values[10]),
                   (values[2], values[5], values[8], values[11]), (0, 0, 0, 1)))


def _all_collections(root):
    yield root
    for child in root.children:
        yield from _all_collections(child)


def set_variant(root, group, option):
    """Switch complete item permutations without touching mesh or transform data."""
    _apply_selections(root, {group: option})
    if root.get("unbound_presets_json"):
        root["active_source_preset"] = current_preset(root)


def current_preset(root):
    """Describe actual collection choices, rather than the last preset button."""
    selected = {}
    for c in _all_collections(root):
        if "unbound_option" in c and not c.hide_viewport:
            group = c["unbound_group"]
            if group in selected:
                return "Custom"
            selected[group] = c["unbound_option"]
    for name, choices in json.loads(root.get("unbound_presets_json", "{}")).items():
        if choices == selected:
            return name
    return "Custom"


def _apply_selections(root, selections):
    # Validate the complete preset before changing visibility. Recompute duplicate
    # suppression once after every group is in its final state.
    collections = list(_all_collections(root))
    pending = []
    for group, option in selections.items():
        choices = [c for c in collections if c.get("unbound_group") == group and "unbound_option" in c]
        if not any(c["unbound_option"] == option for c in choices):
            raise ValueError("Unknown assembly variant for " + group + ": " + str(option))
        pending.extend((c, c["unbound_option"] != option) for c in choices)
    for collection, hidden in pending:
        if collection.hide_viewport != hidden or collection.hide_render != hidden:
            collection.hide_viewport = collection.hide_render = hidden
    _suppress_duplicates(root)


def _suppress_duplicates(root):
    import bpy
    # Only identical source + complete placement may be suppressed. Intersection
    # of bounding boxes alone is NOT evidence that different car parts are duplicates.
    seen = set()
    count = 0
    pending, issues = [], []
    def walk(c, visible):
        nonlocal count
        visible = visible and not c.hide_viewport
        if "unbound_instance_key" in c:
            key = c["unbound_instance_key"]
            duplicate = visible and key in seen
            # Blender invalidates its cached recursive collection object iterator
            # when hide_set/hide_render changes visibility. Retain actual object
            # references BEFORE any visibility writes; otherwise later iterator
            # entries can become None after reopening a .blend.
            for o in tuple(c.all_objects):
                if o is None:
                    issues.append({"Collection": c.name, "Issue": "Missing object reference during visibility snapshot"})
                else:
                    pending.append((o, duplicate))
            if duplicate:
                count += 1
            elif visible:
                seen.add(key)
        for sub in tuple(c.children):
            walk(sub, visible)
    walk(root, True)
    view_layer = bpy.context.view_layer
    in_layer = set(view_layer.objects.keys())
    for obj, duplicate in pending:
        # Excluded layer collections have no object Base in this view layer.
        # Their exclusion stays intact; render visibility can still be updated.
        # Only changed values are written: every write re-evaluates the scene (about 2 s per part switch on a car
        # with 1,500 objects when all were rewritten).
        if obj.name in in_layer and obj.hide_get(view_layer=view_layer) != duplicate:
            obj.hide_set(duplicate, view_layer=view_layer)
        if obj.hide_render != duplicate:
            obj.hide_render = duplicate
    root["suppressed_exact_duplicate_instances"] = count
    root["unbound_variant_issues_json"] = json.dumps(issues)


def apply_preset(root, preset):
    spec = json.loads(root["unbound_presets_json"])
    if preset not in spec:
        raise ValueError("Unknown source preset")
    _apply_selections(root, spec[preset])
    root["active_source_preset"] = preset


def assemble_existing(manifest_path):
    import bpy
    from mathutils import Matrix
    path = Path(manifest_path).resolve()
    assembly_path = path.with_name("assembly.json")
    data = json.loads(assembly_path.read_text(encoding="utf-8-sig"))
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("Schema") != 1 or manifest.get("Schema") != 1:
        raise ValueError("Unsupported assembly/geometry manifest schema")
    if data.get("Status") not in ("completed", "completed_with_issues"):
        raise ValueError("Assembly extraction is incomplete")
    if any(c.get("unbound_assembly_path") == str(assembly_path) for c in bpy.data.collections):
        raise ValueError("This assembly is already present. Use the variant controls; no duplicate assembly was created.")
    records = {m["Id"]: m for m in manifest["Meshes"] if m["Status"] == "exported"}
    templates = defaultdict(list)
    for o in bpy.context.scene.objects:
        key = o.get("unbound_mesh_id")
        if key in records and not o.get("unbound_assembled"):
            templates[key].append(o)
    if data.get("BodyMeshId") not in templates:
        raise ValueError("Import the vehicle's manifest.json first; the body mesh is missing.")
    if len(data["Wheels"]) != 4 or len({w["Name"] for w in data["Wheels"]}) != 4:
        raise ValueError("Four unique authored wheel links are required; no placement will be invented.")
    # Validate matrices, mesh coverage and input files before creating collections.
    for w in data["Wheels"]:
        matrix_from_basis(w["Transform"])
    missing = sorted({u["MeshId"] for u in data["MeshUses"]} - templates.keys())
    if missing:
        raise ValueError("Missing assembly geometry: import the updated manifest, including shared tires/brakes. " + ", ".join(missing))
    nodes = {n["Id"]: n for n in data["Nodes"]}
    uses = defaultdict(list)
    for use in data["MeshUses"]:
        uses[use["BlueprintGuid"]].append(use)
    bpy.context.view_layer.update()
    # Exact conversion inherited from this native FBX's Blender root, avoiding a
    # separately guessed coordinate system. Rigid wheel roots carry FBX Y-up conversion.
    front_rim_item = next(i for i in data["Items"] if i["Type"] == "RimsItemData" and i["Default"])
    rim_use = uses[front_rim_item["Permutations"][0]["Meshes"][0]["BlueprintGuid"]][0]
    sample = templates[rim_use["MeshId"]]
    sample_roots = [o for o in sample if o.parent not in sample]
    if len(sample_roots) != 1:
        raise ValueError("Ambiguous FBX conversion root; assembly not guessed.")
    conversion = sample_roots[0].matrix_world.copy()
    if conversion.translation.length > 1e-5 or any(abs(s-1) > 1e-4 for s in conversion.to_scale()):
        raise ValueError("FBX root conversion has unexpected translation/scale.")
    inverse = conversion.inverted()

    diagnostics = []
    def col(label, parent):
        c = bpy.data.collections.new(label)
        parent.children.link(c)
        return c
    name = data["Vehicle"]["Asset"].rsplit("/", 1)[-1]
    # Human-readable title is cosmetic; the exact vehicle identity is retained.
    name = ((data.get("VehicleName") or {}).get("Long")
            or re.sub(r"^car_", "", name, flags=re.I).replace("_", " ").title())
    root = col(name, bpy.context.scene.collection)
    root["vehicle_name_json"] = json.dumps(data.get("VehicleName") or {})
    root["fbx_to_blender_matrix"] = json.dumps([list(r) for r in conversion])
    root["unbound_assembly_path"] = str(assembly_path)
    root["unbound_manifest_path"] = str(path)
    root["vehicle_asset"] = data["Vehicle"]["Asset"]
    root["placement_status"] = "Authored rest pose; runtime loaded suspension is not simulated."
    root["variant_policy"] = "Exact item memberships; source permutation 1 is the preview default. Restriction/offset runtime evaluation is unresolved."
    library = col("Source geometry (preserved)", root)
    # Rehome originals intact, rather than editing/deleting their geometry.
    for meshid, objects in templates.items():
        source = col(records[meshid]["Asset"].rsplit("/", 1)[-1], library)
        source["unbound_mesh_id"] = meshid
        for o in objects:
            source.objects.link(o)
            for old in list(o.users_collection):
                if old != source:
                    old.objects.unlink(o)
    # Unlink now-empty legacy hierarchy from this scene; it remains a datablock.
    for old in list(bpy.context.scene.collection.children):
        if old != root and old.get("manifest") and not old.all_objects:
            bpy.context.scene.collection.children.unlink(old)
    bpy.context.view_layer.update()
    layer_root = bpy.context.view_layer.layer_collection.children[root.name]
    layer_root.children[library.name].exclude = True

    def empty(label, collection, parent=None, transform=None):
        o = bpy.data.objects.new(label, None)
        collection.objects.link(o)
        o.empty_display_type = "PLAIN_AXES"
        o.empty_display_size = 0.08
        if parent:
            o.parent = parent
        if transform is not None:
            o.matrix_basis = transform
        o["unbound_assembled"] = True
        return o

    def instance(meshid, collection, label, parent=None, local=None, body=False):
        # Object copies share immutable geometry. Armature targets are remapped.
        originals = templates[meshid]
        inst = col(label, collection)
        transform = local if local is not None else Matrix.Identity(4)
        inst["unbound_instance_key"] = json.dumps([meshid, [round(x, 8) for row in transform for x in row],
                                                    parent.get("wheel_side") if parent else None])
        mapping = {}
        for source in originals:
            clone = source.copy()
            inst.objects.link(clone)
            mapping[source] = clone
            clone["unbound_assembled"] = True
            clone["unbound_original_name"] = source.name
            clone["unbound_baseline_matrix_world"] = json.dumps([list(r) for r in source.matrix_world])
        for source, clone in mapping.items():
            clone.parent = mapping.get(source.parent, parent)
            if source.parent in mapping:
                clone.matrix_parent_inverse = source.matrix_parent_inverse.copy()
                clone.matrix_basis = source.matrix_basis.copy()
            else:
                clone.matrix_parent_inverse = Matrix.Identity(4)
                clone.matrix_basis = transform @ source.matrix_world
            for modifier in clone.modifiers:
                if modifier.type == "ARMATURE" and modifier.object in mapping:
                    modifier.object = mapping[modifier.object]
        if body:
            subgroups = {}
            for o in mapping.values():
                if o.type != "MESH":
                    continue
                rawname = o["unbound_original_name"].lower()
                group = "Windows" if "glass_window" in rawname else "Interior" if "interior" in rawname else "Body panels"
                subgroups.setdefault(group, None)
                if subgroups[group] is None:
                    subgroups[group] = col(group, inst)
                subgroups[group].objects.link(o)
                inst.objects.unlink(o)
        else:
            plates = [o for o in mapping.values() if o.type == "MESH" and "licenseplate" in o["unbound_original_name"].lower()]
            if plates:
                plate_col = col("License Plate", inst)
                for o in plates:
                    plate_col.objects.link(o)
                    inst.objects.unlink(o)
        return inst

    body = col("Body", root)
    instance(data["BodyMeshId"], body, "Original body assembly", body=True)
    wheel_root = col("Wheels", root)
    wheel_controls = {}
    tire_config = nodes[data["TireConfig"]]["Raw"] if data.get("TireConfig") in nodes else {}
    for w in data["Wheels"]:
        c = col(w["Name"], wheel_root)
        authored = matrix_from_basis(w["Transform"])
        rest = empty(w["Name"] + " | Rest position", c, transform=conversion @ authored @ inverse)
        rest["source_wheel_node"] = w["WheelComponent"]
        rest["source_transform_json"] = json.dumps(w["Transform"])
        suspension = empty(w["Name"] + " | Suspension", c, rest)
        steering = empty(w["Name"] + " | Steering", c, suspension)
        spin = empty(w["Name"] + " | Rotation", c, steering)
        for o in (rest, suspension, steering, spin):
            o["wheel_side"] = w["Name"]
        spin["animation_axis"] = "Local X axle; rest-space axes converted from FBX"
        steering["animation_axis"] = "Local Blender Z (authored Y)"
        suspension["animation_axis"] = "Local Blender Z (authored Y)"
        wheel_controls[w["Name"]] = (c, steering, spin)
    used = {data["BodyMeshId"]}
    # Source wheel declarations are explicit; runtime resize/deformation is tracked separately.
    defaults, item_choices, group_collections = {}, {}, {}

    def mount(item, collection):
        """Instances of a wheel item's meshes on their wheels (rims, tires and brakes spin; calipers steer only)."""
        for desc in item["Permutations"][0]["Meshes"]:
            facing = desc.get("Facing")
            if not facing or facing["Name"] not in wheel_controls:
                diagnostics.append("Unresolved wheel facing: " + item["Asset"])
                continue
            c, steering, spin = wheel_controls[facing["Name"]]
            blueprint, rotate, offsets = desc["BlueprintGuid"], desc["Rotate"], None
            status = "Original authored rim/part dimensions retained; runtime shader resize not applied."
            if item["Type"] == "TiresItemData":
                infos = item.get("TireMeshInfos") or []
                info = next((i for i in infos if any(m["MeshGuid"] == blueprint for m in i["Meshes"])), None)
                axle = "Front" if facing["Front"] else "Rear"
                outer = tire_config.get("Diameter" + axle)
                width = tire_config.get("SectionWidth" + axle)
                rim = wheels.rim_diameter(data, tire_config, axle)
                if info and outer and width and rim:
                    # The sidewall size the game picks for this rim; exports before 1.0.9 hold only the default one.
                    chosen = wheels.tire_size(infos, rim, outer, item["Raw"]["SmallToMedRatio"], item["Raw"]["MedToLargeRatio"])
                    tag = ((desc.get("Raw") or {}).get("Tag") or {}).get("Asset", "").lower()
                    mesh = next((m for m in chosen["Meshes"] if ((m.get("Tag") or {}).get("Asset") or "").lower() == tag), chosen["Meshes"][0])
                    if mesh["MeshGuid"] in uses:
                        blueprint, rotate, info = mesh["MeshGuid"], mesh["Rotate"], chosen
                    offsets = wheels.tire_offsets(info, outer, rim, width)
                    status = ("Wheel fit (the game's tire shader, per vertex): %.3f m sidewall mesh, tread %+.4f m, bead %+.4f m, "
                              "each side %+.4f m, from the tire configuration and the %.3f m rim%s"
                              % (info["InnerDiameter"], offsets[0], offsets[1], offsets[2], rim,
                                 "" if info is chosen else "; the game's %.3f m sidewall mesh is not in this export" % chosen["InnerDiameter"]))
                else:
                    status = "Tire dimensions unresolved: source size preserved."
                    diagnostics.append(status + " " + item["Asset"])
                # Every size counts as placed: only one is shown.
                for i in infos:
                    for m in i["Meshes"]:
                        used.update(u["MeshId"] for u in uses.get(m["MeshGuid"], []))
            rotation = Matrix.Rotation(math.pi, 4, "Y") if rotate else Matrix.Identity(4)
            kind = {"RimsItemData": "Rim", "TiresItemData": "Tire", "BrakeDiscsItemData": "Brake Disc", "CalipersItemData": "Caliper"}[item["Type"]]
            parent = steering if item["Type"] == "CalipersItemData" else spin
            for use in uses[blueprint]:
                proxy = Matrix.Identity(4)
                for matrix in use["TransformChain"]:
                    proxy = proxy @ matrix_from_basis(matrix)
                inst = instance(use["MeshId"], collection or c, kind, parent, conversion @ rotation @ proxy @ inverse)
                inst["source_item"] = item["Asset"]
                inst["source_rotate_flag"] = rotate
                inst["dimension_status"] = status
                inst["source_item_json"] = json.dumps(item["Raw"])
                if offsets:
                    wheels.fit(inst.all_objects, offsets)
                used.add(use["MeshId"])

    for item in data["Items"]:
        if item["Type"] in ("TiresItemData", "BrakeDiscsItemData", "CalipersItemData") and item["Default"] and item["Permutations"]:
            mount(item, None)
    # The car's own wheel sets (its factory rims in the game; up to four, e.g. the Aventador S): one choice group, the
    # front and rear items of a set sharing its set code. The game names every set "Stock", so the others show their code.
    rim_sets = defaultdict(list)
    for item in data["Items"]:
        if item["Type"] == "RimsItemData" and item["Permutations"]:
            rim_sets[set_code(item["Asset"]) or item["Asset"]].append(item)
    if rim_sets:
        group = "Rims"
        parent_col = group_collections[group] = col("Wheels (rim sets)", root)
        parent_col["unbound_choice_group"], parent_col["unbound_label"] = group, "Wheels"
        parent_col["show_variants"] = False
        for code, items in sorted(rim_sets.items(), key=lambda kv: (not any(i["Default"] for i in kv[1]), kv[0])):
            stock = any(i["Default"] for i in items)
            text = "Stock" if stock else re.sub(r"^set", "", code).upper() if len(code) <= 7 else re.sub(r"^set", "", code).title()
            option = "rims/" + code
            variant = col("Wheels | " + text, parent_col)
            variant["unbound_group"], variant["unbound_option"], variant["unbound_label"] = group, option, text
            variant["unbound_set_code"] = code
            variant["unbound_item"] = ", ".join(i["Asset"] for i in items)
            for item in items:
                mount(item, variant)
                item_choices[item["Asset"].lower()] = (group, option)
            if stock:
                defaults[group] = option
            variant.hide_viewport = variant.hide_render = not stock
    # Item meshes authored relative to their customization component are placed at that component (component chain
    # composed root to leaf; the component comes from the mesh blueprint's BlueprintComponents entry). Evidence: every
    # spoiler of the Chiron Sport and P1 is modelled around the origin and its SpoilerCustomizationComponentData
    # carries the deck position (the P1's -0.44 m lateral offset centres its asymmetric wing); the Diablo's pop-up
    # headlights sit on LightsCustomizationComponentData at the front corners. A mesh already in car space (its centre
    # would leave the body) keeps its authored placement.
    comp_by_node = {c["Node"]: c for c in data.get("Components", [])}
    comp_owners = data.get("BlueprintComponents") or {}

    def component_matrix(c):
        chain = []
        while c is not None and c not in chain:
            chain.append(c)
            c = comp_by_node.get(c.get("Parent"))
        m = Matrix.Identity(4)
        for c in reversed(chain):
            m = m @ matrix_from_basis(c["Transform"])
        return m
    def world_box(objects, transform):
        from mathutils import Vector
        pts = [transform @ o.matrix_world @ Vector(c) for o in objects if o.type == "MESH" for c in o.bound_box]
        return ([min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]) if pts else None

    def placement_for(blueprint, meshid):
        # Geometry centred on the component's own position is already in car space (e.g. the Countach's unnamed
        # setepic wing); geometry centred near the origin is modelled relative to the component.
        from mathutils import Vector
        comps = {o["Component"] for o in comp_owners.get(blueprint, []) if o["Component"] in comp_by_node}
        matrices = {tuple(round(x, 6) for row in component_matrix(comp_by_node[c]) for x in row): c for c in comps}
        if len(matrices) != 1:
            if len(matrices) > 1:
                diagnostics.append("%s: on %d components with different positions; authored placement kept"
                                   % (records[meshid]["Asset"].rsplit("/", 1)[-1], len(matrices)))
            return None
        comp = comp_by_node[next(iter(matrices.values()))]
        m = component_matrix(comp)
        if all(abs(m[i][j] - (1.0 if i == j else 0.0)) <= 1e-6 for i in range(4) for j in range(4)):
            return None
        local = conversion @ m @ inverse
        box = world_box(templates[meshid], Matrix.Identity(4))
        if not box:
            return None
        centre = Vector([(a + b) / 2 for a, b in zip(*box)])
        if (centre - local.translation).length < centre.length:
            diagnostics.append("%s: geometry already sits at the %s position (car space); authored placement kept"
                               % (records[meshid]["Asset"].rsplit("/", 1)[-1], comp["Type"]))
            return None
        return local

    # In-game labels: the group shows the game's category when all its items agree; options show the game's option
    # name, with the set code added where two options would otherwise read the same.
    group_items = defaultdict(list)
    for item in data["Items"]:
        if item["Type"] not in ("RimsItemData", "TiresItemData", "BrakeDiscsItemData", "CalipersItemData") and item["Permutations"]:
            group_items[category(item)].append(item)
    group_label, option_label = {}, {}
    for group, items in group_items.items():
        cats = {ui_category(i) for i in items}
        group_label[group] = cats.pop() if len(cats) == 1 and None not in cats else group
        names = defaultdict(list)
        for i in items:
            names[item_label(i)[0]].append(i)
        for text, same in names.items():
            for i in same:
                code = set_code(i["Asset"])
                label = text or option_name(i)
                if text and len(same) > 1 and code:
                    label += " (" + code + ")"
                option_label[i["Node"]] = label
    for item in data["Items"]:
        if item["Type"] in ("RimsItemData", "TiresItemData", "BrakeDiscsItemData", "CalipersItemData") or not item["Permutations"]:
            continue
        group = category(item)
        if group not in group_collections:
            group_collections[group] = col(group_label.get(group, group), root)
        parent_col = group_collections[group]
        if not parent_col.get("unbound_choice_group"):
            parent_col["unbound_choice_group"] = group
            parent_col["unbound_label"] = group_label.get(group, group)
            parent_col["show_variants"] = False
            none = col(group_label.get(group, group) + " | None", parent_col)
            none["unbound_group"], none["unbound_option"] = group, "none"
            none["unbound_label"] = "None (hide this part)"
        for index, permutation in enumerate(item["Permutations"]):
            if permutation.get("Deprecated"):
                continue
            option = item["Node"] + "/" + str(index)
            text = option_label.get(item["Node"]) or option_name(item)
            if index:
                text += " / Source configuration " + str(index + 1)
            variant = col(group_label.get(group, group) + " | " + text, parent_col)
            variant["unbound_group"], variant["unbound_option"] = group, option
            variant["unbound_label"] = text
            variant["unbound_name_status"] = item_label(item)[1]
            variant["unbound_set_code"] = set_code(item["Asset"]) or ""
            variant["unbound_item"] = item["Asset"]
            variant["source_permutation_json"] = json.dumps(permutation)
            variant["compatibility_status"] = "Source membership preserved; runtime restrictions and permutation offsets not evaluated."
            if item["Default"] and index == 0:
                defaults[group] = option
            if index == 0:
                item_choices[item["Asset"].lower()] = (group, option)
            local_seen = set()
            for desc in permutation["Meshes"]:
                if desc.get("Facing") or desc["Rotate"]:
                    diagnostics.append("Non-wheel tagged/rotated item needs explicit placement: " + item["Asset"])
                    continue
                for use in uses.get(desc["BlueprintGuid"], []):
                    # Body parts already align; preserve their exact existing world matrices.
                    key = use["MeshId"]
                    if key in local_seen:
                        continue
                    local_seen.add(key)
                    label = records[key]["Asset"].rsplit("/", 1)[-1]
                    label = re.sub(r"^car_.*?_\d{4}_", "", label).removesuffix("_mesh").replace("_", " ").title()
                    local = placement_for(desc["BlueprintGuid"], key)
                    inst = instance(key, variant, label, local=local)
                    if local is not None:
                        inst["placement_status"] = "Placed at the item's customization component (source transform)"
                    inst["source_blueprint_guid"] = desc["BlueprintGuid"]
                    used.add(key)
            variant.hide_viewport = variant.hide_render = defaults.get(group) != option
    for group_col in root.children:
        group = group_col.get("unbound_choice_group")
        if group:
            defaults.setdefault(group, "none")
            set_variant(root, group, defaults[group])
    presets = {"Stock": defaults}
    items_by_asset = {i["Asset"].lower(): i for i in data["Items"]}
    for preset in data.get("Presets", []):
        choices = dict(defaults)
        missing_items = []
        for p in preset["SubItems"]:
            match = item_choices.get((p.get("Asset") or "").lower())
            if match:
                choices[match[0]] = match[1]
            else:
                missing_items.append(p.get("Asset"))
        label = preset_label(preset, items_by_asset)
        while label in presets:
            label += " +"
        presets[label] = choices
        if missing_items:
            diagnostics.append("Unresolved preset items: " + str(missing_items))
    root["unbound_presets_json"] = json.dumps(presets)
    root["active_source_preset"] = "Stock"
    leftovers = col("Unassigned source parts (review)", root)
    leftovers.hide_viewport = leftovers.hide_render = True
    for meshid in sorted(set(templates) - used):
        instance(meshid, leftovers, records[meshid]["Asset"].rsplit("/", 1)[-1])
        diagnostics.append("No selected blueprint/item placement: " + records[meshid]["Asset"])
    _suppress_duplicates(root)
    diagnostics += [
        "Right-side Rotate flag interpreted as a half turn about source Y; outward rim facing checked, runtime implementation unavailable.",
        "Tires are fitted per vertex with the game's wheel shader formula (Wheel fit modifier); its inputs are derived from the "
        "tire configuration and declared part sizes, not yet read from the running game.",
        "Brake disc/caliper shader sizing, caliper runtime offsets, loaded suspension and camber are not reconstructed.",
        "Variant collections preserve item permutations; runtime restrictions/offsets are recorded, not guessed.",
        "Material IDs are custom metadata; no placeholder materials or shaders were generated."
    ]
    root["diagnostics_json"] = json.dumps(diagnostics)
    text = bpy.data.texts.new("An's Garage assembly report")
    text.write("Authored vehicle assembly\n" + "\n".join(diagnostics))
    bpy.context.view_layer.update()
    return root, diagnostics
