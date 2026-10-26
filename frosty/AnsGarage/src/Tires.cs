using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;
using Frosty.Core;
using Frosty.Core.Windows;
using FrostySdk.Ebx;
using FrostySdk.IO;
using FrostySdk.Managers.Entries;
using Newtonsoft.Json.Linq;

namespace AnsGarage
{
    public sealed class SharedPartsMenu : MenuExtension
    {
        public override string TopLevelMenuName { get { return "Tools"; } }
        public override string SubLevelMenuName { get { return "An's Garage"; } }
        public override string MenuItemName { get { return "Export shared parts..."; } }
        public override RelayCommand MenuItemClicked { get { return new RelayCommand(o => SharedParts.Run()); } }
    }

    // What every car can use (shader textures, tires, rims, plates, plate frames): tick what to export, pick one folder,
    // and each goes into its own subfolder there, where the Blender add-on finds it.
    internal static class SharedParts
    {
        private static readonly string[] Labels = { "Shader textures (every car needs them)", "Tires", "Rims", "License plates", "Plate frames" };
        private static readonly bool[] Ticked = { true, true, true, true, true };
        private static string lastFolder;
        private static int busy;

        public static void Run()
        {
            if (Interlocked.Exchange(ref busy, 1) != 0) return;
            try
            {
                if (!Choose()) return;
                string root = lastFolder;
                bool shader = Ticked[0], tires = Ticked[1], rims = Ticked[2], plates = Ticked[3], frames = Ticked[4];
                var lines = new List<string>();
                FrostyTaskWindow.Show("An's Garage: export shared parts", "Reading game data", task => {
                    Action<string, Func<string>> step = (label, export) => {
                        try { lines.Add(label + ": " + export()); }
                        catch (Exception ex) { lines.Add(label + ": failed: " + ex.Message); }
                    };
                    if (shader)
                        step("Shader textures", () => {
                            string dir = Path.Combine(root, "AnsGarage_ShaderTextures");
                            Batch.ExportShaderDefaults(dir);
                            var index = JObject.Parse(File.ReadAllText(Path.Combine(dir, "textures.json")));
                            return ((JArray)index["Textures"]).Count + " textures";
                        });
                    if (tires)
                        step("Tires", () => ((JArray)TireLibrary.Export(Path.Combine(root, "AnsGarage_TireLibrary"), task)["Tires"]).Count + " tires");
                    if (rims)
                        step("Rims", () => ((JArray)RimLibrary.Export(Path.Combine(root, "AnsGarage_RimLibrary"), task)["Rims"]).Count + " rims");
                    // Plates and frames share one library; the part not ticked is kept from the existing one.
                    if (plates || frames)
                        step(plates && frames ? "License plates and frames" : plates ? "License plates" : "Plate frames", () => {
                            var index = PlateLibrary.Export(Path.Combine(root, "AnsGarage_PlateLibrary"), task, plates, frames);
                            return ((JArray)index["Plates"]).Count + " plates, " + ((JArray)index["Frames"]).Count + " frames";
                        });
                }, true, task => { });
                MessageBox.Show("Exported to " + root + "\n\n" + string.Join("\n", lines), "An's Garage");
            }
            catch (Exception ex) { MessageBox.Show(ex.Message, "An's Garage"); }
            finally { Interlocked.Exchange(ref busy, 0); }
        }

