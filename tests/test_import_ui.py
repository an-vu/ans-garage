"""Interactive (non-blocking) import from the UI: progress in the sidebar, screenshots along the way.
Run with a window (no --background):
blender --factory-startup --python test_import_ui.py -- <addon parent dir> <manifest.json> <out dir>
"""
import importlib
import json
import sys
import time
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, manifest, out_dir = Path(args[0]), args[1], Path(args[2])
out_dir.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(addon_parent))
addon = importlib.import_module("ans_garage")
addon.register()
state = {"shots": [], "samples": [], "start": None}
marks = [5, 35, 70, 90]


def window_context():
    win = bpy.context.window_manager.windows[0]
    area = next(a for a in win.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return {"window": win, "screen": win.screen, "area": area, "region": region}


def shot(label):
    path = out_dir / ("ui-%s.png" % label)
    with bpy.context.temp_override(**window_context()):
        bpy.ops.screen.screenshot(filepath=str(path), check_existing=False)
    state["shots"].append(path.name)


def start():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    with bpy.context.temp_override(**window_context()):
        result = bpy.ops.import_scene.ans_garage_vehicle("EXEC_DEFAULT", filepath=manifest)
    state["start"], state["result"] = time.time(), list(result)
    bpy.app.timers.register(watch, first_interval=0.5)


def watch():
    run = addon.RUN
    if run:
        # The UI keeps redrawing between import slices: record that timer callbacks keep arriving.
        state["samples"].append([round(time.time() - state["start"], 2), run["stage"], round(run["pct"], 1)])
        if marks and run["pct"] >= marks[0]:
            shot("%02d" % marks.pop(0))
        return 0.5
    shot("done")
    gaps = [b[0] - a[0] for a, b in zip(state["samples"], state["samples"][1:])]
    roots = [c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path")]
    summary = {"Started": state["result"], "Seconds": round(time.time() - state["start"], 1),
               "Samples": len(state["samples"]), "LongestUiGap": round(max(gaps), 2) if gaps else None,
               "LongestGapDuring": state["samples"][gaps.index(max(gaps))][1:] if gaps else None,
               "Stages": sorted({s[1] for s in state["samples"]}), "Assembled": [r.name for r in roots],
               "Meshes": len([o for o in bpy.context.scene.objects if o.type == "MESH"]), "Shots": state["shots"]}
    (out_dir / "ui-import.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print("UI IMPORT", json.dumps(summary, ensure_ascii=False))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(start, first_interval=1.0)
