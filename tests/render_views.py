"""Render validation views of the visible assembled vehicle. Neutral studio lighting (not game lighting).
blender --background <scene.blend> --python render_views.py -- <out prefix> [engine] [samples] [views]
"""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
prefix = Path(args[0])
engine = args[1] if len(args) > 1 else "CYCLES"
samples = int(args[2]) if len(args) > 2 else 32
views = args[3].split(",") if len(args) > 3 else ["front_left", "rear_right", "side", "top"]
scene = bpy.context.scene
objs = [o for o in scene.objects if o.type == "MESH" and o.visible_get()]
lo = Vector((min(v[i] for o in objs for v in (o.matrix_world @ Vector(c) for c in o.bound_box)) for i in range(3)))
hi = Vector((max(v[i] for o in objs for v in (o.matrix_world @ Vector(c) for c in o.bound_box)) for i in range(3)))
center, size = (lo + hi) / 2, (hi - lo)
print("bounds", lo, hi)
world = bpy.data.worlds.new("Unbound validation studio")
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
sky = world.node_tree.nodes.new("ShaderNodeTexSky")
if hasattr(sky, "sky_type"):
    try:
        sky.sky_type = "HOSEK_WILKIE"
    except TypeError:
        pass
world.node_tree.links.new(sky.outputs[0], bg.inputs[0])
bg.inputs[1].default_value = 0.6
scene.world = world
sun_data = bpy.data.lights.new("Unbound validation sun", "SUN")
sun_data.energy = 3.0
sun = bpy.data.objects.new("Unbound validation sun", sun_data)
sun.rotation_euler = (math.radians(50), 0, math.radians(35))
scene.collection.objects.link(sun)
floor_mesh = bpy.data.meshes.new("floor")
r = max(size) * 4
floor_mesh.from_pydata([(-r, -r, 0), (r, -r, 0), (r, r, 0), (-r, r, 0)], [], [(0, 1, 2, 3)])
floor = bpy.data.objects.new("Unbound validation floor", floor_mesh)
floor.location.z = lo.z
fm = bpy.data.materials.new("floor")
fm.use_nodes = True
fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.18, 0.18, 0.18, 1)
fm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.6
floor_mesh.materials.append(fm)
scene.collection.objects.link(floor)
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 50
cam = bpy.data.objects.new("Unbound validation camera", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.engine = "BLENDER_EEVEE" if engine.startswith("EEVEE") else "CYCLES"
if scene.render.engine == "CYCLES":
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.get_devices()
        for kind in ("OPTIX", "CUDA", "HIP", "ONEAPI"):
            try:
                prefs.compute_device_type = kind
                if any(d.type == kind for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = True
                    scene.cycles.device = "GPU"
                    break
            except TypeError:
                continue
    except Exception as exc:
        print("GPU setup", exc)
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.render.film_transparent = False
scene.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in scene.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
dist = max(size) * 1.25
dirs = {"front_left": Vector((-0.8, -1.0, 0.35)), "rear_right": Vector((0.8, 1.0, 0.35)),
        "side": Vector((-1.0, 0.0, 0.12)), "top": Vector((0.25, -0.35, 1.0)), "front": Vector((0, -1, 0.15)),
        "rear": Vector((0, 1, 0.2)), "front_right": Vector((0.8, -1.0, 0.25))}
for name in views:
    d = dirs[name].normalized()
    cam.location = center + d * dist * (1.35 if name == "top" else 1.0)
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(prefix) + "-" + name + ".png"
    bpy.ops.render.render(write_still=True)
    print("rendered", scene.render.filepath)
