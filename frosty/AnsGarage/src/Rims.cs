using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Frosty.Core;
using Frosty.Core.Windows;
using FrostySdk.Ebx;
using FrostySdk.IO;
using Newtonsoft.Json.Linq;

namespace AnsGarage
{
    public sealed class RimLibraryMenu : MenuExtension
    {
        public override string TopLevelMenuName { get { return "Tools"; } }
        public override string SubLevelMenuName { get { return "An's Garage"; } }
        public override string MenuItemName { get { return "Export rim library..."; } }
        public override RelayCommand MenuItemClicked { get { return new RelayCommand(o => LibraryMenu.Run("rim library",
            "AnsGarage_RimLibrary", RimLibrary.Export, index => ((JArray)index["Rims"]).Count + " rims")); } }
    }

    // Real-brand aftermarket rim library. The game keeps each brand's wheel meshes in its own folder; the NFS-made ones
    // (turbofans, LED and "ghost" wheels, drag and off-road wheels, the generic folder) live elsewhere and are left out,
    // with every rim item that uses them. A car's own factory wheels come with the car's export, never from here.
    public static class RimLibrary
    {
        private const string Root = "vehicles/sharedcustomizedparts/wheels/";
        public static readonly Dictionary<string, string> Brands = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) {
            { "3sdm", "3SDM" }, { "bbs", "BBS" }, { "cosmis", "Cosmis" }, { "fifteen52", "Fifteen52" }, { "hre", "HRE" },
            { "loma", "Loma" }, { "nismo", "Nismo" }, { "rotiform", "Rotiform" }, { "rtr", "RTR" }, { "ssr", "SSR" },
            { "vorsteiner", "Vorsteiner" }, { "vossen", "Vossen" }, { "watanabe", "Watanabe" }, { "wedsco", "Weds" },
            { "weld", "Weld Racing" }, { "workwheels", "Work" } };

        private static string Ref(object p)
        {
            if (!(p is PointerRef) || ((PointerRef)p).Type != PointerRefType.External) return null;
            var e = App.AssetManager.GetEbxEntry(((PointerRef)p).External.FileGuid);
            return e == null ? null : e.Name;
        }

        private static IEnumerable List(object o, string field) { return (Batch.Get(o, field) as IEnumerable) ?? new object[0]; }

        private static string Folder(string mesh)
        {
            if (mesh == null || !mesh.StartsWith(Root, StringComparison.OrdinalIgnoreCase)) return null;
            string rest = mesh.Substring(Root.Length);
            int slash = rest.IndexOf('/');
            return slash < 0 ? null : rest.Substring(0, slash).ToLowerInvariant();
        }

        private static JArray Vec(object v)
        {
            return v == null ? null : new JArray(new[] { "x", "y", "z" }.Select(c => Convert.ToDouble(Batch.Get(v, c) ?? 0.0)));
        }

