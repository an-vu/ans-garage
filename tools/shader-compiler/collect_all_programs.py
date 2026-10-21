"""All shader records in the parsed v293 vehicle shader DB, keyed by name hash (read-only)."""
import json, struct, sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from settings import path as setting  # noqa: E402
DATA = setting("shader_data_dir")
p = json.loads((DATA / "parsed.json").read_text())[0]
result, allbc = {}, set()
for t in p["Shaders"]:
    recs = []
    for i in t["Solutions"]:
        s = p["Solutions"][i]
        if s["PS"] == 0xffffffffffffffff:
            continue
        ps, vs = p["Permutations"]["Pixel"][s["PS"]], p["Permutations"]["Vertex"][s["VS"]]
        recs.append({"SolutionIndex": i, "PS": ps["Bytecode"], "VS": vs["Bytecode"], "PSConstants": s["PSConstants"],
                     "VSConstants": s["VSConstants"], "Declaration": p["Declarations"][p["DeclarationIndices"][s["VS"]]]})
        allbc.update((ps["Bytecode"], vs["Bytecode"]))
    result[str(t["Hash"])] = {"Hash": t["Hash"], "Textures": t["Textures"],
                              "Streaming": [[str(uuid.UUID(bytes_le=struct.pack("<4I", *e[:4])))] + list(e[4:]) for e in t["ExternalTextures"]],
                              "Solutions": recs}
(DATA / "all-shader-programs.json").write_text(json.dumps(result))
have = {f.stem for f in (DATA / "asm").glob("*.asm")}
missing = sorted(allbc - have)
(DATA / "bytecode-filter-all.txt").write_text("|".join(missing))
print("shaders", len(result), "programs", len(allbc), "already disassembled", len(allbc & have), "missing", len(missing))
