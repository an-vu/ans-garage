import bpy,json,sys,hashlib
from pathlib import Path
from io_scene_fbx import parse_fbx
from collections import Counter
root=Path(__import__("os").environ["UNBOUND_VALIDATION_WORKSPACE"]).resolve()
sys.path.insert(0,str(root/'outputs/UnboundBatchExport/blender'))
import import_unbound_batch as importer
old=root/'outputs/Murcielago-Assembly'
new=root/'work/full-batch-0.4'
document=json.loads((new/'manifest.json').read_text())
checks=[]
vector_deltas={}
def check(name,ok):checks.append({'Check':name,'Passed':bool(ok)})
def freeze(e):
    def value(v):
        if isinstance(v,bytes):return ['bytes',v.hex()]
        if isinstance(v,(int,float,str)):return v
        return list(v)
    return [e.id.hex(),[value(v) for v in e.props],[freeze(c) for c in e.elems]]
def native(path):
    tree,_=parse_fbx.parse(str(path))
    objs=next(e for e in tree.elems if e.id==b'Objects')
    rows=[]
    names={e.props[0]:e.props[1].decode(errors='replace') for e in objs.elems if e.id in (b'Geometry',b'Model')}
    for e in objs.elems:
        if e.id in (b'Geometry',b'Model'):
            row=freeze(e);row[1]=row[1][1:];rows.append(row)
    links=next(e for e in tree.elems if e.id==b'Connections')
    connections=[]
    for c in links.elems:
        if c.props[0]==b'OO' and c.props[1] in names:
            connections.append([names[c.props[1]],names.get(c.props[2],'<root>')])
    return rows,sorted(connections)
def compare(a,b,path=(),vector=False):
    if isinstance(a,list) and isinstance(b,list):
        if len(a)!=len(b):return False
        if a and isinstance(a[0],str) and a[0] in (b'LayerElementNormal'.hex(),b'LayerElementTangent'.hex(),b'LayerElementBinormal'.hex()):
            path=path+(bytes.fromhex(a[0]).decode(),)
            vector=True
        return all(compare(x,y,path,vector) for x,y in zip(a,b))
    if vector and isinstance(a,float) and isinstance(b,float):
        delta=abs(a-b)
        label='/'.join(path)
        vector_deltas[label]=max(vector_deltas.get(label,0),delta)
        return delta<=1e-5
    return a==b
for mesh in document['Meshes']:
    before=native(old/mesh['Fbx']);after=native(new/mesh['Fbx'])
    check(mesh['Asset']+' native geometry/UV/model exact; tangent vectors within 1e-5',compare(before[0],after[0]))
    check(mesh['Asset']+' native hierarchy connections',before[1]==after[1])
check('Source inventory unchanged',{m['Id'] for m in document['Meshes']} ==
      {m['Id'] for m in json.loads((old/'manifest.json').read_text())['Meshes']})
oldmat=json.loads((old/'materials.json').read_text());newmat=json.loads((new/'materials.json').read_text())
check('DDS hashes unchanged',{t['ResourceId']:t['Sha256'] for t in oldmat['Textures']} ==
      {t['ResourceId']:t['Sha256'] for t in newmat['Textures']})
bpy.ops.wm.read_factory_settings(use_empty=True)
count,errors=importer.import_manifest(new/'manifest.json')
check('Fresh importer exported count',count==102)
check('Fresh importer has no errors',not errors)
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
check('Fresh source and assembly meshes',len(meshes)==593)
check('All fresh meshes have restored slots',all(o.data.materials and 'unbound_material_slot' in o for o in meshes))
check('All fresh faces have source indices',all(all(p.material_index==o['unbound_material_slot'] for p in o.data.polygons) for o in meshes))
check('Fresh assembly exists',sum(bool(c.get('unbound_assembly_path')) for c in bpy.context.scene.collection.children)==1)
rubber=[o for o in meshes if o.material_slots[o['unbound_material_slot']].material.get('unbound_family')=='Rubber']
check('Four fresh assembled rubber tires',len([o for o in rubber if o.get('unbound_assembled')])==4)
for tex in newmat['Textures']:
    check('Fresh DDS bytes '+tex['ResourceId'],hashlib.sha256((new/tex['Path']).read_bytes()).hexdigest()==tex['Sha256'])
result={'Passed':sum(c['Passed'] for c in checks),'Failed':[c for c in checks if not c['Passed']],
        'ImporterErrors':errors,'Checks':checks,'NativeVectorMaxComponentDelta':vector_deltas,
        'ComparisonPolicy':'Geometry, UVs, colors, model properties and topology exact; native decoded normal/tangent/binormal components tolerate 1e-5. Original blend attributes are checked exactly in material-validation.json.'}
(old/'fresh-pipeline-validation.json').write_text(json.dumps(result,indent=2))
print('FRESH PIPELINE',result['Passed'],'FAILED',result['Failed'][:10])
if result['Failed']:raise AssertionError('Fresh pipeline verification failed')
