import bpy, json, sys
from pathlib import Path
from collections import Counter
from mathutils import Vector
from io_scene_fbx import parse_fbx

root=Path(__import__("os").environ["UNBOUND_VALIDATION_WORKSPACE"]).resolve()
out=root/'outputs/Murcielago-Assembly'
d=json.loads((out/'materials.json').read_text(encoding='utf-8-sig'))
m=next(m for m in d['Meshes'] if m['Asset'].endswith('fendersr_seta_mesh'))
tree,version=parse_fbx.parse(str(out/m['Fbx']))
objects=next(e for e in tree.elems if e.id==b'Objects')
report={'Asset':m['Asset'],'Fbx':m['Fbx'],'FbxVersion':version,'Sections':[]}
for e in objects.elems:
    if e.id!=b'Geometry':continue
    kids={x.id:x for x in e.elems}
    if b'PolygonVertexIndex' not in kids:continue
    vertices=kids[b'Vertices'].props[0]
    vertices=[Vector(vertices[i:i+3]) for i in range(0,len(vertices),3)]
    poly=[]; faces=[]
    for index in kids[b'PolygonVertexIndex'].props[0]:
        poly.append(index if index>=0 else ~index)
        if index<0:faces.append(poly);poly=[]
    degenerates=[]
    for ordinal,p in enumerate(faces):
        if len(set(p))<3:
            degenerates.append({'Polygon':ordinal,'Indices':p,'Reason':'repeated_vertex_indices'})
        elif len(p)==3 and (vertices[p[1]]-vertices[p[0]]).cross(vertices[p[2]]-vertices[p[0]]).length==0:
            degenerates.append({'Polygon':ordinal,'Indices':p,'Reason':'zero_area_distinct_indices'})
    report['Sections'].append({'GeometryId':e.props[0],'Name':e.props[1].decode(errors='replace').split('\x00')[0],
        'FbxPolygons':len(faces),'RepeatedIndexPolygons':sum(len(set(p))<3 for p in faces),
        'Degenerates':degenerates,'SourcePolygons':faces})
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(out/m['Fbx']),use_anim=False,automatic_bone_orientation=False)
for s in report['Sections']:
    o=next(o for o in bpy.data.objects if o.type=='MESH' and o.name==s['Name'])
    got=Counter(tuple(p.vertices) for p in o.data.polygons)
    expected=Counter(tuple(p) for p in s['SourcePolygons'])
    s['BlenderPolygons']=len(o.data.polygons)
    s['MissingIndexSequences']=[list(p) for p in (expected-got).elements()]
    s['AddedIndexSequences']=[list(p) for p in (got-expected).elements()]
    del s['SourcePolygons']
(out/'rear-fender-audit.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
