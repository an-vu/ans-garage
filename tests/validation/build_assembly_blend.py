import bpy,json,hashlib,importlib.util,sys,math
from pathlib import Path
from mathutils import Matrix,Vector
import numpy as np
workspace=Path(__import__("os").environ["UNBOUND_VALIDATION_WORKSPACE"]).resolve()
out=workspace/"outputs/Murcielago-Assembly"
spec=importlib.util.spec_from_file_location("unbound_assembly",workspace/"outputs/UnboundBatchExport/blender/unbound_assembly.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
manifest=json.loads((out/"manifest.json").read_text())
assembly=json.loads((out/"assembly.json").read_text())

def mesh_digest(mesh):
    h=hashlib.sha256()
    h.update(str((len(mesh.vertices),len(mesh.edges),len(mesh.polygons),len(mesh.loops))).encode())
    for attr in mesh.attributes:
        h.update(str((attr.name,attr.domain,attr.data_type,len(attr.data))).encode())
        if not attr.data:continue
        first=attr.data[0]
        prop=next((p for p in first.bl_rna.properties if p.identifier not in ("rna_type",) and p.type in ("INT","FLOAT","BOOLEAN")),None)
        if prop is None:raise RuntimeError("Unsupported audit attribute "+attr.name)
        count=max(prop.array_length,1)
        buf=np.empty(len(attr.data)*count,dtype=np.float64 if prop.type=="FLOAT" else np.int32)
        attr.data.foreach_get(prop.identifier,buf)
        h.update(buf.tobytes())
    normal=np.empty(len(mesh.corner_normals)*3,dtype=np.float32)
    mesh.corner_normals.foreach_get("vector",normal);h.update(normal.tobytes())
    return h.hexdigest()

checks=[]
def check(name,ok,details=None):
    checks.append({"Check":name,"Passed":bool(ok),"Details":details})

# The baseline has excluded variants whose cached matrix_world is identity until
# evaluated. Include all source layers for the comparison, without changing any
# object's transform channels. Otherwise a stale cache looks like a 90-degree edit.
def include_sources(layer):
    layer.exclude=False
    layer.hide_viewport=False
    layer.collection.hide_viewport=False
    for child in layer.children:include_sources(child)
include_sources(bpy.context.view_layer.layer_collection)
bpy.context.view_layer.update()
before_objects={o.name:{"matrix":o.matrix_world.copy(),"parent":o.parent,"data":o.data,"mesh_id":o.get("unbound_mesh_id"),
                       "weights":[[(g.group,g.weight) for g in v.groups] for v in o.data.vertices] if o.type=="MESH" else None}
                for o in bpy.data.objects}
before_meshes={m.name:mesh_digest(m) for m in bpy.data.meshes}
before_eval={}
dg=bpy.context.evaluated_depsgraph_get()
for o in bpy.data.objects:
    if o.type=="MESH":
        ev=o.evaluated_get(dg)
        before_eval[o.name]=np.array([ev.matrix_world@v.co for v in ev.data.vertices],dtype=np.float64)

ids={o.get("unbound_mesh_id") for o in bpy.data.objects}
extra=[]
for record in manifest["Meshes"]:
    if record["Status"]!="exported" or record["Id"] in ids:continue
    before=set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(out/record["Fbx"]),global_scale=1.0,use_manual_orientation=False,
                            bake_space_transform=False,use_anim=False,automatic_bone_orientation=False,
                            ignore_leaf_bones=False,use_prepost_rot=True)
    added=set(bpy.data.objects)-before
    for o in added:o["unbound_mesh_id"]=record["Id"]
    extra.append(record["Asset"])

root,diagnostics=module.assemble_existing(out/"manifest.json")
bpy.context.view_layer.update()
check("four authored wheel assemblies",set(c.name for c in root.children["Wheels"].children)=={w["Name"] for w in assembly["Wheels"]})
conversion=Matrix(json.loads(root["fbx_to_blender_matrix"]))
for wheel in assembly["Wheels"]:
    control=next(o for o in bpy.data.objects if o.get("source_wheel_node")==wheel["WheelComponent"])
    expected=conversion@Vector(wheel["Transform"][9:])
    check("wheel "+wheel["Name"]+" authored center",(control.matrix_world.translation-expected).length<1e-6,
          {"Expected":list(expected),"Actual":list(control.matrix_world.translation)})
    c=root.children["Wheels"].children[wheel["Name"]]
    rim=[s for s in c.children if s.name.startswith("Rim")]
    tire=[s for s in c.children if s.name.startswith("Tire")]
    check("wheel "+wheel["Name"]+" rim and tire present",len(rim)==1 and len(tire)==1)
    for part in rim+tire:
        check("wheel "+wheel["Name"]+" "+part.name+" source identity",all(o.get("unbound_mesh_id") for o in part.all_objects))
        if part in tire:
            pts=[o.matrix_world@v.co for o in part.all_objects if o.type=="MESH" for v in o.data.vertices]
            dimensions=[max(p[i] for p in pts)-min(p[i] for p in pts) for i in range(3)]
            check("wheel "+wheel["Name"]+" tire finite and nonzero",all(math.isfinite(x) and x>0 for x in dimensions),dimensions)
    badges=[o for part in rim for o in part.all_objects if o.type=="MESH" and "badge" in o["unbound_original_name"].lower()]
    if badges:
        outward=1 if wheel["Facing"]["Left"] else -1
        check("wheel "+wheel["Name"]+" badge faces outward",
              all((sum((o.matrix_world@v.co).x for v in o.data.vertices)/len(o.data.vertices)-expected.x)*outward>0 for o in badges))

