"""Stance: the garage's ride height and front/rear camber sliders.

The car's stock visual-suspension item (assembly.json "Stance", exported by An's Garage for Frosty) lists each slider's
range, stock setting and the physics attributes it changes, linearly from Min (slider minimum) to Max (slider maximum);
attributes from several sliders add up. The visible ones move the wheels' Suspension empties:
- ATM_XCarBodyYOffset: the body moves down over the wheels. Here the wheels rise into the body by the same amount (the
  car itself stays where it is);
- ATM_XCarWheelCamberTop/Bottom<axle>: camber, tops in. Read as radians; the top/bottom pair (equal on every car
  checked) is taken as one angle; both unchecked;
- ATM_XCarWheelXOffsetTop/Bottom<axle>: the wheel moves out along its axle (track width).
Caster and ATM_XCarMultiplier change no wheel position at rest and are not applied.
"""
import json
from pathlib import Path

from .unbound_assembly import world_matrix

KEYS = {"ID_TUNING_RIDEHEIGHTHEIGHT": ("ride_height", "Ride height"),
        "ID_TUNING_CAMBERFRONT": ("camber_front", "Front camber"),
        "ID_TUNING_CAMBERREAR": ("camber_rear", "Rear camber")}
ADDITION = "ModificationType_Addition"


def sliders(root):
    """[{Key, Text, Min, Max, Stock, ...}] of a car with stance sliders, else []."""
    return json.loads(root.get("ans_garage_stance_json") or "{}").get("Sliders", [])


def controls(root):
    """The object holding the car's stance sliders (custom properties), or None."""
    import bpy
    return bpy.data.objects.get(root.get("ans_garage_stance", ""))


def linear(rows, attributes):
    """(constant, {slider key: slope}) of the mean of `attributes` over the sliders' changes, as a function of the
    sliders' values."""
    const, slope = 0.0, {}
    for s in rows:
        span = (s["Max"] - s["Min"]) or 1
        for change in s["Changes"]:
            if change["Attribute"] in attributes and change["Type"] == ADDITION:
                k = (change["Max"] - change["Min"]) / span / len(attributes)
                const += change["Min"] / len(attributes) - k * s["Min"]
                slope[s["Key"]] = slope.get(s["Key"], 0.0) + k
    return const, slope


def _drive(target, path, index, obj, const, slope, scale):
    """target.path[index] = scale x (const + sum(slope x slider)): a simple expression (no Python scripts needed)."""
    curve = target.driver_add(path, index)
    driver = curve.driver
    driver.type = "SCRIPTED"
    terms = ["%r" % (scale * const)] + ["%r*%s" % (scale * k, key) for key, k in slope.items() if abs(scale * k) > 1e-12]
    driver.expression = " + ".join(terms)
    for key in slope:
        var = driver.variables.new()
        var.name = key
        var.type = "SINGLE_PROP"
        var.targets[0].id_type = "OBJECT"
        var.targets[0].id = obj
        var.targets[0].data_path = '["%s"]' % key
    for m in list(curve.modifiers):
        curve.modifiers.remove(m)


def build(root):
    """Stance sliders for an assembled car, driving its wheels. Returns lines for the car's report."""
    import bpy
    from mathutils import Vector
    data = json.loads(Path(root["unbound_assembly_path"]).read_text(encoding="utf-8-sig"))
    stance = data.get("Stance") or {}
    rows = []
    for i, s in enumerate(stance.get("Sliders") or []):
        key, text = KEYS.get(s["Label"], ("stance_%d" % i, s["Label"]))
        rows.append(dict(s, Key=key, Text=text))
    root["ans_garage_stance_json"] = json.dumps({"Item": stance.get("Item"), "Sliders": rows})
    if not rows:
        return ["None in this car's data (export it again with An's Garage for Frosty 1.1.7)"]
    obj = bpy.data.objects.new(root.name + " | Stance", None)
    obj.empty_display_size = 0.01
    root.objects.link(obj)
    obj.hide_viewport = obj.hide_render = True
    for s in rows:
        obj[s["Key"]] = int(s["Stock"])
        obj.id_properties_ui(s["Key"]).update(min=int(s["Min"]), max=int(s["Max"]), soft_min=int(s["Min"]),
                                              soft_max=int(s["Max"]), step=1, default=int(s["Stock"]),
                                              description="%s, as the game's stance slider (stock %d)" % (s["Text"], s["Stock"]))
    root["ans_garage_stance"] = obj.name
    lift = linear(rows, {"ATM_XCarBodyYOffset"})
    wheels = [o for o in root.all_objects if o.get("wheel_side") and o.name.split(".")[0].endswith("| Suspension")]
    for susp in wheels:
        axle = "Front" if "Front" in susp["wheel_side"] else "Rear"
        camber = linear(rows, {"ATM_XCarWheelCamberTop" + axle, "ATM_XCarWheelCamberBottom" + axle})
        track = linear(rows, {"ATM_XCarWheelXOffsetTop" + axle, "ATM_XCarWheelXOffsetBottom" + axle})
        rest = world_matrix(susp.parent)
        basis = rest.to_3x3()
        to_local = basis.normalized().inverted()
        side = 1.0 if rest.translation.x > 0 else -1.0
        outward, up, forward = (to_local @ Vector(v) for v in ((side, 0, 0), (0, 0, 1), (0, 1, 0)))
        # Tops in: about the car's forward axis, towards the car's centre; mirrored rest frames turn the other way.
        turn = -side * (-1.0 if basis.determinant() < 0 else 1.0)
        susp.rotation_mode = "AXIS_ANGLE"
        susp.rotation_axis_angle = (0.0, forward.x, forward.y, forward.z)
        _drive(susp, "rotation_axis_angle", 0, obj, camber[0], camber[1], turn)
        for i in range(3):
            # The body goes down by the offset: the wheel goes up into it.
            const = -lift[0] * up[i] + track[0] * outward[i]
            slope = {k: -lift[1].get(k, 0.0) * up[i] + track[1].get(k, 0.0) * outward[i]
                     for k in set(lift[1]) | set(track[1])}
            _drive(susp, "location", i, obj, const, slope, 1.0)
    travel = -min((c["Min"] for s in rows for c in s["Changes"] if c["Attribute"] == "ATM_XCarBodyYOffset"), default=0.0)
    return ["%s (%s): %s; ride height lowers the car up to %.0f mm" % (
        stance.get("Item", "").rsplit("/", 1)[-1], "%d wheels" % len(wheels),
        ", ".join("%s %d-%d, stock %d" % (s["Text"], s["Min"], s["Max"], s["Stock"]) for s in rows), travel * 1000)]


def set_stock(root):
    obj = controls(root)
    if obj is None:
        return
    for s in sliders(root):
        obj[s["Key"]] = int(s["Stock"])
    obj.update_tag()
