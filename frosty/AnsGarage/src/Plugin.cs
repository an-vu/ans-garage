using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Drawing;
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

[assembly: AssemblyTitle("AnsGarage")]
[assembly: AssemblyVersion("1.0.1.0")]
[assembly: PluginDisplayName("An's Garage for Frosty")]
[assembly: PluginAuthor("An Vu")]
[assembly: PluginVersion("1.0.1.0")]
[assembly: RegisterMenuExtension(typeof(AnsGarage.ExportMenu))]
[assembly: RegisterMenuExtension(typeof(AnsGarage.TireLibraryMenu))]

namespace AnsGarage
{
    public sealed class ExportMenu : MenuExtension
    {
        private static int busy;
        public override string TopLevelMenuName { get { return "Tools"; } }
        public override string SubLevelMenuName { get { return "An's Garage"; } }
        public override string MenuItemName { get { return "Export vehicle..."; } }
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
                        if (options.Blueprint != null && Core.InScope(options.Blueprint, Core.Normalize(options.Prefix.Text))) batch.Blueprint = options.Blueprint;
                        Exception fatal = null;
                        FrostyTaskWindow.Show("An's Garage: export vehicle", "Scanning databases", task => {
                            try { batch.Run(task); } catch (Exception ex) { fatal = ex; batch.Manifest.Errors.Add(ex.ToString()); }
                            finally { try { batch.Save(); } catch (Exception ex) { fatal = ex; } }
                        }, true, task => batch.Cancel = true);
                        MessageBox.Show((fatal == null ? "Export run finished. " : "Run failed: " + fatal.Message + "\n") +
                            batch.Manifest.Meshes.Count(x => x.Status == "exported") + " meshes exported; " + batch.Manifest.Errors.Count + " geometry/run errors.\nReview manifest.json for skips and materials.json/materials.log for texture results.\n" + target,
                            "An's Garage");
                    }
                }
            }
            catch (Exception ex) { MessageBox.Show(ex.Message, "An's Garage"); }
            finally { Interlocked.Exchange(ref busy, 0); }
        }
    }

    // Layout panels size every control from its text, so nothing is clipped at any Windows display scaling.
    internal static class Ui
    {
        public static void Setup(Form f, string title)
        {
            f.Text = title; f.Font = SystemFonts.MessageBoxFont; f.AutoScaleMode = AutoScaleMode.Dpi;
            f.FormBorderStyle = FormBorderStyle.FixedDialog; f.MaximizeBox = false; f.MinimizeBox = false;
            f.StartPosition = FormStartPosition.CenterScreen; f.AutoSize = true; f.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            f.Padding = new Padding(12);
        }
        public static TableLayoutPanel Grid(int columns)
        {
            var g = new TableLayoutPanel { ColumnCount = columns, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Dock = DockStyle.Fill };
            return g;
        }
        public static Label Text(string text) { return new Label { Text = text, AutoSize = true, Margin = new Padding(3, 8, 3, 3) }; }
        public static Button Button(string text) { return new Button { Text = text, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, MinimumSize = new Size(90, 0), Padding = new Padding(6, 2, 6, 2) }; }
        public static FlowLayoutPanel Buttons(params Button[] buttons)
        {
            var row = new FlowLayoutPanel { FlowDirection = FlowDirection.RightToLeft, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Dock = DockStyle.Fill, Margin = new Padding(0, 10, 0, 0) };
            foreach (var b in buttons) row.Controls.Add(b);
            return row;
        }
    }

    internal sealed class Options : Form
    {
        public readonly TextBox Prefix = new TextBox { Width = 560, Anchor = AnchorStyles.Left | AnchorStyles.Right };
        public string Blueprint;
        public readonly TextBox Skeleton = new TextBox { Width = 560, Anchor = AnchorStyles.Left | AnchorStyles.Right };
        public Options()
        {
            Ui.Setup(this, "An's Garage: export vehicle");
            var g = Ui.Grid(2);
            g.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            g.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            var choose = Ui.Button("Choose vehicle...");
            choose.Click += (s,e) => { using (var picker = new VehiclePicker()) if (picker.ShowDialog(this) == DialogResult.OK) { Prefix.Text = picker.Folder; Blueprint = picker.Blueprint; } };
            Prefix.TextChanged += (s,e) => { if (Blueprint != null && !Core.InScope(Blueprint, Core.Normalize(Prefix.Text))) Blueprint = null; };
            g.Controls.Add(Ui.Text("Vehicle folder (or click Choose vehicle... to pick by in-game name):"), 0, 0); g.SetColumnSpan(g.GetControlFromPosition(0, 0), 2);
            g.Controls.Add(Prefix, 0, 1); g.Controls.Add(choose, 1, 1);
            var skel = Ui.Text("Skeleton asset path (optional; skinned meshes are skipped if empty):");
            g.Controls.Add(skel, 0, 2); g.SetColumnSpan(skel, 2);
            g.Controls.Add(Skeleton, 0, 3); g.SetColumnSpan(Skeleton, 2);
            var info = Ui.Text("LOD0, binary FBX 2014, meters, hierarchy retained. Current loaded asset state.\nTextures, in-game part names, shader default textures and assembly data are exported.");
            info.MaximumSize = new Size(680, 0);
            g.Controls.Add(info, 0, 4); g.SetColumnSpan(info, 2);
            var go = Ui.Button("Export...");
            go.Click += (s,e) => { if (Core.Normalize(Prefix.Text).Length == 0) { MessageBox.Show(this, "Enter a vehicle folder, or click Choose vehicle..."); return; } DialogResult=DialogResult.OK; };
            var cancel = Ui.Button("Cancel"); cancel.DialogResult = DialogResult.Cancel;
            var buttons = Ui.Buttons(cancel, go);
            g.Controls.Add(buttons, 0, 5); g.SetColumnSpan(buttons, 2);
            Controls.Add(g); AcceptButton=go; CancelButton=cancel;
        }
    }

    internal sealed class VehiclePicker : Form
    {
        public string Folder, Blueprint;
        // Two columns: in-game name and the vehicle's folder; click a header to sort by it.
        private readonly ListView list = new ListView { Width = 900, Height = 480, View = View.Details, FullRowSelect = true,
            MultiSelect = false, HideSelection = false, Dock = DockStyle.Fill };
        private int sortColumn;
        private readonly TextBox search = new TextBox { Dock = DockStyle.Fill };
        private readonly Label status = Ui.Text("");
        private readonly Button ok = Ui.Button("Select"), refresh = Ui.Button("Refresh list");
        private List<VehicleCatalog.Vehicle> vehicles = new List<VehicleCatalog.Vehicle>();
        private System.ComponentModel.BackgroundWorker worker;
        public VehiclePicker()
        {
            Ui.Setup(this, "Choose an NFS Unbound vehicle");
            var g = Ui.Grid(1);
            g.Controls.Add(Ui.Text("Search by in-game name or folder:"));
            g.Controls.Add(search); g.Controls.Add(list); g.Controls.Add(status);
            var cancel = Ui.Button("Cancel"); cancel.DialogResult = DialogResult.Cancel;
            g.Controls.Add(Ui.Buttons(cancel, ok, refresh));
            Controls.Add(g);
            list.Columns.Add("Car", 420); list.Columns.Add("Folder", 440);
            list.ColumnClick += (s,e) => { sortColumn = e.Column; Fill(); };
            ok.Click += (s,e) => { if (list.SelectedItems.Count == 0) return; var v = (VehicleCatalog.Vehicle)list.SelectedItems[0].Tag; Folder = v.Folder; Blueprint = v.Blueprint; DialogResult = DialogResult.OK; };
            list.DoubleClick += (s,e) => ok.PerformClick();
            search.TextChanged += (s,e) => Fill();
            refresh.Click += (s,e) => Start(true);
            AcceptButton=ok; CancelButton=cancel;
            Shown += (s,e) => Start(false);
            FormClosing += (s,e) => { if (worker != null && worker.IsBusy) { e.Cancel = true; status.Text = "Please wait until the vehicle list has been read."; } };
        }
        private void Start(bool rebuild)
        {
            var cached = rebuild ? null : VehicleCatalog.Cached();
            if (cached != null) { vehicles = cached; status.Text = vehicles.Count + " vehicles (cached list; Refresh list re-reads the game data)."; Fill(); return; }
            ok.Enabled = refresh.Enabled = search.Enabled = false;
            status.Text = "Reading vehicle data (first time only, may take a minute)...";
            worker = new System.ComponentModel.BackgroundWorker { WorkerReportsProgress = true };
            worker.DoWork += (s,e) => e.Result = VehicleCatalog.BuildAndCache(m => worker.ReportProgress(0, m));
            worker.ProgressChanged += (s,e) => status.Text = (string)e.UserState;
            worker.RunWorkerCompleted += (s,e) => {
                ok.Enabled = refresh.Enabled = search.Enabled = true;
                if (e.Error != null) { status.Text = "Could not read the vehicle list: " + e.Error.Message; return; }
                vehicles = (List<VehicleCatalog.Vehicle>)e.Result;
                status.Text = vehicles.Count + " vehicles.";
                Fill();
                search.Focus();
            };
            worker.RunWorkerAsync();
        }
        private static string Leaf(string folder) { return folder.Substring(folder.LastIndexOf('/') + 1); }
        private void Fill()
        {
            list.BeginUpdate(); list.Items.Clear();
            string q = search.Text.Trim();
            var rows = vehicles.Where(v => q.Length == 0 || v.Name.IndexOf(q, StringComparison.CurrentCultureIgnoreCase) >= 0 || v.Folder.IndexOf(q, StringComparison.OrdinalIgnoreCase) >= 0);
            rows = sortColumn == 0 ? rows.OrderBy(v => v.Name, StringComparer.CurrentCultureIgnoreCase) : rows.OrderBy(v => Leaf(v.Folder), StringComparer.OrdinalIgnoreCase);
            foreach (var v in rows)
            {
                // The folder column shows the folder's own name; the full path stays searchable and in the tooltip.
                var item = new ListViewItem(new[] { v.Name, Leaf(v.Folder) }) { Tag = v, ToolTipText = v.Folder };
                list.Items.Add(item);
            }
            list.ShowItemToolTips = true;
            list.EndUpdate();
        }
    }

    public sealed class Manifest
    {
        public int Schema = 1;
        public string PluginVersion = "1.0.1";
        public string Target = "HarGabt 1.0.7 v1.0.7_26.10.12 / NFS Unbound";
        public string Scope, CreatedUtc, MeshSetPluginVersion, Blueprint;
        public string TransformPolicy = "Mesh-local geometry unchanged; hierarchy retained; rigid composite transforms only. Raw composite matrices retained. No blueprint/entity placement inferred.";
        public string VariantPolicy = "Database row/material references only; variation hashes are not body-kit assembly definitions. Shared geometry exported once.";
        public string Units = "Meters";
        public bool Cancelled;
        public int DatabasesScanned;
        public int DatabasesConsidered, DatabasesSkippedByDependencies;
        public List<MeshRecord> Meshes = new List<MeshRecord>();
        public List<string> Errors = new List<string>();
        // Seconds per export stage (where an export spends its time).
        public Dictionary<string,double> Timings = new Dictionary<string,double>();
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
        // Chosen RaceVehicleBlueprint when one folder holds several vehicles (e.g. a base car and its special edition).
        public string Blueprint { get { return Manifest.Blueprint; } set { Manifest.Blueprint = value; } }
        // Library exports (shared parts such as the tire library) have no vehicle blueprint and no per-car shader defaults.
        public bool Library;
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
        private void Time(string stage, Action work)
        {
            var watch = System.Diagnostics.Stopwatch.StartNew();
            try { work(); }
            finally { double t; Manifest.Timings.TryGetValue(stage, out t); Manifest.Timings[stage] = Math.Round(t + watch.Elapsed.TotalSeconds, 2); }
        }
        public void Run(FrostyTaskWindow task)
        {
            var total = System.Diagnostics.Stopwatch.StartNew();
            try { RunStages(task); }
            finally { Manifest.Timings["Total"] = Math.Round(total.Elapsed.TotalSeconds, 2); }
        }
        // Progress files are rewritten at most every 10 seconds (they grow with every part; rewriting them after each
        // part took half of a 368-part export). The final save after each stage is unchanged.
        private System.Diagnostics.Stopwatch geometrySaved = System.Diagnostics.Stopwatch.StartNew(), materialsSaved = System.Diagnostics.Stopwatch.StartNew();
        private static bool Due(ref System.Diagnostics.Stopwatch since)
        {
            if (since.Elapsed.TotalSeconds < 10) return false;
            since = System.Diagnostics.Stopwatch.StartNew();
            return true;
        }
        private void RunStages(FrostyTaskWindow task)
        {
            Directory.CreateDirectory(output);
            var scan = System.Diagnostics.Stopwatch.StartNew();
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
            Manifest.Timings["Scan mesh variation databases"] = Math.Round(scan.Elapsed.TotalSeconds, 2);
            // Include unreferenced mesh assets inside the explicit vehicle scope.
            foreach(var entry in entries.Where(e=>Core.InScope(e.Name,prefix) && (e.Type=="RigidMeshAsset" || e.Type=="CompositeMeshAsset" || e.Type=="SkinnedMeshAsset")))
            {
                if(Cancel) break;
                try { var asset=App.AssetManager.GetEbx(entry); Add(entry,asset.RootObject,asset.RootInstanceGuid); }
                catch(Exception ex) { Manifest.Errors.Add(entry.Name + ": " + ex.Message); }
            }
            AssemblyRun assembly=null;
            if(!Cancel && !Library) Time("Assembly", () => {
                try {assembly=new AssemblyRun(Manifest,output) {CancellationRequested=()=>Cancel,Blueprint=Blueprint};assembly.Run();}
                catch(Exception ex) {if(assembly!=null){assembly.Issue("run",ex.Message);assembly.Save();}Manifest.Errors.Add("Assembly: "+ex.Message);}
            });
            Save();
            foreach(var record in Manifest.Meshes)
            {
                if(Cancel) break;
                Time("Geometry (FBX export)", () => {
                    try { Export(record,task); }
                    catch(Exception ex) { record.Status="failed"; record.Error=ex.ToString(); Manifest.Errors.Add(record.Asset + ": " + ex.Message); }
                });
                if (Due(ref geometrySaved)) Time("Geometry: progress saves", () => Save());
            }
            Time("Geometry: progress saves", () => Save());
            if(!Cancel)
            {
                var materialRun=new MaterialRun(output,prefix);
                try {
                    foreach(var record in Manifest.Meshes) {
                        if(Cancel) {materialRun.Cancel=true;break;}
                        task.Update("Materials: "+record.Asset);
                        var current = record;
                        Time("Materials and textures", () => materialRun.Process(current));
                        if (Due(ref materialsSaved)) Time("Materials: progress saves", () => materialRun.Save());
                    }
                } catch(Exception ex) {materialRun.Issue("run",ex);}
                finally {materialRun.Save(true);}
                if(!Cancel && !Library) {
                    task.Update("Shader default textures");
                    Time("Shader default textures", () => {
                        try { ExportShaderDefaults(output); } catch(Exception ex) { Manifest.Errors.Add("Shader defaults: "+ex.Message); }
                    });
                }
            }
            Manifest.Cancelled=Cancel;
            foreach(var record in Manifest.Meshes.Where(r=>r.Status=="pending")) record.Status="cancelled";
        }
        // Shared textures that vehicle shaders read by default (swatch atlases, trim swatches, flake normals, grime masks).
        // The asset list ships next to the plugin (generated from the Blender add-on's compiled shader profiles).
        public static void ExportShaderDefaults(string output)
        {
            string list=Path.Combine(Path.GetDirectoryName(typeof(Batch).Assembly.Location),"UnboundShaderDefaults.json");
            if(!File.Exists(list)) throw new FileNotFoundException("UnboundShaderDefaults.json missing next to the plugin");
            var names=Newtonsoft.Json.Linq.JArray.Parse(File.ReadAllText(list)).Select(t=>(string)t).ToList();
            var run=new MaterialRun(Path.Combine(output,"shader-defaults"),"shader defaults");
            foreach(string name in names) {
                var entry=App.AssetManager.GetEbxEntry(name);
                if(entry==null) { run.Issue(name,"Texture asset not found"); continue; }
                try { run.ExportTextureAsset(entry); } catch(Exception ex) { run.Issue(name,ex); }
            }
            run.SaveTextureIndex("Exported by An's Garage for Frosty; game data, keep private.");
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
            MaterialRun.ReplaceFile(temp,path);
        }
    }
}