for name,baseline in before_objects.items():
    o=bpy.data.objects.get(name)
    check("original object retained "+name,o is not None)
    if o is None:continue
    error=max(abs(o.matrix_world[r][c]-baseline["matrix"][r][c]) for r in range(4) for c in range(4))
    check("original transform "+name,error<1e-7,{"MaxError":error,"Before":[list(r) for r in baseline["matrix"]],"After":[list(r) for r in o.matrix_world]} if error>=1e-7 else None)
    check("original parent "+name,o.parent==baseline["parent"])
    if o.type=="MESH":
        check("original mesh data "+name,o.data==baseline["data"] and mesh_digest(o.data)==before_meshes[o.data.name])
        check("original vertex groups "+name,baseline["weights"]==[[(g.group,g.weight) for g in v.groups] for v in o.data.vertices])

wheel_meshids={o.get("unbound_mesh_id") for o in root.children["Wheels"].all_objects if o.type=="MESH"}
dg=bpy.context.evaluated_depsgraph_get()
compared=0
for o in root.all_objects:
    if o.type!="MESH" or not o.get("unbound_assembled"):continue
    original=o["unbound_original_name"]
    if original in before_objects:
        check("clone shares source geometry "+o.name,o.data==before_objects[original]["data"])
        if o.get("unbound_mesh_id") not in wheel_meshids:
            ev=o.evaluated_get(dg);now=np.array([ev.matrix_world@v.co for v in ev.data.vertices])
            expected=before_eval[original]
            error=float(np.max(np.abs(now-expected))) if now.shape==expected.shape else -1
            check("body evaluated placement "+o.name,now.shape==expected.shape and error<2e-5,{"MaxError":error,"Source":original} if error>=2e-5 else None)
            compared+=1
check("body sections compared",compared>250,compared)

presets=json.loads(root["unbound_presets_json"])
state_before={o.name:[list(r) for r in o.matrix_world] for o in root.all_objects}
for preset in presets:
    module.apply_preset(root,preset)
    for c in root.children:
        if c.get("unbound_choice_group"):
            check("preset exclusive "+preset+"/"+c.name,sum(not v.hide_viewport for v in c.children if "unbound_option" in v)==1)
module.apply_preset(root,"Stock")
for c in root.children:
    if not c.get("unbound_choice_group"):continue
    for variant in c.children:
        if "unbound_option" in variant:
            module.set_variant(root,c["unbound_choice_group"],variant["unbound_option"])
            check("variant switch "+variant.name,sum(not v.hide_viewport for v in c.children if "unbound_option" in v)==1)
module.apply_preset(root,"Stock")
bpy.context.view_layer.update()
check("variant switches preserve all transforms",all(state_before[o.name]==[list(r) for r in o.matrix_world] for o in root.all_objects))
try:
    module.assemble_existing(out/"manifest.json")
    check("duplicate assembly rejected",False)
except ValueError as e:
    check("duplicate assembly rejected","already present" in str(e))

# Test registration and operators; does not claim a human UI click test.
spec2=importlib.util.spec_from_file_location("batch_importer",workspace/"outputs/UnboundBatchExport/blender/import_unbound_batch.py")
addon=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(addon);addon.register()
result=bpy.ops.object.unbound_variant(root=root.name,preset="Stock")
check("Blender variant operator",result=={"FINISHED"})
addon.unregister()
report={"Blender":bpy.app.version_string,"ChecksPassed":sum(c["Passed"] for c in checks),
        "ChecksFailed":sum(not c["Passed"] for c in checks),"Checks":checks,"AdditionalSourceMeshes":extra,
        "Diagnostics":diagnostics,"VerificationScope":"Original and assembled geometry/attributes and authored rest transforms. Runtime in-game suspension/shader sizing not reproduced."}
(out/"blender-validation.json").write_text(json.dumps(report,indent=2))
print("VALIDATION",report["ChecksPassed"],"passed",report["ChecksFailed"],"failed")
if report["ChecksFailed"]:
    print("FAILURES",[c for c in checks if not c["Passed"]][:20])
    raise RuntimeError("Assembly validation failed")
bpy.ops.wm.save_as_mainfile(filepath=str(out/"merci-assembled.blend"))
