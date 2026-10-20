import collections,hashlib,json,struct,re
from pathlib import Path
root=Path("outputs/Murcielago-Materials")
m=json.loads((root/"materials.json").read_text(encoding="utf-8-sig"))
blend=json.loads(Path("work/blend-audit.json").read_text())
nodes={n["Id"]:n for n in m["Nodes"]}
tex={t["ResourceId"]:t for t in m["Textures"]}
checks=[];failures=[]
def check(name,ok,details=None):
    checks.append({"check":name,"passed":bool(ok),"details":details})
    if not ok:failures.append(name)
check("run completed",m["Status"]=="completed")
check("no extraction issues",not m["Issues"])
check("unique texture resources",len(tex)==len(m["Textures"]))
for t in m["Textures"]:
    data=(root/t["Path"]).read_bytes()
    start=148 if data[84:88]==b"DX10" else 128
    raw=(root/t["RawData"]).read_bytes()
    check("texture "+t["ResourceId"],data[:4]==b"DDS " and data[start:]==raw and hashlib.sha256(data).hexdigest()==t["Sha256"],
          {"format":t["Format"],"source":t["Aliases"][0]["Asset"],"bytes":len(data)})
by_mesh=collections.defaultdict(list)
for obj in blend["meshes"]:by_mesh[obj["unbound_mesh_id"]].append(obj)
assignments=0
for mesh in m["Meshes"]:
    slots={s["Index"]:s["Source"]["Node"] for s in mesh["Slots"]}
    sections=[s for s in mesh["Sections"] if s["Renderable"]]
    b=by_mesh[mesh["MeshId"]]
    check("geometry mapping "+mesh["MeshId"],
          len(b)==len(sections) and sum(o["polygons"] for o in b)==sum(s["PrimitiveCount"] for s in sections),
          {"asset":mesh["Asset"],"source_sections":len(sections),"blend_objects":len(b)})
    check("source slot references "+mesh["MeshId"],all(s["MaterialSlot"] in slots and slots[s["MaterialSlot"]] in nodes for s in sections))
    for v in mesh["Variants"]:
        for a in v["Assignments"]:
            assignments+=1
            check("variant mapping "+mesh["MeshId"]+"/"+str(v["Row"])+"/"+str(assignments),
                  bool(a["Slots"]) and all(slots[i]==a["Material"]["Node"] for i in a["Slots"]) and
                  (a["Override"]["Kind"]=="Null" or a["Override"].get("Node") in nodes))
def value(obj):
    return obj.get("Value") if isinstance(obj,dict) else obj
def shader_of(nodeid):
    n=nodes[nodeid];shader=n.get("Raw",{}).get("Shader",{})
    target=shader.get("Shader",{}).get("Node")
    return nodes.get(target,{}).get("Asset")
categories={}
selectors={
 "body_paint":lambda mesh,s:"carpaint" in s["Name"].lower() and "carbon" not in s["Name"].lower(),
 "glass":lambda mesh,s:"glass" in s["Name"].lower(),
 "headlights":lambda mesh,s:"headlight" in mesh["Asset"].lower(),
 "taillights":lambda mesh,s:"taillight" in mesh["Asset"].lower(),
 "carbon_fiber":lambda mesh,s:"carbon" in s["Name"].lower(),
 "plastic":lambda mesh,s:"plastic" in s["Name"].lower(),
 "rubber":lambda mesh,s:bool(re.search("rubber|tyre|tire",s["Name"],re.I)),
}
for label,test in selectors.items():
    hits=[]
    for mesh in m["Meshes"]:
        for s in mesh["Sections"]:
            if s["Renderable"] and test(mesh,s):
                slot=mesh["Slots"][s["MaterialSlot"]]
                hits.append({"mesh":mesh["Asset"],"section":s["Name"],"slot":s["MaterialSlot"],
                             "material_node":slot["Source"]["Node"],"shader":shader_of(slot["Source"]["Node"])})
    categories[label]={"basis":"Source section/asset names only; not a rendered appearance assertion","count":len(hits),"examples":hits[:3]}
bindings=[]
for n in m["Nodes"]:
    raw=n.get("Raw",{})
    shader=raw.get("Shader") or raw.get("ShaderPreset") or {}
    for p in shader.get("TextureParameters",[]):
        target=nodes.get(p.get("Value",{}).get("Node"),{})
        bindings.append({"owner":n["Id"],"parameter":value(p.get("ParameterName")),"texture":target.get("Asset"),"resource":target.get("TextureResource")})
report={"checks_passed":sum(c["passed"] for c in checks),"checks_failed":len(failures),"failures":failures,
 "mesh_assets":len(m["Meshes"]),"renderable_sections":sum(s["Renderable"] for mesh in m["Meshes"] for s in mesh["Sections"]),
 "base_slots":sum(len(mesh["Slots"]) for mesh in m["Meshes"]),"variant_rows":sum(len(mesh["Variants"]) for mesh in m["Meshes"]),
 "variant_assignments":assignments,"unique_textures":len(tex),"types":dict(collections.Counter(n["Type"] for n in m["Nodes"])),
 "formats":dict(collections.Counter(t["Format"] for t in m["Textures"])),"categories":categories,
 "texture_parameter_names":sorted(set(b["parameter"] for b in bindings)),
 "blender_audit":{"version":blend["blender_version"],"objects":len(blend["meshes"]),"material_slots":sum(len(o["slots"]) for o in blend["meshes"])},
 "limitations":["Compiled shader resources and global runtime texture bindings not decoded.","No guessed packed-channel assignments.","Blender shader reconstruction and rendered visual matching not performed.","Section names may repeat; this audit compares counts/triangles by mesh ID, not ambiguous object-name slot assignment."],
 "checks":checks}
(root/"validation.json").write_text(json.dumps(report,indent=2))
(root/"texture-bindings.json").write_text(json.dumps(bindings,indent=2))
print(json.dumps({k:v for k,v in report.items() if k not in ("checks","categories")},indent=2))
assert not failures
