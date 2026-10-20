using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using Frosty.Core;
using Frosty.Core.Attributes;
using Frosty.Core.Windows;
using FrostySdk;
using FrostySdk.Ebx;
using FrostySdk.IO;
using FrostySdk.Managers.Entries;
using MeshSetPlugin;
using MeshSetPlugin.Resources;
using Newtonsoft.Json;

[assembly: AssemblyTitle("UnboundBatchExport")]
[assembly: AssemblyVersion("0.4.0.0")]
[assembly: PluginDisplayName("Unbound Vehicle Batch Export (experimental)")]
[assembly: PluginAuthor("An Vu")]
[assembly: PluginVersion("0.4.0.0")]
[assembly: RegisterMenuExtension(typeof(UnboundBatchExport.ExportMenu))]

namespace UnboundBatchExport
{
    public sealed class ExportMenu : MenuExtension
    {
        private static int busy;
        public override string TopLevelMenuName { get { return "Tools"; } }
        public override string MenuItemName { get { return "Unbound vehicle batch export..."; } }
        public override RelayCommand MenuItemClicked { get { return new RelayCommand(o => Run()); } }
        private static void Run()
        {
            if (Interlocked.Exchange(ref busy, 1) != 0) return;
            try
            {
                if (!ProfilesLibrary.IsLoaded(ProfileVersion.NeedForSpeedUnbound)) throw new InvalidOperationException("Load the NFS Unbound profile first.");
                using (var options = new Options())
                {
                    if (options.ShowDialog() != DialogResult.OK) return;
                    using (var folder = new FolderBrowserDialog { Description = "Choose parent folder for a NEW export run" })
                    {
                        if (folder.ShowDialog() != DialogResult.OK) return;
                        string target = Path.Combine(folder.SelectedPath, "Unbound_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss") + "_" + Guid.NewGuid().ToString("N").Substring(0,8));
                        var batch = new Batch(Core.Normalize(options.Prefix.Text), options.Skeleton.Text.Trim(), target);
                        Exception fatal = null;
                        FrostyTaskWindow.Show("Unbound batch export", "Scanning databases", task => {
                            try { batch.Run(task); } catch (Exception ex) { fatal = ex; batch.Manifest.Errors.Add(ex.ToString()); }
                            finally { try { batch.Save(); } catch (Exception ex) { fatal = ex; } }
                        }, true, task => batch.Cancel = true);
                        MessageBox.Show((fatal == null ? "Export run finished. " : "Run failed: " + fatal.Message + "\n") +
                            batch.Manifest.Meshes.Count(x => x.Status == "exported") + " meshes exported; " + batch.Manifest.Errors.Count + " geometry/run errors.\nReview manifest.json for skips and materials.json/materials.log for texture results.\n" + target,
                            "Unbound batch export");
                    }
                }
            }
            catch (Exception ex) { MessageBox.Show(ex.Message, "Unbound batch export"); }
            finally { Interlocked.Exchange(ref busy, 0); }
        }
    }

    internal sealed class Options : Form
    {
        public readonly TextBox Prefix = new TextBox { Left=16, Top=48, Width=590 };
        public readonly TextBox Skeleton = new TextBox { Left=16, Top=108, Width=590 };
        public Options()
        {
            Text="Unbound vehicle batch export"; Width=640; Height=290; FormBorderStyle=FormBorderStyle.FixedDialog; MaximizeBox=false; MinimizeBox=false;
            Controls.Add(new Label { Left=16, Top=16, Width=600, Text="Exact vehicle folder / asset path from Frosty's Data Explorer (required):" }); Controls.Add(Prefix);
            Controls.Add(new Label { Left=16, Top=82, Width=600, Text="Skeleton asset path (optional; skinned meshes are skipped if empty):" }); Controls.Add(Skeleton);
            Controls.Add(new Label { Left=16, Top=145, Width=600, Height=48, Text="LOD0, binary FBX 2014, meters, hierarchy retained. Current loaded asset state.\nTextures and authored assembly data are extracted. Shader reconstruction remains partial." });
            var go = new Button { Text="Export...", Left=410, Top=208, Width=95 };
            go.Click += (s,e) => { if (Core.Normalize(Prefix.Text).Length == 0) { MessageBox.Show("Enter a specific vehicle folder or asset path."); return; } DialogResult=DialogResult.OK; };
            var cancel = new Button { Text="Cancel", Left=515, Top=208, Width=90, DialogResult=DialogResult.Cancel };
            Controls.Add(go); Controls.Add(cancel); AcceptButton=go; CancelButton=cancel;
        }
    }

    public sealed class Manifest
    {
        public int Schema = 1;
        public string PluginVersion = "0.4.0";
        public string Target = "HarGabt 1.0.7 v1.0.7_26.10.12 / NFS Unbound";
        public string Scope, CreatedUtc, MeshSetPluginVersion;
        public string TransformPolicy = "Mesh-local geometry unchanged; hierarchy retained; rigid composite transforms only. Raw composite matrices retained. No blueprint/entity placement inferred.";
        public string VariantPolicy = "Database row/material references only; variation hashes are not body-kit assembly definitions. Shared geometry exported once.";
        public string Units = "Meters";
        public bool Cancelled;
        public int DatabasesScanned;
        public int DatabasesConsidered, DatabasesSkippedByDependencies;
        public List<MeshRecord> Meshes = new List<MeshRecord>();
        public List<string> Errors = new List<string>();
    }
    public sealed class MeshRecord
    {
        public string Id, Asset, FileGuid, ClassGuid, InternalId, Type, Fbx, Skeleton, Status="pending", Error;
        public List<double[]> CompositeTransforms = new List<double[]>();
        public List<double[]> SkeletonLocalPoses = new List<double[]>();
        public List<double[]> ProceduralLocalPoses = new List<double[]>();
        public List<VariantRecord> Variants = new List<VariantRecord>();
        [JsonIgnore] public object Object;
    }
    public sealed class VariantRecord
    {
        public string Database, DatabaseGuid, Hash;
        public int Row;
        public List<object> Materials = new List<object>();
    }

    public sealed class Batch
    {
        public readonly Manifest Manifest = new Manifest();
        public volatile bool Cancel;
        private readonly string prefix, skeleton, output;
        private readonly Dictionary<string,MeshRecord> meshes = new Dictionary<string,MeshRecord>();
        public Batch(string scope, string skeletonAsset, string directory)
        {
            prefix=scope; skeleton=skeletonAsset; output=directory;
            Manifest.Scope=scope; Manifest.CreatedUtc=DateTime.UtcNow.ToString("o");
            Manifest.MeshSetPluginVersion=typeof(FBXExporter).Assembly.FullName;
        }
        public static object Get(object obj, string name)
        {
            if (obj == null) return null;
            var p=obj.GetType().GetProperty(name); if(p!=null) return p.GetValue(obj,null);
            var f=obj.GetType().GetField(name); return f == null ? null : f.GetValue(obj);
        }
        public static object Resolve(PointerRef ptr, Func<Guid,EbxAsset> load)
        {
            if (ptr.Type == PointerRefType.Internal) return ptr.Internal;
            if (ptr.Type != PointerRefType.External) throw new InvalidDataException("Null mesh reference.");
            var asset=load(ptr.External.FileGuid);
            if (asset == null) throw new InvalidDataException("Missing EBX file " + ptr.External.FileGuid);
            object obj=ptr.External.ClassGuid == Guid.Empty ? asset.RootObject : asset.GetObject(ptr.External.ClassGuid);
            if(obj==null) throw new InvalidDataException("Missing EBX object " + ptr.External.ClassGuid + " in " + ptr.External.FileGuid);
            return obj;
        }
        private MeshRecord Add(EbxAssetEntry owner, object obj, Guid classGuid)
        {
            if (Get(obj,"MeshSetResource") == null) throw new InvalidDataException("Referenced object has no MeshSetResource.");
            string internalId=null;
            if(classGuid==Guid.Empty) internalId=((AssetClassGuid)((dynamic)obj).GetInstanceGuid()).InternalId.ToString();
            string key=owner.Guid.ToString("N") + ":" + (internalId==null ? classGuid.ToString("N") : "internal:" + internalId);
            MeshRecord record;
            if (!meshes.TryGetValue(key,out record))
            {
                record=new MeshRecord { Id=Core.Id(key), Asset=owner.Name, FileGuid=owner.Guid.ToString(), ClassGuid=classGuid.ToString(), InternalId=internalId, Type=obj.GetType().Name, Object=obj };
                meshes.Add(key,record); Manifest.Meshes.Add(record);
            }
            return record;
        }
        private static object PointerInfo(object value)
        {
            if (!(value is PointerRef)) return null;
            var p=(PointerRef)value;
            return new { Kind=p.Type.ToString(), FileGuid=p.External.FileGuid, ClassGuid=p.External.ClassGuid,
                InternalType=p.Internal == null ? null : p.Internal.GetType().Name };
        }
        public static bool DatabaseMayReferenceScope(EbxAssetEntry database,string scope,HashSet<Guid> scopedFiles)
        {
            if(Core.InScope(database.Name,scope))return true;
            // SDK import tables include every external PointerRef file. Modified
            // assets expose their current dependencies through this same API.
            // Empty lists may mean unavailable metadata, so retain the slow path.
            var dependencies=database.EnumerateDependencies().ToList();
            return dependencies.Count==0 || dependencies.Any(g=>scopedFiles.Contains(g));
        }
        public void Run(FrostyTaskWindow task)
        {
            Directory.CreateDirectory(output);
            var entries=App.AssetManager.EnumerateEbx().OrderBy(e=>e.Name,StringComparer.OrdinalIgnoreCase).ToList();
            var scopedFiles=new HashSet<Guid>(entries.Where(e=>Core.InScope(e.Name,prefix)).Select(e=>e.Guid));
            foreach (var db in entries.Where(e => e.Type == "MeshVariationDatabase" || e.Filename.IndexOf("MeshVariationDb_Win32",StringComparison.OrdinalIgnoreCase)>=0))
            {
                if(Cancel) break;
                Manifest.DatabasesConsidered++;
                if(!DatabaseMayReferenceScope(db,prefix,scopedFiles)) {Manifest.DatabasesSkippedByDependencies++;continue;}
                task.Update("Reading " + db.Name);
                try
                {
                    var asset=App.AssetManager.GetEbx(db);
                    var rows=Get(asset.RootObject,"Entries") as IEnumerable;
                    if(rows==null) throw new InvalidDataException("Database has no Entries collection.");
                    Manifest.DatabasesScanned++;
                    int index=0;
                    foreach(object row in rows)
                    {
                        if(Cancel) break;
                        int rowIndex=index++;
                        try
                        {
                            object value=Get(row,"Mesh");
                            if(!(value is PointerRef)) throw new InvalidDataException("Mesh is not a PointerRef.");
                            var ptr=(PointerRef)value;
                            EbxAssetEntry owner=ptr.Type==PointerRefType.External ? App.AssetManager.GetEbxEntry(ptr.External.FileGuid) : db;
                            if (!Core.InScope(db.Name,prefix) && (owner==null || !Core.InScope(owner.Name,prefix))) continue;
                            object obj=Resolve(ptr, guid => { var e=App.AssetManager.GetEbxEntry(guid); return e==null ? null : App.AssetManager.GetEbx(e); });
                            Guid cls=ptr.Type==PointerRefType.External ? ptr.External.ClassGuid : ((dynamic)obj).GetInstanceGuid().ExportedGuid;
                            if(cls==Guid.Empty) cls=((dynamic)obj).GetInstanceGuid().ExportedGuid;
                            var record=Add(owner,obj,cls);
                            object hash=Get(row,"VariationAssetNameHash");
                            var variant=new VariantRecord { Database=db.Name, DatabaseGuid=db.Guid.ToString(), Row=rowIndex, Hash=hash==null ? "unknown" : Convert.ToUInt32(hash).ToString("x8") };
                            var materials=Get(row,"Materials") as IEnumerable;
                            if(materials!=null) foreach(object material in materials)
                                variant.Materials.Add(new { Material=PointerInfo(Get(material,"Material")), MaterialVariation=PointerInfo(Get(material,"MaterialVariation")), SurfaceShaderId=Get(material,"SurfaceShaderId"), SurfaceShaderGuid=Get(material,"SurfaceShaderGuid") });
                            record.Variants.Add(variant);
                        }
                        catch(Exception ex) { Manifest.Errors.Add(db.Name + " row " + rowIndex + ": " + ex.Message); }
                    }
                }
                catch(Exception ex) { Manifest.Errors.Add(db.Name + ": " + ex.Message); }
            }
            // Include unreferenced mesh assets inside the explicit vehicle scope.
            foreach(var entry in entries.Where(e=>Core.InScope(e.Name,prefix) && (e.Type=="RigidMeshAsset" || e.Type=="CompositeMeshAsset" || e.Type=="SkinnedMeshAsset")))
            {
                if(Cancel) break;
                try { var asset=App.AssetManager.GetEbx(entry); Add(entry,asset.RootObject,asset.RootInstanceGuid); }
                catch(Exception ex) { Manifest.Errors.Add(entry.Name + ": " + ex.Message); }
            }
            AssemblyRun assembly=null;
            if(!Cancel) {
                try {assembly=new AssemblyRun(Manifest,output) {CancellationRequested=()=>Cancel};assembly.Run();}
                catch(Exception ex) {if(assembly!=null){assembly.Issue("run",ex.Message);assembly.Save();}Manifest.Errors.Add("Assembly: "+ex.Message);}
            }
            Save();
            foreach(var record in Manifest.Meshes)
            {
                if(Cancel) break;
                try { Export(record,task); }
                catch(Exception ex) { record.Status="failed"; record.Error=ex.ToString(); Manifest.Errors.Add(record.Asset + ": " + ex.Message); }
                Save();
            }
            if(!Cancel)
            {
                var materialRun=new MaterialRun(output,prefix);
                try {
                    foreach(var record in Manifest.Meshes) {
                        if(Cancel) {materialRun.Cancel=true;break;}
                        task.Update("Materials: "+record.Asset);
                        materialRun.Process(record);materialRun.Save();
                    }
                } catch(Exception ex) {materialRun.Issue("run",ex);}
                finally {materialRun.Save(true);}
            }
            Manifest.Cancelled=Cancel;
            foreach(var record in Manifest.Meshes.Where(r=>r.Status=="pending")) record.Status="cancelled";
        }
        private void Export(MeshRecord record, FrostyTaskWindow task)
        {
            ulong rid=GetResourceId(Get(record.Object,"MeshSetResource"));
            var res=App.AssetManager.GetResEntry(rid);
            if(res==null) throw new InvalidDataException("Missing mesh resource " + rid);
            var mesh=App.AssetManager.GetResAs<MeshSet>(res);
            if(mesh==null || mesh.Lods.Count==0) throw new InvalidDataException("Mesh resource has no LOD0.");
            foreach(var t in mesh.Lods[0].PartTransforms)
                record.CompositeTransforms.Add(new double[] {t.right.x,t.right.y,t.right.z,t.up.x,t.up.y,t.up.z,t.forward.x,t.forward.y,t.forward.z,t.trans.x,t.trans.y,t.trans.z});
            if(mesh.Type==MeshType.MeshType_Composite && record.CompositeTransforms.Any(m=>!Core.IsRigid(m)))
                throw new NotSupportedException("Composite scale, reflection, shear or invalid matrix: native exporter would lose it. Raw transforms retained; FBX deliberately not written.");
            if(mesh.Type==MeshType.MeshType_Skinned && (skeleton.Length==0 || App.AssetManager.GetEbxEntry(skeleton)==null))
            { record.Status="skipped"; record.Error="Skinned mesh requires a valid explicit skeleton asset path."; return; }
            if(mesh.Type==MeshType.MeshType_Skinned)
            {
                record.Skeleton=skeleton;
                object skel=App.AssetManager.GetEbx(App.AssetManager.GetEbxEntry(skeleton)).RootObject;
                var poses=Get(skel,"LocalPose") as IEnumerable;
                if(poses==null) throw new InvalidDataException("Skeleton has no LocalPose collection.");
                foreach(object pose in poses) record.SkeletonLocalPoses.Add(ReadMatrix(pose));
                var procedural=Get(Get(record.Object,"SkinnedProceduralAnimation"),"Bones") as IEnumerable;
                if(procedural!=null) foreach(object bone in procedural) record.ProceduralLocalPoses.Add(ReadMatrix(Get(bone,"Pose")));
                if(record.SkeletonLocalPoses.Concat(record.ProceduralLocalPoses).Any(m=>!Core.IsRigid(m)))
                    throw new NotSupportedException("Skeleton scale, reflection, shear or invalid matrix: native exporter would lose it. Raw poses retained; FBX not written.");
            }
            string relative="parts/" + Core.SafeName(Path.GetFileName(Core.Normalize(record.Asset))) + "_" + record.Id + "/LOD0.fbx";
            string file=Path.Combine(output,relative.Replace('/',Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            string partial=Core.PendingFbxPath(file);
            try
            {
                new FBXExporter(task).ExportFBX(record.Object,partial,"2014","Meters",false,true,false,skeleton,"binary",mesh);
                if(!Core.HasBinaryFbxHeader(partial)) throw new IOException("Native FBX export returned without a valid binary FBX header.");
                File.Move(partial,file); record.Fbx=relative; record.Status="exported";
            }
            finally { if(File.Exists(partial)) File.Delete(partial); }
        }
        public void ExportAdditional(MeshRecord record,FrostyTaskWindow task)
        {
            if(record.Status=="exported")return;
            try {Export(record,task);}
            catch(Exception ex) {record.Status="failed";record.Error=ex.ToString();Manifest.Errors.Add(record.Asset+": "+ex.Message);}
        }
        public static ulong GetResourceId(object value)
        {
            // ResourceRef defines an implicit ulong conversion, not IConvertible.
            // Unbox it first; Convert.ToUInt64(object) bypasses that operator.
            ulong id;
            if(value is ResourceRef) id=(ResourceRef)value;
            else if(value is ulong) id=(ulong)value;
            else throw new InvalidDataException("MeshSetResource must be a ResourceRef or UInt64; got " + (value==null ? "null" : value.GetType().FullName));
            if(id==0) throw new InvalidDataException("MeshSetResource is zero.");
            return id;
        }
        public static double[] ReadMatrix(object pose)
        {
            var values=new List<double>();
            foreach(string basis in new [] {"right","up","forward","trans"})
            {
                object vector=Get(pose,basis);
                foreach(string axis in new [] {"x","y","z"})
                {
                    object value=Get(vector,axis);
                    if(value==null) throw new InvalidDataException("Missing transform field " + basis + "." + axis);
                    values.Add(Convert.ToDouble(value));
                }
            }
            return values.ToArray();
        }
        public void Save()
        {
            Directory.CreateDirectory(output);
            string path=Path.Combine(output,"manifest.json"), temp=path + ".tmp";
            File.WriteAllText(temp,JsonConvert.SerializeObject(Manifest,Formatting.Indented));
            if(File.Exists(path)) File.Replace(temp,path,null); else File.Move(temp,path);
        }
    }
}
