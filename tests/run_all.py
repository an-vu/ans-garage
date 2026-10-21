"""Run the Blender test suite with paths from settings.json.

usage: python tests/run_all.py [existing] [fresh] [nodes] [vehicle:<export folder name>] ...
With no arguments: existing, fresh and nodes on the Murciélago test data. Results go to <validation_dir>/latest.
Needs (in test_data_dir): input-merci-tires-0.5.0.blend, Murcielago-Export, Murcielago-Export-bare.
The install ZIP for "fresh" comes from tools/package_release.py (<release_dir>/<version>/AnsGarage-Blender-<version>.zip).
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "tools"))
from settings import path as setting  # noqa: E402

BLENDER = str(setting("blender_exe"))
DATA = setting("test_data_dir")
OUT = setting("validation_dir") / "latest"
VERSION = ".".join(map(str, eval(re.search(r'"version": (\([^)]*\))', (REPO / "blender/ans_garage/__init__.py").read_text()).group(1))))


def blender(args, log):
    print("running", log, flush=True)
    with open(OUT / (log + ".log"), "w", encoding="utf-8") as f:
        r = subprocess.run([BLENDER, "--background", "--factory-startup", "--python-exit-code", "1"] + args,
                           stdout=f, stderr=subprocess.STDOUT)
    text = (OUT / (log + ".log")).read_text(encoding="utf-8", errors="replace")
    summary = [l for l in text.splitlines() if l.startswith(("PASSED", "FAIL "))]
    print("  ", "ok" if r.returncode == 0 else "FAILED (exit %d)" % r.returncode, *summary[-4:], sep="\n   ")
    return r.returncode == 0


def main(tests):
    OUT.mkdir(parents=True, exist_ok=True)
    tests = tests or ["existing", "fresh", "nodes"]
    ok = True
    for t in tests:
        if t == "existing":
            scene = OUT / "work-existing.blend"
            shutil.copy2(DATA / "input-merci-tires-0.5.0.blend", scene)
            ok &= blender([str(scene), "--python", str(HERE / "test_existing_full.py"), "--",
                           str(REPO / "blender"), str(DATA / "Murcielago-Export" / "materials.json"), str(OUT)], "existing")
        elif t == "fresh":
            zipfile = setting("release_dir") / VERSION / ("AnsGarage-Blender-%s.zip" % VERSION)
            ok &= blender(["--python", str(HERE / "test_fresh.py"), "--", str(zipfile), str(OUT / "zip-test"),
                           str(DATA / "Murcielago-Export"), str(DATA / "Murcielago-Export-bare"), str(OUT)], "fresh")
        elif t == "nodes":
            ok &= blender(["--python", str(HERE / "test_node_compiler.py"), "--", str(REPO / "blender" / "ans_garage"),
                           str(DATA / "Murcielago-Export" / "materials.json"), str(OUT / "node-compiler.json")], "nodes")
        elif t.startswith("vehicle:"):
            name = t.split(":", 1)[1]
            ok &= blender(["--python", str(HERE / "test_vehicle.py"), "--", str(REPO / "blender"),
                           str(setting("exports_dir") / name), str(OUT), name], "vehicle-" + name)
        else:
            raise SystemExit("unknown test " + t)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
