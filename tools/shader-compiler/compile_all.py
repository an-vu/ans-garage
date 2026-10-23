"""Vehicle-agnostic shader profiles for every shader in the v293 vehicle shader database.

Unlike profile_compiler.py (one export's material states and vertex layouts), this compiles every program for every
vertex declaration in the database:
  - profiles are keyed by the shader name hash (DJB2-xor of the lower-case asset name, as the database stores it);
  - every external parameter stays symbolic (the add-on specializes with each material's values), except the fixed
    static-state overrides (undamaged);
  - every material-bindable texture stays a texture (the add-on folds bound textures whose texels are uniform);
  - interpolants are named by declaration element ("Elem<i>.<k>"); the add-on maps elements to the section's usages.

usage: compile_all.py <out.json> [--jobs N] [--timeout S] [shader filter ...]
       compile_all.py --worker <shader hash> <cache.json>
Formulas only; no game bytecode or textures are written.
"""
import json
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from settings import path as setting  # noqa: E402

DATA = setting("shader_data_dir")  # game-derived inputs (disassembly, parsed shader database); never committed
CACHE = DATA / "agnostic-cache"


def djb(name):
    h = 5381
    for c in name.lower().encode():
        h = ((h * 33) ^ c) & 0xFFFFFFFF
    return h


def known_names():
    names = {}
    for f in ("vehicle-shader-programs.json",):
        for n in json.loads((DATA / f).read_text()):
            names[str(djb(n))] = n
    extra = DATA / "shader-names.json"
    if extra.is_file():
        for n in json.loads(extra.read_text()):
            names[str(djb(n))] = n
    return names


def worker(shader, out_path):
    sys.path.insert(0, str(HERE))
    import build_profile as bp
    import make_profiles as mp
    import profile_compiler as pc

    pc.AGNOSTIC = True
    bp.PROGRAMS_FILE = "all-shader-programs.json"
    programs = bp._cached("all-shader-programs.json")
    parsed = bp._cached("parsed.json")[0]
    pc.PARSED["p"] = parsed

    # Layouts: one synthetic usage tuple per database declaration (Pos at element 0, others by element and format).
    decl_formats = {}
    for d in parsed["Declarations"]:
        fmts = tuple(pc.FMT.get(x[0], str(x[0])) for x in d)
        usage = tuple("Pos" if i == 0 else "Elem%d:%s" % (i, f) for i, f in enumerate(fmts))
        decl_formats[usage] = fmts
    layouts = {tuple(zip(u, f)) for u, f in decl_formats.items()}

    ext_textures = set()
    for s in programs[shader]["Solutions"]:
        ext_textures |= {t["Name"] for t in parsed["Constants"][s["PSConstants"]]["ExternalTextures"]}
    static = {k.casefold() for k in mp.STATIC_UNDAMAGED}
    mp.overridden_params = lambda sh, states, ext: {v["Name"] for v in ext.values() if v["Name"].casefold() not in static}
    mp.bindings_for = lambda sh, states, root: {n: "image" for n in ext_textures}

    sols = Counter(s["PS"] for s in programs[shader]["Solutions"])
    gbuf, fwd = [], []
    for ps, count in sols.items():
        path = DATA / "asm" / (ps + ".asm")
        if not path.is_file():
            continue
        text = path.read_text()
        targets = len(re.findall(r"^; SV_Target\s+\d+\s+xyzw", text.split("define void")[0], re.M))
        if targets >= 4:
            gbuf.append((count, ps))
        elif targets == 2 and "dx.op.discard" not in text:
            fwd.append((count, ps))
    rep = {"Programs": len(sols), "GBufferPrograms": len(gbuf), "ForwardPrograms": len(fwd)}
    started = time.time()
    if gbuf:
        kind, entries = "gbuffer", pc.compile_entries(shader, sorted(gbuf, reverse=True), pc.compile_shader, None, None,
                                                       None, programs, parsed, layouts, rep)
    elif fwd:
        kind, entries = "forward_transmittance", pc.compile_entries(shader, sorted(fwd, reverse=True), pc.compile_forward,
                                                                    None, None, None, programs, parsed, layouts, rep)
    else:
        kind, entries = None, []
    for e in entries:
        e["Formats"] = [list(decl_formats[tuple(l)]) for l in e["Layouts"]]
        del e["Layouts"]
        e["Shader"] = shader
    # Declarations whose vertex programs are all constant stubs (skinned layouts) cannot be routed by element. For the
    # usage layouts seen in exported vehicles (known-layouts.json), compile usage-named entries with the unanimous
    # routing of the program's other known layouts (profile_compiler's original rule).
    stubs = [e for e in entries if any("constant stubs" in (x.get("Evidence") or "") for x in e.get("InputEvidence", []))]
    extra = []
    if stubs:
        known = {tuple(tuple(x) for x in l) for l in json.loads((DATA / "known-layouts.json").read_text())}
        fn = pc.compile_shader if kind == "gbuffer" else pc.compile_forward
        pc.AGNOSTIC, done = False, set()
        for e in stubs:
            e["StubVertexPrograms"] = True
            for fmts in e["Formats"]:
                for l in sorted(known):
                    usage = tuple(u for u, _ in l)
                    if [f for _, f in l] != fmts:
                        continue
                    for ps in e["Programs"]:
                        if (ps, usage) in done:
                            continue
                        done.add((ps, usage))
                        try:
                            prof = fn(shader, ps, None, None, None, programs, parsed, known, usage)[0]
                        except Exception as exc:
                            rep.setdefault("Errors", []).append({"PS": ps, "Layout": list(usage), "Error": repr(exc)})
                            continue
                        prof.update(Programs=[ps], Layouts=[list(usage)], SolutionCount=0, Shader=shader,
                                    Routing="vertex programs of this layout are constant stubs; unanimous routing of "
                                            "the program's other known vertex layouts (from exported vehicles)")
                        extra.append(prof)
        pc.AGNOSTIC = True
    entries += extra
    rep["StubLayoutEntries"] = len(extra)
    entries.sort(key=lambda e: -e["SolutionCount"])
    rep["Seconds"] = round(time.time() - started, 1)
    if not entries:
        rep["Status"] = "not_profiled"
        rep["Reason"] = "No program could be profiled" if (gbuf or fwd) else "No G-buffer or dual-source program"
    else:
        rep["Status"] = "profiled" if any(not e["Unresolved"] for e in entries) else "unresolved"
        rep["Entries"] = [{"Programs": e["Programs"], "Declarations": len(e.get("Formats", e.get("Layouts", []))), "Nodes": len(e["Nodes"]),
                           "Unresolved": e["Unresolved"][:4], "AssumedUsages": e["AssumedUsages"]} for e in entries]
    profile = {"Shader": shader, "Kind": kind, "Agnostic": True, "Entries": entries} if entries else None
    Path(out_path).write_text(json.dumps({"Profile": profile, "Report": rep}, separators=(",", ":")))


