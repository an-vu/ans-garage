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
    // License plate backgrounds: real US states and territories, Japanese plates, the fictional NFS places, and the plain
    // and Palace Edition plates. Game logos, animated and themed plates are left out. Plates have no localized names, so
    // labels are written here; the background texture is what the plate shader's Ext_T_LicensePlate_Diffuse samples.
    // Frames (An's choice): none and simple, the Fatlace brands, two NFS games and German Automotive; each frame item
    // names its diffuse and normal map in the shared plate texture collection (Ext_T_Frame_Diffuse / _Normalmap).
    public static class PlateLibrary
    {
        private const string Folder = "vehicles/customization/license_plate/licenseplate_";

        private static readonly string[] States = {
            "alabama|Alabama", "alaska|Alaska", "arizona|Arizona", "arkansas|Arkansas", "california|California",
            "colorado|Colorado", "connecticut|Connecticut", "delaware|Delaware", "florida|Florida", "georgia|Georgia",
            "hawaii|Hawaii", "idaho|Idaho", "idahoclassic|Idaho (classic)", "illinois|Illinois", "indiana|Indiana",
            "iowa|Iowa", "kansas|Kansas", "kentucky|Kentucky", "louisiana|Louisiana", "maine|Maine", "maryland|Maryland",
            "massachusetts|Massachusetts", "michigan|Michigan", "minnesota|Minnesota", "mississippi|Mississippi",
            "missouri|Missouri", "montana|Montana", "nebraska|Nebraska", "nevada|Nevada", "newhampshire|New Hampshire",
            "newjersey|New Jersey", "newmexico|New Mexico", "newyork|New York", "northcarolina|North Carolina",
            "northdakota|North Dakota", "ohio|Ohio", "oklahoma|Oklahoma", "oregon|Oregon", "pennsylvania|Pennsylvania",
            "rhodeisland|Rhode Island", "southcarolina|South Carolina", "southdakota|South Dakota", "tennessee|Tennessee",
            "texas|Texas", "utah|Utah", "vermont|Vermont", "virginia|Virginia", "washington|Washington",
            "westvirginia|West Virginia", "wisconsin|Wisconsin", "wyoming|Wyoming" };
        private static readonly string[] Territories = { "washingtondc|Washington DC", "americansamoa|American Samoa" };
        private static readonly string[] Japan = { "japanese01|Japan 1", "japanese02|Japan 2", "japanese03|Japan 3" };
        private static readonly string[] Places = {
            "lakeshore|Lakeshore", "lakeshoreclassic|Lakeshore (classic)", "palmcity|Palm City", "fortunevalley|Fortune Valley",
            "bayview|Bayview", "olympiccity|Olympic City", "rockport|Rockport", "rockport06|Rockport '06",
            "palmontcity|Palmont City", "fairhaven|Fairhaven", "redview|Redview", "tricitybay|Tri-City Bay",
            "canyonstate|Canyon State", "sunshinecountry|Sunshine Country", "mericacity|Merica City" };
        // key|label|texture (when the texture isn't licenseplate_<key>_d)
        private static readonly string[] Common = { "simple|Simple|licenseplate_simple_d_1", "deluxe|Palifornia" };
        private const string Collection = "vehicles/sharedcustomizedparts/licenseplatetextures";
        private const string FrameItems = "Items/genericvisualitems/licenceplateitems/licenseplateframe_";
        // key|label|group|frame item ("-": the collection's no-frame textures)
        private static readonly string[] Frames = {
            "none|None|Stock|-", "simple|Simple|Stock|Simple",
            "illest|Illest (Fatlace)|Brands|Illest", "meanstreets|Mean Streets|Brands|5", "shirtstuckedin|Shirts Tucked In|Brands|4",
            "germanautomotive|German Automotive|Brands|Vol6_01",
            "mostwanted|Most Wanted|NFS games|MostWanted", "underground|Underground|NFS games|NFSUnderground" };

        public static JObject Export(string output, FrostyTaskWindow task, bool withPlates = true, bool withFrames = true)
        {
            Directory.CreateDirectory(output);
            string indexPath = Path.Combine(output, "plates.json");
            var previous = File.Exists(indexPath) ? JObject.Parse(File.ReadAllText(indexPath)) : new JObject();
            var plates = new JArray();
            var run = new MaterialRun(Path.Combine(output, "textures"), "license plates");
            var groups = new[] { Tuple.Create("US states", States), Tuple.Create("US", Territories), Tuple.Create("Japan", Japan),
                                 Tuple.Create("NFS places", Places), Tuple.Create("Common", Common) };
            foreach (var group in withPlates ? groups : new Tuple<string, string[]>[0])
                foreach (string row in group.Item2)
                {
                    var cells = row.Split('|');
                    string key = cells[0], label = cells[1],
                        asset = cells.Length > 2 ? Folder.Substring(0, Folder.LastIndexOf('/') + 1) + cells[2] : Folder + key + "_d";
                    task.Update("Exporting " + label);
                    var entry = App.AssetManager.GetEbxEntry(asset);
                    if (entry == null) { run.Issue(asset, "Texture asset not found"); continue; }
                    try { run.ExportTextureAsset(entry); }
                    catch (Exception ex) { run.Issue(asset, ex); continue; }
                    plates.Add(new JObject { { "Key", key }, { "Label", label }, { "Group", group.Item1 }, { "Texture", entry.Name } });
                }
            var frames = new JArray();
            var textures = CollectionTextures();
            foreach (string row in withFrames ? Frames : new string[0])
            {
                var cells = row.Split('|');
                task.Update("Exporting frame " + cells[1]);
                string diffuse, normal;
                if (cells[3] == "-")
                {
                    diffuse = textures.FirstOrDefault(t => t != null && t.EndsWith("plate_frame_frame_no_frame_11_d", StringComparison.OrdinalIgnoreCase));
                    normal = textures.FirstOrDefault(t => t != null && t.EndsWith("plate_frame_frame_no_frame_11_n", StringComparison.OrdinalIgnoreCase));
                }
                else
                {
                    var item = App.AssetManager.GetEbxEntry(FrameItems + cells[3]);
                    if (item == null) { run.Issue(FrameItems + cells[3], "Frame item not found"); continue; }
                    var root = App.AssetManager.GetEbx(item).RootObject;
                    diffuse = At(textures, Batch.Get(root, "DiffuseMapIndex"));
                    normal = At(textures, Batch.Get(root, "NormalMapIndex"));
                }
                bool ok = true;
                foreach (string name in new[] { diffuse, normal })
                {
                    var entry = name == null ? null : App.AssetManager.GetEbxEntry(name);
                    if (entry == null) { run.Issue(cells[1], "Frame texture not found: " + name); ok = false; continue; }
                    try { run.ExportTextureAsset(entry); }
                    catch (Exception ex) { run.Issue(name, ex); ok = false; }
                }
                if (ok)
                    frames.Add(new JObject { { "Key", cells[0] }, { "Label", cells[1] }, { "Group", cells[2] },
                        { "Item", cells[3] == "-" ? null : FrameItems + cells[3] }, { "Diffuse", diffuse }, { "Normal", normal } });
            }
            if (!withPlates) plates = (previous["Plates"] as JArray) ?? new JArray();
            if (!withFrames) frames = (previous["Frames"] as JArray) ?? new JArray();
            run.SaveTextureIndex("License plate textures exported by An's Garage for Frosty; game data, keep private.",
                                 !(withPlates && withFrames));
            var index = new JObject { { "Schema", 1 }, { "PluginVersion", new Manifest().PluginVersion },
                { "Parameter", "Ext_T_LicensePlate_Diffuse" }, { "Plates", plates },
                { "FrameParameters", new JObject { { "Diffuse", "Ext_T_Frame_Diffuse" }, { "Normal", "Ext_T_Frame_Normalmap" } } },
                { "Frames", frames } };
            MaterialRun.WriteJson(indexPath, index);
            return index;
        }

        // Asset names of the shared plate texture collection, in order (frame items index into it).
        private static List<string> CollectionTextures()
        {
            var entry = App.AssetManager.GetEbxEntry(Collection);
            var names = new List<string>();
            if (entry == null) return names;
            foreach (object p in (Batch.Get(App.AssetManager.GetEbx(entry).RootObject, "Textures") as IEnumerable) ?? new object[0])
            {
                var e = p is PointerRef && ((PointerRef)p).Type == PointerRefType.External
                    ? App.AssetManager.GetEbxEntry(((PointerRef)p).External.FileGuid) : null;
                names.Add(e == null ? null : e.Name);
            }
            return names;
        }

        private static string At(List<string> names, object index)
        {
            int i = Convert.ToInt32(index);
            return i >= 0 && i < names.Count ? names[i] : null;
        }
    }
}
