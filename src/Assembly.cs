using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using Frosty.Core;
using Frosty.Core.Attributes;
using Frosty.Core.Windows;
using FrostySdk.Ebx;
using FrostySdk.IO;
using FrostySdk.Managers.Entries;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

[assembly: RegisterMenuExtension(typeof(UnboundBatchExport.AssemblyMenu))]
namespace UnboundBatchExport
{
    public sealed class AssemblyMenu : MenuExtension
    {
        public override string TopLevelMenuName { get { return "Tools"; } }
        public override string MenuItemName { get { return "Unbound assembly for existing export..."; } }
        public override RelayCommand MenuItemClicked { get { return new RelayCommand(o => {
            try {
                if(!FrostySdk.ProfilesLibrary.IsLoaded(FrostySdk.ProfileVersion.NeedForSpeedUnbound)) throw new InvalidOperationException("Load NFS Unbound first.");
                using(var dialog=new System.Windows.Forms.OpenFileDialog {Filter="Batch manifest|manifest.json",Title="Select existing export manifest"}) {
                    if(dialog.ShowDialog()!=System.Windows.Forms.DialogResult.OK)return;
                    string folder=Path.GetDirectoryName(dialog.FileName);
                    var manifest=JsonConvert.DeserializeObject<Manifest>(File.ReadAllText(dialog.FileName));
                    if(manifest==null || manifest.Schema!=1)throw new InvalidDataException("Unsupported manifest.");
                    var batch=new Batch(manifest.Scope,"",folder);
                    batch.Manifest.Meshes.AddRange(manifest.Meshes);
                    var assembly=new AssemblyRun(batch.Manifest,folder);
                    FrostyTaskWindow.Show("Vehicle assembly","Reading vehicle blueprint",task=> {
                        try {
                            assembly.Run();
                            foreach(var mesh in batch.Manifest.Meshes.Where(m=>m.Status=="pending").ToArray()) {
                                if(assembly.Cancel)break;
                                batch.ExportAdditional(mesh,task);
                            }
                            // Keep the user's geometry manifest and its statuses; only append newly resolved meshes.
                            foreach(var mesh in batch.Manifest.Meshes.Where(m=>!manifest.Meshes.Any(old=>old.Id==m.Id)))
                                manifest.Meshes.Add(mesh);
                            var materials=new MaterialRun(folder,manifest.Scope);
                            foreach(var mesh in manifest.Meshes) {if(assembly.Cancel){materials.Cancel=true;break;}materials.Process(mesh);}
                            materials.Save(true);
                            MaterialRun.WriteJson(dialog.FileName,JObject.FromObject(manifest));
                        } catch(Exception ex) {assembly.Issue("run",ex.Message);}
                        finally {assembly.Save();}
                    },true,task=>assembly.Cancel=true);
                    System.Windows.Forms.MessageBox.Show("Assembly data saved. Review assembly.json and assembly.log.\n"+folder,"Unbound assembly");
                }
            } catch(Exception ex) {System.Windows.Forms.MessageBox.Show(ex.Message,"Unbound assembly");}
        }); } }
    }