def main(argv):
    out = Path(argv[0])
    jobs, timeout, filters = 12, 3600, []
    i = 1
    while i < len(argv):
        if argv[i] == "--jobs":
            jobs, i = int(argv[i + 1]), i + 2
        elif argv[i] == "--timeout":
            timeout, i = int(argv[i + 1]), i + 2
        else:
            filters.append(argv[i])
            i += 1
    programs = json.loads((DATA / "all-shader-programs.json").read_text())
    names = known_names()
    shaders = [h for h in programs if not filters or any(f in h or f in names.get(h, "") for f in filters)]
    CACHE.mkdir(exist_ok=True)

    def run(h):
        path = CACHE / (h + ".json")
        if path.is_file():
            return h, "cached"
        t = time.time()
        try:
            r = subprocess.run([sys.executable, "-I", str(Path(__file__)), "--worker", h, str(path)],
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                path.write_text(json.dumps({"Profile": None, "Report": {"Status": "error", "Error": r.stderr[-2000:]}}))
        except subprocess.TimeoutExpired:
            path.write_text(json.dumps({"Profile": None, "Report": {"Status": "timeout", "Seconds": timeout}}))
        return h, "%.0fs" % (time.time() - t)

    with ThreadPoolExecutor(jobs) as pool:
        for n, (h, how) in enumerate(pool.map(run, shaders), 1):
            print("%d/%d %s %s %s" % (n, len(shaders), h, names.get(h, ""), how), flush=True)

    # States[solution][4] bit 9 separates the full and reduced programs of a pair; a frame capture of the game shows
    # light lenses drawn with the full one (bit 9 clear). Recorded per entry so the add-on can pick it.
    parsed = json.loads((DATA / "parsed.json").read_text())
    states = (parsed[0] if isinstance(parsed, list) else parsed)["States"]
    profiles, report = {}, {}
    for h in programs:
        path = CACHE / (h + ".json")
        if not path.is_file():
            continue
        r = json.loads(path.read_text())
        rep = r["Report"]
        if names.get(h):
            rep["Name"] = names[h]
        report[h] = rep
        if r["Profile"]:
            if names.get(h):
                r["Profile"]["Name"] = names[h]
            bit9 = {}
            for s in programs[h]["Solutions"]:
                bit9.setdefault(s["PS"], set()).add(bool(states[s["SolutionIndex"]][4] & 0x200))
            for e in r["Profile"]["Entries"]:
                e["StateBit9"] = sorted({b for ps in e["Programs"] for b in bit9.get(ps, ())})
            profiles[h] = r["Profile"]
    import profile_compiler as pc
    doc = {"Schema": 3, "Generator": "compile_all.py (DXC disassembly of the v293 vehicle shader database; symbolic "
                                     "evaluation with parameters symbolic; one entry per program/vertex-declaration result)",
           "DatabaseSHA256": pc.DB_SHA256, "Keys": "DJB2-xor hash of the lower-case shader asset name",
           "Profiles": profiles, "Report": report}
    out.write_text(json.dumps(doc, separators=(",", ":")))
    print("wrote", out, out.stat().st_size, Counter(r.get("Status") for r in report.values()))


if __name__ == "__main__":
    if sys.argv[1] == "--worker":
        worker(sys.argv[2], sys.argv[3])
    else:
        main(sys.argv[1:])
