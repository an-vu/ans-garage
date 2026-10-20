import bpy,sys,json,hashlib
import numpy as np
from pathlib import Path
root=Path(__import__("os").environ["UNBOUND_VALIDATION_WORKSPACE"]).resolve()
sys.path.insert(0,str(root/'outputs/UnboundBatchExport/blender'))
import unbound_materials as m
out=root/'outputs/Murcielago-Assembly'
def digest(mesh):
    h=hashlib.sha256()
    h.update(str((len(mesh.vertices),len(mesh.edges),len(mesh.polygons),len(mesh.loops))).encode())
    for attr in mesh.attributes:
        if attr.name in ("material_index", ".material_index"):continue
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

baseline={o.name:{"data":o.data,"transform":[list(r) for r in o.matrix_basis],"parent":o.parent,
                 "groups":[[(g.group,g.weight) for g in v.groups] for v in o.data.vertices]}
          for o in bpy.context.scene.objects if o.type=='MESH'}
hashes={o.data.name:digest(o.data) for o in bpy.context.scene.objects if o.type=='MESH'}
report=m.reconstruct(out/'manifest.json')
print('ASSIGNED',len(report['Objects']),'MATERIALS',len(report['Materials']))
print('FAILURES',[i for i in report['Issues'] if i.get('Severity')=='assignment_failed'])
(out/'material-reconstruction.json').write_text(json.dumps(report,indent=2))
checks=[]
def check(label,condition):checks.append({'Check':label,'Passed':bool(condition)})
check('No assignment failures',not any(x.get('Severity')=='assignment_failed' for x in report['Issues']))
check('Every source/assembly mesh assigned',len(report['Objects'])==len(baseline))
after_hashes={mesh.name:digest(mesh) for mesh in set(b['data'] for b in baseline.values())}
for name,b in baseline.items():
    o=bpy.data.objects[name]
    check(name+' geometry attributes',after_hashes[o.data.name]==hashes[o.data.name])
    check(name+' shared data and hierarchy',o.data==b['data'] and o.parent==b['parent'] and [list(r) for r in o.matrix_basis]==b['transform'])
    check(name+' vertex groups',[[(g.group,g.weight) for g in v.groups] for v in o.data.vertices]==b['groups'])
    if 'unbound_material_slot' in o:
        check(name+' face assignments',all(p.material_index==o['unbound_material_slot'] for p in o.data.polygons))
        check(name+' material identity',o.material_slots[o['unbound_material_slot']].material['unbound_material_node']==o['unbound_material_source'])
for mat in bpy.data.materials:
    if mat.get('unbound_state_key'):
        check(mat.name+' no guessed surface',all(not n.inputs['Surface'].is_linked for n in mat.node_tree.nodes if n.type=='OUTPUT_MATERIAL'))
        check(mat.name+' no guessed UV',all(not n.inputs['Vector'].is_linked for n in mat.node_tree.nodes if n.type=='TEX_IMAGE'))
rubber=[o for o in bpy.context.scene.objects if o.type=='MESH' and 'unbound_material_slot' in o and
        o.material_slots[o['unbound_material_slot']].material.get('unbound_family')=='Rubber']
check('Four assembled rubber tire objects',len([o for o in rubber if o.get('unbound_assembled')])==4)
check('Packed tire channels recovered',any(b.get('Channels',{}).get('A')=='Smoothness' for r in report['Materials'] for b in r['State']['TextureBindings'] if b.get('Channels')))
import import_unbound_batch as importer
importer.register()
check('Material importer operator registered',hasattr(bpy.ops.import_scene,'unbound_materials'))
check('Material variant operator registered',hasattr(bpy.ops.object,'unbound_material_variant'))
resolver=m.Resolver(json.loads((out/'materials.json').read_text()))
target=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.visible_get() and
            any(v['Hash']!='00000000' for v in resolver.meshes[o['unbound_mesh_id']]['Variants']))
record=resolver.meshes[target['unbound_mesh_id']]
row=next(v for v in record['Variants'] if v['Hash']!='00000000')
shared=next(o for o in bpy.context.scene.objects if o!=target and o.type=='MESH' and o.data==target.data)
prior=[s.material for s in target.material_slots]
other_prior=[s.material for s in shared.material_slots]
uv_prior=target['unbound_texture_uv_json']
indices=[p.material_index for p in target.data.polygons]
bpy.ops.object.select_all(action='DESELECT')
target.select_set(True)
bpy.context.view_layer.objects.active=target
status=bpy.ops.object.unbound_material_variant(database_guid=row['DatabaseGuid'],row=row['Row'])
check('Source material row operator executed',status=={'FINISHED'})
check('Source row changed only selected instance',[s.material for s in shared.material_slots]==other_prior)
check('Source row retained per-face indices',[p.material_index for p in target.data.polygons]==indices)
check('Source row retained shared mesh data',target.data==shared.data)
for s,mat in zip(target.material_slots,prior):s.material=mat
target['unbound_texture_uv_json']=uv_prior
del target['unbound_active_material_variant']
importer.unregister()
check('UV fallback never connected',all(not n.inputs['Vector'].is_linked for mat in bpy.data.materials
      if mat.get('unbound_state_key') for n in mat.node_tree.nodes if n.type=='TEX_IMAGE'))
summary={'Passed':sum(c['Passed'] for c in checks),'Failed':[c for c in checks if not c['Passed']],
         'RubberObjects':[o.name for o in rubber],'Checks':checks}
(out/'material-validation.json').write_text(json.dumps(summary,indent=2))
print('VALIDATION',summary['Passed'],'FAILED',summary['Failed'][:12])
if summary['Failed']:raise AssertionError('Validation failed; did not save scene')
for im in bpy.data.images:
    if im.get('unbound_resource_id') and im.size[0]>0:
        try:im.pack()
        except Exception as ex:print('IMAGE PACK FAILED',im.name,str(ex))
bpy.ops.wm.save_as_mainfile(filepath=str(out/'merci-material-slots.blend'))