    // Reads authored relationships. No vehicle-specific coordinates or item IDs are embedded.
    public sealed class AssemblyRun
    {
        public volatile bool Cancel;
        public Func<bool> CancellationRequested;
        private bool IsCancelled {get {return Cancel || (CancellationRequested!=null && CancellationRequested());}}
        public readonly JObject Document;
        private readonly Manifest manifest;
        private readonly string output;
        private readonly List<EbxAssetEntry> entries;
        private readonly Dictionary<Guid,EbxAsset> cache=new Dictionary<Guid,EbxAsset>();
        private readonly Dictionary<string,JObject> captured=new Dictionary<string,JObject>();
        private readonly Dictionary<Guid,Tuple<EbxAssetEntry,object>> blueprints=new Dictionary<Guid,Tuple<EbxAssetEntry,object>>();
        private readonly JArray nodes=new JArray(),issues=new JArray(),components=new JArray(),items=new JArray(),wheels=new JArray(),meshUses=new JArray();
        private readonly HashSet<Guid> variantDbs=new HashSet<Guid>();
        public AssemblyRun(Manifest source,string directory)
        {
            manifest=source;output=directory;entries=App.AssetManager.EnumerateEbx().ToList();
            Document=new JObject {{"Schema",1},{"PluginVersion","0.4.0"},{"Scope",source.Scope},{"CreatedUtc",DateTime.UtcNow.ToString("o")},
                {"Nodes",nodes},{"Components",components},{"Items",items},{"Wheels",wheels},{"MeshUses",meshUses},{"Issues",issues},
                {"CoordinateSystem","Frostbite authored XYZ, Y up. Matrices are right/up/forward/translation vectors; meters."},
                {"Policy","Source graph, rest placement and explicit item references. Runtime suspension simulation, shader deformation and arbitrary compatibility rules are not evaluated."}};
        }
        public void Issue(string path,string message) {issues.Add(new JObject {{"Path",path},{"Message",message}});}
        private EbxAsset Load(Guid id) {EbxAsset a;if(!cache.TryGetValue(id,out a)){var e=App.AssetManager.GetEbxEntry(id);if(e==null)throw new InvalidDataException("Missing EBX "+id);a=App.AssetManager.GetEbx(e);cache[id]=a;}return a;}
        private object Resolve(object value) {if(!(value is PointerRef))throw new InvalidDataException("Expected PointerRef.");return Batch.Resolve((PointerRef)value,Load);}
        private static Guid Owner(object value,Guid owner) {var p=(PointerRef)value;return p.Type==PointerRefType.External?p.External.FileGuid:owner;}
        private static IEnumerable<object> List(object obj,string field) {var list=Batch.Get(obj,field) as IEnumerable;return list==null?Enumerable.Empty<object>():list.Cast<object>();}
        private static Guid ObjectGuid(object obj) {return ((AssetClassGuid)obj.GetType().GetMethod("GetInstanceGuid",Type.EmptyTypes).Invoke(obj,null)).ExportedGuid;}
        public static double[] Matrix(object t)
        {
            if(t==null)throw new InvalidDataException("Missing authored transform.");
            var values=new List<double>();
            foreach(string basis in new[]{"right","up","forward","trans"}) {
                object v=Batch.Get(t,basis);if(v==null)throw new InvalidDataException("Missing matrix vector "+basis);
                foreach(string axis in new[]{"x","y","z"}) {
                    double x=Convert.ToDouble(Batch.Get(v,axis));
                    if(Double.IsNaN(x)||Double.IsInfinity(x))throw new InvalidDataException("Nonfinite authored transform.");
                    values.Add(x);
                }
            }
            return values.ToArray();
        }
        public JToken Raw(object obj,Guid owner,int depth=0)
        {
            if(obj==null)return JValue.CreateNull();
            if(depth>24) {Issue(owner.ToString(),"Raw nesting limit reached.");return new JObject {{"Truncated",true}};}
            if(obj is PointerRef) {
                var p=(PointerRef)obj;var entry=p.Type==PointerRefType.External?App.AssetManager.GetEbxEntry(p.External.FileGuid):null;
                var r=new JObject {{"Kind",p.Type.ToString()},{"FileGuid",p.Type==PointerRefType.External?p.External.FileGuid:owner},{"ClassGuid",p.External.ClassGuid},{"Asset",entry==null?null:entry.Name}};
                if(p.Type==PointerRefType.Internal)r["Node"]=MaterialRun.ObjectKey(owner,p.Internal);
                else if(p.Type==PointerRefType.External)r["Node"]=p.External.FileGuid.ToString("N")+":"+p.External.ClassGuid.ToString("N");
                return r;
            }
            if(obj is ResourceRef)return new JValue(((ulong)(ResourceRef)obj).ToString("x16"));
            var type=obj.GetType();
            if(type==typeof(Guid)||type==typeof(string)||type.IsPrimitive||type==typeof(decimal))return JToken.FromObject(obj);
            if(type.IsEnum)return new JObject {{"Name",obj.ToString()},{"Numeric",Convert.ToInt64(obj)}};
            if(type.Name=="CString"||type.Name=="FileRef")return new JValue(obj.ToString());
            if(type.Name=="LinearTransform")return new JObject {{"Basis",new JArray(Matrix(obj))}};
            if(obj is IEnumerable) {var array=new JArray();int count=0;foreach(var v in (IEnumerable)obj){if(count++>=100000){Issue(owner.ToString(),"Raw collection limit reached.");break;}array.Add(Raw(v,owner,depth+1));}return array;}
            var row=new JObject {{"Type",type.Name}};
            foreach(var prop in type.GetProperties().Where(p=>p.GetIndexParameters().Length==0))
                try {row[prop.Name]=Raw(prop.GetValue(obj,null),owner,depth+1);}catch(Exception ex){row[prop.Name]=new JObject {{"Error",ex.Message}};Issue(prop.Name,ex.Message);}
            foreach(var f in type.GetFields())row[f.Name]=Raw(f.GetValue(obj),owner,depth+1);
            return row;
        }
        private string Capture(Guid owner,object obj)
        {
            string key=MaterialRun.ObjectKey(owner,obj);
            if(!captured.ContainsKey(key)) {
                var e=App.AssetManager.GetEbxEntry(owner);
                var node=new JObject {{"Id",key},{"FileGuid",owner},{"ClassGuid",ObjectGuid(obj)},{"Asset",e==null?null:e.Name},{"Type",obj.GetType().Name},{"Raw",Raw(obj,owner)}};
                captured[key]=node;nodes.Add(node);
            }
            return key;
        }
        private JObject Facing(object tag,Guid owner)
        {
            if(!(tag is PointerRef)||((PointerRef)tag).Type==PointerRefType.Null)return null;
            object obj=Resolve(tag);
            if(obj.GetType().Name!="MeshCustomizationTagWithFacing")return null;
            bool front=Convert.ToBoolean(Batch.Get(obj,"Front")),left=Convert.ToBoolean(Batch.Get(obj,"Left"));
            return new JObject {{"Node",Capture(Owner(tag,owner),obj)},{"Front",front},{"Left",left},{"Name",(front?"Front":"Rear")+" "+(left?"Left":"Right")}};
        }
        public void Run()
        {
            Directory.CreateDirectory(output);
            // A blueprint must directly own the requested vehicle folder or a recorded mesh.
            var candidates=entries.Where(e=>e.Type=="RaceVehicleBlueprint" &&
                (Core.InScope(e.Name,manifest.Scope) || manifest.Meshes.Any(m=>Core.InScope(m.Asset,Path.GetDirectoryName(e.Name).Replace('\\','/'))))).ToList();
            if(candidates.Count!=1)throw new InvalidDataException("Expected one matching RaceVehicleBlueprint; found "+candidates.Count+". Use one vehicle folder.");
            var vehicle=candidates[0];var asset=Load(vehicle.Guid);var root=asset.RootObject;
            var objects=asset.Objects.ToList();
            Document["Vehicle"]=new JObject {{"Asset",vehicle.Name},{"FileGuid",vehicle.Guid},{"Node",Capture(vehicle.Guid,root)}};
            foreach(var obj in objects)Capture(vehicle.Guid,obj);
            var entity=Resolve(Batch.Get(root,"Object"));
            var hash=Convert.ToUInt32(Batch.Get(Batch.Get(entity,"VehicleBundleHash"),"Hash"));
            var parents=new Dictionary<string,string>();
            foreach(var obj in objects) foreach(var p in List(obj,"Components")) {
                if(!(p is PointerRef)||((PointerRef)p).Type==PointerRefType.Null)continue;
                string child=MaterialRun.ObjectKey(Owner(p,vehicle.Guid),Resolve(p)),parent=MaterialRun.ObjectKey(vehicle.Guid,obj);
                if(parents.ContainsKey(child)&&parents[child]!=parent)Issue(child,"Multiple component parents.");
                else parents[child]=parent;
            }
            var links=List(root,"LinkConnections").ToList();
            foreach(var obj in objects.Where(o=>Batch.Get(o,"Transform")!=null)) {
                string id=MaterialRun.ObjectKey(vehicle.Guid,obj),parent;parents.TryGetValue(id,out parent);
                components.Add(new JObject {{"Node",id},{"Type",obj.GetType().Name},{"Parent",parent},{"Transform",new JArray(Matrix(Batch.Get(obj,"Transform")))},
                    {"Facing",Facing(Batch.Get(obj,"Tag"),vehicle.Guid)}});
            }
            foreach(var rim in objects.Where(o=>o.GetType().Name=="RimCustomizationComponentData")) {
                var facing=Facing(Batch.Get(rim,"Tag"),vehicle.Guid);
                var linked=links.Where(l=>((PointerRef)Batch.Get(l,"Source")).Type==PointerRefType.Internal &&
                    Object.ReferenceEquals(Resolve(Batch.Get(l,"Source")),rim) &&
                    Resolve(Batch.Get(l,"Target")).GetType().Name=="RaceWheelComponentData").ToList();
                if(facing==null||linked.Count!=1){Issue(Capture(vehicle.Guid,rim),"Cannot uniquely link tagged rim to wheel.");continue;}
                object wheel=Resolve(Batch.Get(linked[0],"Target"));
                var config=Batch.Get(wheel,"Config");
                wheels.Add(new JObject {{"Name",facing["Name"]},{"Facing",facing},{"RimComponent",Capture(vehicle.Guid,rim)},
                    {"WheelComponent",Capture(vehicle.Guid,wheel)},{"Transform",new JArray(Matrix(Batch.Get(wheel,"Transform")))},
                    {"Link",Raw(linked[0],vehicle.Guid)},{"WheelConfig",Capture(Owner(config,vehicle.Guid),Resolve(config))},
                    {"PivotOffset",Raw(Batch.Get(rim,"PivotOffset"),vehicle.Guid)},{"PositionStatus","authored_rest_transform"},
                    {"RuntimeStatus","Loaded suspension, camber and tire shader deformation not simulated."}});
            }
            if(wheels.Count!=4||wheels.Select(w=>(string)w["Name"]).Distinct().Count()!=4)Issue("Wheels","Expected four uniquely tagged wheel links.");
            // Match the item through its RaceVehicleReference bundle hash, not a guessed asset spelling.
            EbxAssetEntry vehicleItem=null;object stock=null;int stockMatches=0;
            foreach(var e in entries.Where(e=>e.Type=="RaceVehicleItemData")) {
                try {
                    var o=Load(e.Guid).RootObject;var ptr=Batch.Get(o,"RaceVehicle");
                    if(!(ptr is PointerRef)||((PointerRef)ptr).Type==PointerRefType.Null)continue;
                    var reference=Resolve(ptr);var bundle=Batch.Get(reference,"VehicleBundleHash");
                    if(bundle!=null&&Convert.ToUInt32(Batch.Get(bundle,"Hash"))==hash) {
                        stockMatches++;
                        vehicleItem=e;stock=o;
                    }
                } catch(Exception ex) {Issue(e.Name,ex.Message);}
            }
            if(stockMatches>1)throw new InvalidDataException("Multiple vehicle stock items match bundle; stock selection is ambiguous.");
            if(stock==null)throw new InvalidDataException("Vehicle stock item not found by bundle hash.");
            Document["StockItem"]=Capture(vehicleItem.Guid,stock);
            var defaultFiles=new HashSet<Guid>(List(stock,"SubItems").Where(v=>v is PointerRef&&((PointerRef)v).Type==PointerRefType.External).Select(v=>((PointerRef)v).External.FileGuid));
            string itemFolder=vehicleItem.Name.Substring(0,vehicleItem.Name.LastIndexOf('/'));
            var selected=entries.Where(e=>Core.InScope(e.Name,itemFolder)||defaultFiles.Contains(e.Guid)).ToList();
            var presets=new JArray();Document["Presets"]=presets;
            foreach(var e in selected) {
                if(IsCancelled)break;
                var o=Load(e.Guid).RootObject;
                if(o.GetType().Name=="TemplateItemData")
                    presets.Add(new JObject {{"Node",Capture(e.Guid,o)},{"Asset",e.Name},{"SubItems",Raw(Batch.Get(o,"SubItems"),e.Guid)}});
                if(Batch.Get(o,"MeshBlueprintPermutations")==null)continue;
                var item=new JObject {{"Node",Capture(e.Guid,o)},{"Asset",e.Name},{"Type",o.GetType().Name},{"ItemId",Raw(Batch.Get(Batch.Get(o,"Id"),"Id"),e.Guid)},
                    {"Default",defaultFiles.Contains(e.Guid)},{"Location",Batch.Get(o,"Location")==null?null:Batch.Get(o,"Location").ToString()},
                    {"Permutations",new JArray()},{"TireMeshInfos",Raw(Batch.Get(o,"TireMeshInfos"),e.Guid)},{"Raw",Raw(o,e.Guid)}};
                items.Add(item);
                foreach(var p in List(o,"MeshBlueprintPermutations")) {
                    var row=new JObject {{"Meshes",new JArray()},{"Restrictions",Raw(Batch.Get(p,"MeshPermutationRestrictions"),e.Guid)},
                        {"Offsets",Raw(Batch.Get(p,"MeshPermutationOffsets"),e.Guid)},{"Deprecated",Raw(Batch.Get(p,"Deprecated"),e.Guid)}};
                    ((JArray)item["Permutations"]).Add(row);
                    foreach(var desc in List(p,"Meshes")) {
                        ((JArray)row["Meshes"]).Add(new JObject {{"BlueprintGuid",Raw(Batch.Get(desc,"MeshGuid"),e.Guid)},
                            {"Facing",Facing(Batch.Get(desc,"Tag"),e.Guid)},{"Rotate",Raw(Batch.Get(desc,"Rotate"),e.Guid)},{"Raw",Raw(desc,e.Guid)}});
                    }
                }
            }
            var desired=new HashSet<Guid>(items.SelectMany(i=>i["Permutations"]).SelectMany(p=>p["Meshes"]).Select(m=>Guid.Parse((string)m["BlueprintGuid"])));
            var cmiOwners=new Dictionary<Guid,List<JObject>>();
            foreach(var component in objects.Where(o=>Batch.Get(o,"CustomizableMeshInfos")!=null)) {
                if(IsCancelled)break;
                var facing=Facing(Batch.Get(component,"Tag"),vehicle.Guid);
                foreach(var p in List(component,"CustomizableMeshInfos")) {
                    try {
                        Guid owner=Owner(p,vehicle.Guid);object cmi=Resolve(p);
                        Guid bp=(Guid)Batch.Get(cmi,"BlueprintGuid");
                        var e=App.AssetManager.GetEbxEntry(owner);
                        if(!desired.Contains(bp)&&!Core.InScope(e.Name,Path.GetDirectoryName(vehicle.Name).Replace('\\','/')))continue;
                        string cmiId=Capture(owner,cmi);
                        if(!cmiOwners.ContainsKey(bp))cmiOwners[bp]=new List<JObject>();
                        cmiOwners[bp].Add(new JObject {{"Component",Capture(vehicle.Guid,component)},{"CMI",cmiId},{"Facing",facing}});
                        if(blueprints.ContainsKey(bp))continue;
                        // Follow the matching bundle's real pointer and verify the blueprint object GUID.
                        var bundles=entries.Where(b=>b.Type=="BlueprintBundle"&&b.Name.StartsWith(e.Name+"_",StringComparison.OrdinalIgnoreCase)).ToArray();
                        bool found=false;
                        foreach(var bundle in bundles) {
                            object bundleRoot=Load(bundle.Guid).RootObject;object ptr=Batch.Get(bundleRoot,"Blueprint");
                            object target=Resolve(ptr);
                            if(ObjectGuid(target)!=bp)continue;
                            Guid bpOwner=Owner(ptr,bundle.Guid);
                            blueprints[bp]=Tuple.Create(App.AssetManager.GetEbxEntry(bpOwner),target);
                            Capture(bundle.Guid,bundleRoot);
                            foreach(var db in entries.Where(db=>db.Type=="MeshVariationDatabase"&&Core.InScope(db.Name,bundle.Name)))variantDbs.Add(db.Guid);
                            found=true;break;
                        }
                        if(!found)Issue(e.Name,"No bundle points to expected blueprint "+bp);
                    } catch(Exception ex) {Issue("CMI",ex.Message);}
                }
            }
            foreach(var pair in blueprints) {
                var owner=pair.Value.Item1;object bp=pair.Value.Item2;
                Capture(owner.Guid,bp);
                var visited=new HashSet<string>();
                CollectMeshes(Batch.Get(bp,"Object"),owner.Guid,pair.Key,new List<JToken>(),visited);
                foreach(var p in List(bp,"Objects"))CollectMeshes(p,owner.Guid,pair.Key,new List<JToken>(),visited);
            }
            Document["BlueprintComponents"]=JObject.FromObject(cmiOwners.ToDictionary(x=>x.Key.ToString(),x=>x.Value));
            // Main composite stays in its original export space.
            foreach(var rendering in objects.Where(o=>o.GetType().Name=="CustomizableVehicleRenderingComponentData")) {
                var p=Batch.Get(rendering,"Mesh");var m=AddMesh(Owner(p,vehicle.Guid),Resolve(p));
                Document["BodyMeshId"]=m.Id;
            }
            // Retain vehicle tuning and material customization parameters as raw source data.
            foreach(var car in objects.Where(o=>o.GetType().Name=="CarComponentData")) {
                var p=Batch.Get(car,"RaceVehicleConfig");var owner=Owner(p,vehicle.Guid);object config=Resolve(p);
                Document["RaceVehicleConfig"]=Capture(owner,config);
                foreach(string field in new[]{"Tire","Chassis","Suspension","Steering"}) {
                    var cp=Batch.Get(config,field);
                    if(cp is PointerRef&&((PointerRef)cp).Type!=PointerRefType.Null)Document[field+"Config"]=Capture(Owner(cp,owner),Resolve(cp));
                }
            }
            foreach(Guid dbId in variantDbs)AddVariants(dbId);
            Save();
        }
        private void CollectMeshes(object pointer,Guid owner,Guid blueprint,List<JToken> chain,HashSet<string> visited)
        {
            if(!(pointer is PointerRef)||((PointerRef)pointer).Type==PointerRefType.Null)return;
            owner=Owner(pointer,owner);object obj=Resolve(pointer);string key=Capture(owner,obj);
            if(!visited.Add(key))return;
            var next=new List<JToken>(chain);
            if(Batch.Get(obj,"Transform")!=null)next.Add(new JArray(Matrix(Batch.Get(obj,"Transform"))));
            var mesh=Batch.Get(obj,"Mesh");
            if(mesh is PointerRef&&((PointerRef)mesh).Type!=PointerRefType.Null) {
                var record=AddMesh(Owner(mesh,owner),Resolve(mesh));
                meshUses.Add(new JObject {{"BlueprintGuid",blueprint},{"ProxyNode",key},{"MeshId",record.Id},{"TransformChain",new JArray(next)},
                    {"BasePoseTransforms",Raw(Batch.Get(obj,"BasePoseTransforms"),owner)},{"Visible",Raw(Batch.Get(obj,"Visible"),owner)}});
            }
            foreach(var child in List(obj,"Components"))CollectMeshes(child,owner,blueprint,next,visited);
            foreach(var child in List(obj,"Objects"))CollectMeshes(child,owner,blueprint,next,visited);
            var nested=Batch.Get(obj,"Blueprint");if(nested is PointerRef&&((PointerRef)nested).Type!=PointerRefType.Null) {
                Guid nestedOwner=Owner(nested,owner);object bp=Resolve(nested);Capture(nestedOwner,bp);
                CollectMeshes(Batch.Get(bp,"Object"),nestedOwner,blueprint,next,visited);
            }
        }
        private MeshRecord AddMesh(Guid owner,object obj)
        {
            string key=MaterialRun.ObjectKey(owner,obj),id=Core.Id(key);
            var old=manifest.Meshes.FirstOrDefault(m=>m.Id==id);
            if(old!=null){old.Object=obj;return old;}
            var e=App.AssetManager.GetEbxEntry(owner);Guid cls=ObjectGuid(obj);
            var guid=(AssetClassGuid)obj.GetType().GetMethod("GetInstanceGuid",Type.EmptyTypes).Invoke(obj,null);
            var added=new MeshRecord {Id=id,Asset=e.Name,FileGuid=owner.ToString(),ClassGuid=cls.ToString(),InternalId=guid.IsExported?null:guid.InternalId.ToString(),Type=obj.GetType().Name,Object=obj};
            manifest.Meshes.Add(added);return added;
        }
        private void AddVariants(Guid owner)
        {
            var db=App.AssetManager.GetEbxEntry(owner);int index=0;
            foreach(var row in List(Load(owner).RootObject,"Entries")) {
                int n=index++;
                try {
                    var p=Batch.Get(row,"Mesh");string id=Core.Id(MaterialRun.ObjectKey(Owner(p,owner),Resolve(p)));
                    var mesh=manifest.Meshes.FirstOrDefault(m=>m.Id==id);if(mesh==null)continue;
                    if(mesh.Variants.Any(v=>v.DatabaseGuid==owner.ToString()&&v.Row==n))continue;
                    mesh.Variants.Add(new VariantRecord {Database=db.Name,DatabaseGuid=owner.ToString(),Row=n,Hash=Convert.ToUInt32(Batch.Get(row,"VariationAssetNameHash")).ToString("x8")});
                } catch(Exception ex){Issue(db.Name+"#"+n,ex.Message);}
            }
        }
        public void Save()
        {
            Document["Status"]=IsCancelled?"cancelled":issues.Count==0?"completed":"completed_with_issues";
            MaterialRun.WriteJson(Path.Combine(output,"assembly.json"),Document);
            File.WriteAllLines(Path.Combine(output,"assembly.log"),issues.Select(i=>(string)i["Path"]+": "+(string)i["Message"]));
        }
    }
}
