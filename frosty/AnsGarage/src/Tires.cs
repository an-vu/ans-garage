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
    public sealed class TireLibraryMenu : MenuExtension
    {
        public override string TopLevelMenuName { get { return "Tools"; } }
        public override string SubLevelMenuName { get { return "An's Garage"; } }
        public override string MenuItemName { get { return "Export tire library..."; } }
        public override RelayCommand MenuItemClicked { get { return new RelayCommand(o => LibraryMenu.Run("tire library",
            "AnsGarage_TireLibrary", TireLibrary.Export, index => ((JArray)index["Tires"]).Count + " tires")); } }
    }

    // Shared by the library menus: pick a folder, export once with progress, report the result.
    internal static class LibraryMenu
    {
        private static int busy;
        public static void Run(string name, string folderName, Func<string, FrostyTaskWindow, JObject> export, Func<JObject, string> summary)
        {
            if (Interlocked.Exchange(ref busy, 1) != 0) return;
            try
            {
                using (var folder = new FolderBrowserDialog { Description = "Choose a folder for the " + name + " (exported once, shared by all cars)" })
                {
                    if (folder.ShowDialog() != DialogResult.OK) return;
                    string target = Path.Combine(folder.SelectedPath, folderName);
                    Exception fatal = null; JObject index = null;
                    FrostyTaskWindow.Show("An's Garage: export " + name, "Reading game data", task => {
                        try { index = export(target, task); } catch (Exception ex) { fatal = ex; }
                    }, true, task => { });
                    MessageBox.Show(fatal != null ? "Export of the " + name + " failed: " + fatal.Message
                        : char.ToUpper(name[0]) + name.Substring(1) + " exported: " + summary(index) + ".\n" + target, "An's Garage");
                }
            }
            catch (Exception ex) { MessageBox.Show(ex.Message, "An's Garage"); }
            finally { Interlocked.Exchange(ref busy, 0); }
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