        public static JObject Export(string output, FrostyTaskWindow task)
        {
            Directory.CreateDirectory(output);
            var index = new JObject { { "Schema", 1 }, { "PluginVersion", new Manifest().PluginVersion } };
            // 1. Blueprint GUID (what rim items reference) -> mesh asset, for every wheel blueprint (customizable or plain object).
            task.Update("Indexing wheel meshes");
            var blueprints = new JObject();
            foreach (var e in App.AssetManager.EnumerateEbx().Where(x => (x.Type == "CustomizableMeshBlueprint" || x.Type == "ObjectBlueprint") && x.Name.StartsWith(Root, StringComparison.OrdinalIgnoreCase)))
            {
                var asset = App.AssetManager.GetEbx(e);
                var proxy = Batch.Get(asset.RootObject, "Object");
                if (proxy is PointerRef) proxy = Batch.Resolve((PointerRef)proxy, g => App.AssetManager.GetEbx(App.AssetManager.GetEbxEntry(g)));
                string mesh = Ref(Batch.Get(proxy, "Mesh"));
                if (mesh != null) blueprints[asset.RootInstanceGuid.ToString()] = mesh;
            }
            // 2. Shared rim items whose every mesh is in a real brand's folder.
            task.Update("Indexing rims");
            var rims = new JArray();
            foreach (var e in App.AssetManager.EnumerateEbx().Where(x => x.Type == "RimsItemData" && x.Name.IndexOf("/shared_wheels/", StringComparison.OrdinalIgnoreCase) >= 0)
                     .OrderBy(x => x.Name, StringComparer.OrdinalIgnoreCase))
            {
                var asset = App.AssetManager.GetEbx(e);
                var item = asset.RootObject;
                var perm = List(item, "MeshBlueprintPermutations").Cast<object>().FirstOrDefault();
                if (perm == null) continue;
                var meshes = new JArray();
                var folders = new HashSet<string>();
                foreach (object desc in List(perm, "Meshes"))
                {
                    string guid = Batch.Get(desc, "MeshGuid").ToString();
                    string mesh = (string)blueprints[guid];
                    folders.Add(Folder(mesh));
                    meshes.Add(new JObject { { "BlueprintGuid", guid }, { "Mesh", mesh }, { "Tag", Ref(Batch.Get(desc, "Tag")) },
                        { "Rotate", Convert.ToBoolean(Batch.Get(desc, "Rotate")) } });
                }
                if (meshes.Count == 0 || folders.Count != 1 || folders.First() == null || !Brands.ContainsKey(folders.First())) continue;
                Func<object, object> resolve = p => Batch.Resolve((PointerRef)p, g => g == e.Guid ? asset : App.AssetManager.GetEbx(App.AssetManager.GetEbxEntry(g)));
                var ui = Names.ItemUi(item, resolve);
                object location = Batch.Get(item, "Location");
                rims.Add(new JObject { { "Asset", e.Name }, { "Brand", Brands[folders.First()] }, { "Folder", folders.First() },
                    { "Name", (string)ui["LongName"] ?? e.Name.Substring(e.Name.LastIndexOf('/') + 1) },
                    { "Position", location == null ? null : location.ToString() },
                    { "Diameter", Convert.ToDouble(Batch.Get(item, "Diameter")) }, { "Width", Convert.ToDouble(Batch.Get(item, "Width")) },
                    { "BrakeDiscRatio", Convert.ToDouble(Batch.Get(item, "BrakeDiscRatio")) },
                    { "SizeOptions", new JArray(List(item, "SizeOptions").Cast<object>().Select(Convert.ToDouble)) },
                    { "PrimaryPaint", Vec(Batch.Get(item, "PrimaryPaint")) }, { "SecondaryPaint", Vec(Batch.Get(item, "SecondaryPaint")) },
                    { "PrimaryMaterial", Vec(Batch.Get(item, "PrimaryMaterial")) }, { "SecondaryMaterial", Vec(Batch.Get(item, "SecondaryMaterial")) },
                    { "Meshes", meshes }, { "UI", ui } });
            }
            index["Rims"] = rims;
            // 3. Meshes and their materials, one export folder per brand folder that has rims (normal batch path, no car).
            var used = rims.Select(r => (string)r["Folder"]).Distinct().OrderBy(f => f).ToList();
            index["Folders"] = new JArray(used);
            foreach (string folder in used)
            {
                task.Update("Exporting " + Brands[folder] + " rims");
                var batch = new Batch(Root + folder, "", Path.Combine(output, folder)) { Library = true };
                batch.Run(task); batch.Save();
                if (batch.Manifest.Errors.Count > 0) throw new InvalidDataException(folder + ": " + batch.Manifest.Errors[0]);
            }
            index["Blueprints"] = blueprints;
            MaterialRun.WriteJson(Path.Combine(output, "rims.json"), index);
            return index;
        }
    }
}