        // Tick what to export, then pick the folder. False when cancelled or nothing is ticked.
        private static bool Choose()
        {
            using (var form = new Form { Text = "An's Garage: export shared parts", FormBorderStyle = FormBorderStyle.FixedDialog,
                                         MaximizeBox = false, MinimizeBox = false, StartPosition = FormStartPosition.CenterScreen,
                                         AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Padding = new Padding(12) })
            {
                var layout = new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, AutoSize = true, Dock = DockStyle.Fill };
                layout.Controls.Add(new Label { AutoSize = true, Margin = new Padding(0, 0, 0, 8),
                    Text = "What every car can use. Export it once into one folder; the Blender add-on\n" +
                           "finds it there (its preferences: Shared parts folder)." });
                var boxes = Labels.Select((label, i) => new CheckBox { Text = label, Checked = Ticked[i], AutoSize = true }).ToList();
                foreach (var b in boxes) layout.Controls.Add(b);
                var buttons = new FlowLayoutPanel { FlowDirection = FlowDirection.LeftToRight, AutoSize = true, Margin = new Padding(0, 8, 0, 0) };
                var all = new Button { Text = "All / none", AutoSize = true };
                all.Click += (s, e) => { bool on = !boxes.All(b => b.Checked); foreach (var b in boxes) b.Checked = on; };
                var ok = new Button { Text = "Export...", AutoSize = true, DialogResult = DialogResult.OK };
                var cancel = new Button { Text = "Cancel", AutoSize = true, DialogResult = DialogResult.Cancel };
                buttons.Controls.AddRange(new Control[] { all, ok, cancel });
                layout.Controls.Add(buttons);
                form.Controls.Add(layout);
                form.AcceptButton = ok;
                form.CancelButton = cancel;
                if (form.ShowDialog() != DialogResult.OK) return false;
                for (int i = 0; i < boxes.Count; i++) Ticked[i] = boxes[i].Checked;
            }
            if (!Ticked.Any(t => t)) { MessageBox.Show("Nothing ticked, so nothing was exported.", "An's Garage"); return false; }
            using (var folder = new FolderBrowserDialog { Description = "Choose the shared parts folder (each library gets its own subfolder)",
                                                          SelectedPath = lastFolder ?? "" })
            {
                if (folder.ShowDialog() != DialogResult.OK) return false;
                lastFolder = folder.SelectedPath;
            }
            return true;
        }
    }

    // Real-brand tire library: Falken and Toyo tires, plain or with the brand's own sidewall lettering.
    // Exported once (meshes, materials, textures) and indexed in tires.json; the Blender add-on swaps a car's tires
    // for these at the car's own stock tire size.
    public static class TireLibrary
    {
        public static readonly string[] Brands = { "falken", "toyo" };
        private const string Root = "vehicles/sharedcustomizedparts/tires/";
        // Sidewall lettering kept: the brand's own (Falken; Toyo Proxes). NFS, Speedhunters and other brands are left out.
        private static readonly Dictionary<string, string> BrandLettering = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            { { "falken", "_tirebomb_falken" }, { "toyo", "_tirebomb_proxes" } };

        private static string Ref(object p)
        {
            if (!(p is PointerRef) || ((PointerRef)p).Type != PointerRefType.External) return null;
            var e = App.AssetManager.GetEbxEntry(((PointerRef)p).External.FileGuid);
            return e == null ? null : e.Name;
        }

        private static IEnumerable List(object o, string field) { return (Batch.Get(o, field) as IEnumerable) ?? new object[0]; }

        public static JObject Export(string output, FrostyTaskWindow task)
        {
            Directory.CreateDirectory(output);
            var index = new JObject { { "Schema", 1 }, { "PluginVersion", new Manifest().PluginVersion }, { "Brands", new JArray(Brands) } };
            // 1. Meshes and their materials, one export folder per brand (the normal batch path, without car assembly).
            foreach (string brand in Brands)
            {
                task.Update("Exporting " + brand + " tires");
                var batch = new Batch(Root + brand, "", Path.Combine(output, brand)) { Library = true };
                batch.Run(task); batch.Save();
                if (batch.Manifest.Errors.Count > 0) throw new InvalidDataException(brand + ": " + batch.Manifest.Errors[0]);
            }
            // 2. Blueprint GUID (what tire items reference) -> mesh asset.
            task.Update("Indexing tires");
            var blueprints = new JObject();
            foreach (var e in App.AssetManager.EnumerateEbx().Where(x => x.Type == "CustomizableMeshBlueprint" &&
                     Brands.Any(b => x.Name.StartsWith(Root + b + "/", StringComparison.OrdinalIgnoreCase))))
            {
                var asset = App.AssetManager.GetEbx(e);
                var proxy = Batch.Get(asset.RootObject, "Object");
                if (proxy is PointerRef) proxy = Batch.Resolve((PointerRef)proxy, g => App.AssetManager.GetEbx(App.AssetManager.GetEbxEntry(g)));
                string mesh = Ref(Batch.Get(proxy, "Mesh"));
                if (mesh != null) blueprints[asset.RootInstanceGuid.ToString()] = mesh;
            }
            // 3. Tire items: plain and brand-lettered, front and rear, with sizes and shader overrides.
            var tires = new JArray();
            var overrides = new Dictionary<string, JObject>(StringComparer.OrdinalIgnoreCase);
            foreach (var e in App.AssetManager.EnumerateEbx().Where(x => x.Type == "TiresItemData").OrderBy(x => x.Name, StringComparer.OrdinalIgnoreCase))
            {
                string leaf = e.Name.Substring(e.Name.LastIndexOf('/') + 1).ToLowerInvariant();
                string brand = Brands.FirstOrDefault(b => leaf.StartsWith("shared_tire_" + b + "_"));
                if (brand == null) continue;
                int bomb = leaf.IndexOf("_tirebomb_", StringComparison.Ordinal);
                if (bomb >= 0 && !leaf.Contains(BrandLettering[brand])) continue;
                var asset = App.AssetManager.GetEbx(e);
                var item = asset.RootObject;
                Func<object, object> resolve = p => Batch.Resolve((PointerRef)p, g => g == e.Guid ? asset : App.AssetManager.GetEbx(App.AssetManager.GetEbxEntry(g)));
                var ui = Names.ItemUi(item, resolve);
                var sizes = new JArray();
                foreach (object info in List(item, "TireMeshInfos"))
                {
                    string shader = Ref(Batch.Get(info, "MeshShaderOverrideAsset"));
                    if (shader != null && !overrides.ContainsKey(shader)) overrides[shader] = ReadOverride(shader);
                    var meshes = new JArray();
                    foreach (object desc in List(info, "Meshes"))
                    {
                        string guid = Batch.Get(desc, "MeshGuid").ToString();
                        meshes.Add(new JObject { { "BlueprintGuid", guid }, { "Mesh", blueprints[guid] }, { "Tag", Ref(Batch.Get(desc, "Tag")) },
                            { "Rotate", Convert.ToBoolean(Batch.Get(desc, "Rotate")) } });
                    }
                    sizes.Add(new JObject { { "Width", Convert.ToDouble(Batch.Get(info, "Width")) },
                        { "InnerDiameter", Convert.ToDouble(Batch.Get(info, "InnerDiameter")) },
                        { "OuterDiameter", Convert.ToDouble(Batch.Get(info, "OuterDiameter")) },
                        { "ShaderOverride", shader }, { "Meshes", meshes } });
                }
                object location = Batch.Get(item, "Location");
                tires.Add(new JObject { { "Asset", e.Name }, { "Brand", char.ToUpper(brand[0]) + brand.Substring(1) },
                    { "Name", (string)ui["LongName"] ?? leaf }, { "Position", location == null ? null : location.ToString() },
                    { "Lettering", bomb >= 0 ? "Brand" : "Plain" }, { "Sizes", sizes },
                    { "SmallToMedRatio", Convert.ToDouble(Batch.Get(item, "SmallToMedRatio")) },
                    { "MedToLargeRatio", Convert.ToDouble(Batch.Get(item, "MedToLargeRatio")) }, { "UI", ui } });
            }
            index["Tires"] = tires;
            index["Blueprints"] = blueprints;
            index["ShaderOverrides"] = JObject.FromObject(overrides);
            // 4. Textures the lettering overrides bind (exported once; the base textures come with each mesh's materials).
            task.Update("Exporting lettering textures");
            var run = new MaterialRun(Path.Combine(output, "override-textures"), "tire lettering");
            // Plain tires keep the shader's own lettering default (Default_Black = no lettering): export it too.
            var textures = overrides.Values.SelectMany(o => ((JArray)o["Mappings"]).SelectMany(m => ((JObject)m["Textures"]).Properties().Select(p => (string)p.Value)))
                .Concat(new[] { "Vehicles/CommonTextures/Constants/Default_Black" }).Distinct(StringComparer.OrdinalIgnoreCase);
            foreach (string texture in textures)
            {
                var entry = App.AssetManager.GetEbxEntry(texture);
                if (entry == null) { run.Issue(texture, "Texture asset not found"); continue; }
                try { run.ExportTextureAsset(entry); } catch (Exception ex) { run.Issue(texture, ex); }
            }
            run.SaveTextureIndex("Tire lettering textures exported by An's Garage for Frosty; game data, keep private.");
            MaterialRun.WriteJson(Path.Combine(output, "tires.json"), index);
            return index;
        }

        // Per mesh blueprint: shader texture parameter -> texture asset.
        private static JObject ReadOverride(string name)
        {
            var root = App.AssetManager.GetEbx(App.AssetManager.GetEbxEntry(name)).RootObject;
            var mappings = new JArray();
            foreach (object m in List(root, "MeshShaderOverrideMappings"))
            {
                var textures = new JObject();
                foreach (object t in List(m, "ShaderTextureParameterOverrides"))
                    textures[Batch.Get(t, "ShaderParameter").ToString()] = Ref(Batch.Get(t, "Texture"));
                mappings.Add(new JObject { { "BlueprintGuid", Batch.Get(m, "MeshGuid").ToString() }, { "Textures", textures } });
            }
            return new JObject { { "Asset", name }, { "Mappings", mappings } };
        }
    }
}
