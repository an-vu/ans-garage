"""Run the Blender test suite with paths from settings.json.

usage: python tests/run_all.py [full|quick] [--jobs N] [test ...]
  test: existing, fresh, nodes, tires, plates, conditions, vehicle:<export folder name>
  (no tests)  every test: existing, fresh, nodes, tires, plates, conditions and each vehicle in VEHICLES that is exported
  quick       nodes and vehicle:murcielago only
  full        run even tests whose inputs have not changed since they last passed
  --jobs N    Blender processes at once (default 4); the tests are independent

A test is skipped when its inputs (test script, the add-on files it uses, its data) are unchanged since it last passed;
fingerprints are kept in <validation_dir>/latest/test-state.json. "fresh" rebuilds the install ZIP first
(tools/package_release.py). Needs (in test_data_dir): input-merci-tires-0.5.0.blend, Murcielago-Export,
Murcielago-Export-bare. Results go to <validation_dir>/latest.
Manual tools in this folder (not run here): render_views.py (studio renders of an assembled car), DialogShot.cs
(screenshots of the Frosty plugin's dialogs).
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ADDON = REPO / "blender" / "ans_garage"
sys.path.insert(0, str(REPO / "tools"))
from settings import path as setting  # noqa: E402

BLENDER = str(setting("blender_exe"))
DATA = setting("test_data_dir")
EXPORTS = setting("exports_dir")
OUT = setting("validation_dir") / "latest"
STATE = OUT / "test-state.json"
VERSION = ".".join(map(str, eval(re.search(r'"version": (\([^)]*\))', (ADDON / "__init__.py").read_text()).group(1))))
VEHICLES = ["murcielago", "bmw-m3e46", "chiron-sport", "mclaren-p1", "diablo-sv", "taycan", "integra", "audi-s5"]
QUICK = ["nodes", "vehicle:murcielago"]
EXPORT_FILES = ("manifest.json", "assembly.json", "materials.json")
# Add-on files each test exercises (the whole add-on where it imports a car).
MATERIALS = ["unbound_profiles.py", "unbound_materials.py", "shader_profiles.json.gz"]
USES = {"nodes": MATERIALS,
        "existing": MATERIALS + ["__init__.py", "unbound_surfaces.py", "unbound_assembly.py"]}


def addon_files(test):
    names = USES.get(test.split(":")[0])
    return [ADDON / n for n in names] if names else sorted(p for p in ADDON.iterdir() if p.is_file() and p.suffix in (".py", ".json", ".gz"))


def plan(test):
    """(script, Blender arguments, data files) of one test."""
    if test == "existing":
        script = "test_existing_full.py"
        args = [str(OUT / "work-existing.blend"), "--python", str(HERE / script), "--", str(REPO / "blender"),
                str(DATA / "Murcielago-Export" / "materials.json"), str(OUT)]
        data = [DATA / "input-merci-tires-0.5.0.blend", DATA / "Murcielago-Export" / "materials.json"]
    elif test == "fresh":
        script = "test_fresh.py"
        zipfile = setting("release_dir") / VERSION / ("AnsGarage-Blender-%s.zip" % VERSION)
        args = ["--python", str(HERE / script), "--", str(zipfile), str(OUT / "zip-test"),
                str(DATA / "Murcielago-Export"), str(DATA / "Murcielago-Export-bare"), str(OUT)]
        data = [DATA / x / f for x in ("Murcielago-Export", "Murcielago-Export-bare") for f in EXPORT_FILES]
    elif test == "nodes":
        script = "test_node_compiler.py"
        args = ["--python", str(HERE / script), "--", str(ADDON), str(DATA / "Murcielago-Export" / "materials.json"),
                str(OUT / "node-compiler.json")]
        data = [DATA / "Murcielago-Export" / "materials.json"]
    elif test == "tires":
        script = "test_tires.py"
        args = ["--python", str(HERE / script), "--", str(REPO / "blender"), str(EXPORTS / "murcielago"),
                str(EXPORTS / "tire-library"), str(OUT / "tires")]
        data = [EXPORTS / "murcielago" / f for f in EXPORT_FILES] + [EXPORTS / "tire-library" / "tires.json"]
    elif test == "plates":
        script = "test_plates.py"
        args = ["--python", str(HERE / script), "--", str(REPO / "blender"), str(EXPORTS / "murcielago"),
                str(EXPORTS / "plate-library"), str(OUT / "plates")]
        data = [EXPORTS / "murcielago" / f for f in EXPORT_FILES] + [EXPORTS / "plate-library" / "plates.json"]
    elif test == "conditions":
        script = "test_conditions.py"
        args = ["--python", str(HERE / script), "--", str(REPO / "blender"), str(EXPORTS / "murcielago"), str(OUT / "conditions")]
        data = [EXPORTS / "murcielago" / f for f in EXPORT_FILES]
    elif test.startswith("vehicle:"):
        name = test.split(":", 1)[1]
        script = "test_vehicle.py"
        args = ["--python", str(HERE / script), "--", str(REPO / "blender"), str(EXPORTS / name), str(OUT), name]
        data = [EXPORTS / name / f for f in EXPORT_FILES]
    else:
        raise SystemExit("unknown test " + test)
    return script, args, data


def fingerprint(test):
    script, _, data = plan(test)
    h = hashlib.sha256()
    for path in [HERE / script] + addon_files(test) + data:
        h.update(str(path.name).encode())
        h.update(path.read_bytes() if path.is_file() else b"missing")
    return h.hexdigest()


def run(test):
    """Run one test in its own Blender; returns (test, passed, seconds, summary lines)."""
    _, args, _ = plan(test)
    log = OUT / (test.replace(":", "-") + ".log")
    if test == "existing":
        shutil.copy2(DATA / "input-merci-tires-0.5.0.blend", OUT / "work-existing.blend")
    started = time.time()
    with open(log, "w", encoding="utf-8") as f:
        r = subprocess.run([BLENDER, "--background", "--factory-startup", "--python-exit-code", "1"] + args,
                           stdout=f, stderr=subprocess.STDOUT)
    text = log.read_text(encoding="utf-8", errors="replace")
    summary = [l for l in text.splitlines() if l.startswith(("PASSED", "FAIL "))]
    return test, r.returncode == 0, time.time() - started, summary[-4:]


def main(argv):
    OUT.mkdir(parents=True, exist_ok=True)
    jobs, force, tests = 4, False, []
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--jobs":
            jobs = int(args.pop(0))
        elif a == "full":
            force = True
        elif a == "quick":
            tests += QUICK
        else:
            tests.append(a)
    if not tests:
        tests = ["existing", "fresh", "nodes", "tires"] + ["plates"] * (EXPORTS / "plate-library" / "plates.json").is_file() + ["conditions"] + ["vehicle:" + v for v in VEHICLES if (EXPORTS / v / "manifest.json").is_file()]
    if "fresh" in tests:
        # The install test always checks the current code: rebuild the ZIP first (a few seconds).
        subprocess.run([sys.executable, "-I", str(REPO / "tools" / "package_release.py")], check=True, stdout=subprocess.DEVNULL)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.is_file() else {}
    prints = {t: fingerprint(t) for t in tests}
    todo = [t for t in tests if force or state.get(t, {}).get("Fingerprint") != prints[t]]
    for t in tests:
        if t not in todo:
            print("skip %-22s unchanged since it passed (%s, %d s)" % (t, state[t]["PassedAt"], state[t]["Seconds"]))
    started, ok = time.time(), True
    # Longest tests first, so the slowest one isn't left running alone at the end.
    todo.sort(key=lambda t: -state.get(t, {}).get("Seconds", 0))
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for future in as_completed([pool.submit(run, t) for t in todo]):
            test, passed, seconds, summary = future.result()
            ok &= passed
            print("%-4s %-22s %4d s  %s" % ("ok" if passed else "FAIL", test, seconds, " | ".join(summary)), flush=True)
            if passed:
                state[test] = {"Fingerprint": prints[test], "PassedAt": time.strftime("%Y-%m-%d %H:%M"), "Seconds": round(seconds)}
            else:
                state.pop(test, None)
            STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    print("%s: %d run, %d skipped, %d s" % ("all passed" if ok else "FAILED", len(todo), len(tests) - len(todo), time.time() - started))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
