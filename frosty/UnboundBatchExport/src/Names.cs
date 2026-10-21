using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Frosty.Core;
using FrostySdk.Ebx;
using FrostySdk.IO;
using FrostySdk.Managers.Entries;
using Newtonsoft.Json.Linq;

namespace UnboundBatchExport
{
    // In-game display names from item UI metadata and the game's localization tables.
    // Nothing is guessed: unresolved ids are kept as ids and marked unresolved.
    public static class Names
    {
        private static ILocalizedStringDatabase database;
        private static bool attempted;
        public static string Status = "not loaded";

        private static ILocalizedStringDatabase Database()
        {
            if (database != null) return database;
            if (LocalizedStringDatabase.Current != null) { database = LocalizedStringDatabase.Current; Status = "editor localization database"; return database; }
            if (attempted) return null;
            attempted = true;
            // Headless runs: create the NFS localization plugin's database the same way the editor does.
            try
            {
                foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
                {
                    var type = assembly.GetType("FsLocalizationPlugin.FsLocalizationStringDatabase", false);
                    if (type == null) continue;
                    var db = (ILocalizedStringDatabase)Activator.CreateInstance(type);
                    db.Initialize();
                    database = db; Status = "FsLocalizationStringDatabase (initialized by exporter)";
                    return database;
                }
                Status = "localization plugin not loaded";
            }
            catch (Exception ex) { Status = "localization failed: " + ex.Message; }
            return null;
        }

        public static string Text(string id)
        {
            if (string.IsNullOrEmpty(id)) return null;
            var db = Database();
            if (db == null) return null;
            try
            {
                string value = db.GetString(id);
                // Frosty returns a placeholder for unknown ids; treat anything echoing the id as unresolved.
                if (string.IsNullOrEmpty(value) || value.IndexOf(id, StringComparison.OrdinalIgnoreCase) >= 0 ||
                    value.StartsWith("Invalid StringId", StringComparison.OrdinalIgnoreCase)) return null;
                return value;
            }
            catch { return null; }
        }

        private static string Field(object obj, string name)
        {
            object v = Batch.Get(obj, name);
            return v == null ? null : v.ToString();
        }

        // Brand key from the UI brand texture (e.g. ui/textures/smartphone/brands/brand-libertywalk -> libertywalk).
        public static string BrandKey(string texture)
        {
            if (string.IsNullOrEmpty(texture)) return null;
            string leaf = texture.Substring(texture.LastIndexOf('/') + 1).ToLowerInvariant();
            foreach (string prefix in new[] { "brand-", "vehicle_brand_", "brand_" })
                if (leaf.StartsWith(prefix)) return leaf.Substring(prefix.Length);
            return leaf;
        }

        public static JObject ItemUi(object item, Func<object, object> resolve)
        {
            object ui = Batch.Get(item, "ItemUI");
            if (ui is PointerRef && ((PointerRef)ui).Type != PointerRefType.Null) ui = resolve(ui); else if (ui is PointerRef) ui = null;
            var row = new JObject();
            foreach (string id in new[] { "LongNameId", "MediumNameId", "ShortNameId", "DescriptionId", "TypeNameId" })
            {
                string value = Field(ui, id) ?? Field(item, id);
                if (string.IsNullOrEmpty(value)) continue;
                row[id] = value;
                row[id.Replace("Id", "")] = Text(value);
            }
            // Every other string-id field of the UI metadata, resolved where the localization table has it.
            if (ui != null)
            {
                var other = new JObject();
                foreach (var prop in ui.GetType().GetProperties())
                {
                    if (!prop.Name.EndsWith("Id") || prop.Name.StartsWith("__") || row[prop.Name] != null || prop.GetIndexParameters().Length > 0) continue;
                    object v; try { v = prop.GetValue(ui); } catch { continue; }
                    if (v == null || (v.GetType().Name != "String" && v.GetType().Name != "CString")) continue;
                    string s = v.ToString();
                    if (s.Length == 0) continue;
                    other[prop.Name] = new JObject { { "Id", s }, { "Text", Text(s) } };
                }
                if (other.Count > 0) row["OtherIds"] = other;
            }
            object texture = Batch.Get(ui, "Texture");
            if (texture is PointerRef && ((PointerRef)texture).Type == PointerRefType.External)
            {
                var entry = App.AssetManager.GetEbxEntry(((PointerRef)texture).External.FileGuid);
                if (entry != null) { row["BrandTexture"] = entry.Name; row["BrandKey"] = BrandKey(entry.Name); }
            }
            // Kit brand name: aftermarket items carry DescriptionId ID_VC_<KIT>_01 (brand description); the
            // brand name string is ID_VC_<KIT>_02 (verified: Liberty Walk, Rocket Bunny).
            string description = (string)row["DescriptionId"];
            var candidates = new List<string>();
            var m = System.Text.RegularExpressions.Regex.Match(description ?? "", "^(ID_VC_[A-Z0-9_]+?)_01$");
            if (m.Success) candidates.Add(m.Groups[1].Value + "_02");
            if (row["BrandKey"] != null) candidates.Add("ID_VC_" + ((string)row["BrandKey"]).ToUpperInvariant().Replace("-", "") + "_02");
            foreach (string id in candidates)
            {
                string brand = Text(id);
                if (brand != null) { row["BrandNameId"] = id; row["BrandName"] = brand; break; }
            }
            row["Category"] = row["MediumName"];
            row["DisplayName"] = DisplayName(row);
            row["LocalizationStatus"] = Status;
            return row;
        }

        // Game UI convention observed in item data: stock items carry a LongName ("Stock");
        // kit items carry the category (MediumName, "Front Bumper") plus a brand logo and brand string.
        // Option name as listed under a category: LongName, else the kit brand ("Liberty Walk"). Null when the
        // localization has neither (some kit parts only carry a brand logo); consumers then show category + logo key.
        public static string DisplayName(JObject ui)
        {
            string longName = (string)ui["LongName"], brand = (string)ui["BrandName"];
            if (!string.IsNullOrEmpty(longName)) return longName;
            if (!string.IsNullOrEmpty(brand)) return brand;
            return null;
        }
    }

    // Every player vehicle by in-game name, matched to its blueprint folder through the bundle hash.
    public static class VehicleCatalog
    {
        public sealed class Vehicle { public string Name, ShortName, Folder, Blueprint, Item; }

        // Disk cache (per user), invalidated when the loaded asset set changes or by an explicit refresh.
        private static string CachePath { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "UnboundBatchExport", "vehicle-catalog.json"); } }
        private static string CacheKey { get { return "0.5.0|" + App.AssetManager.EnumerateEbx().Count(); } }
        private static List<Vehicle> memory;

        public static List<Vehicle> Cached()
        {
            if (memory != null) return memory;
            try
            {
                if (!File.Exists(CachePath)) return null;
                var doc = JObject.Parse(File.ReadAllText(CachePath));
                if ((string)doc["Key"] != CacheKey) return null;
                memory = doc["Vehicles"].ToObject<List<Vehicle>>();
                return memory;
            }
            catch { return null; }
        }

        public static List<Vehicle> BuildAndCache(Action<string> progress)
        {
            var list = Build(progress);
            memory = list;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(CachePath));
                File.WriteAllText(CachePath, new JObject { { "Key", CacheKey }, { "Vehicles", JArray.FromObject(list) } }.ToString());
            }
            catch { }
            return list;
        }

        public static List<Vehicle> Build(Action<string> progress = null)
        {
            var entries = App.AssetManager.EnumerateEbx().ToList();
            var byHash = new Dictionary<uint, EbxAssetEntry>();
            var blueprints = entries.Where(e => e.Type == "RaceVehicleBlueprint").ToList();
            var items = entries.Where(e => e.Type == "RaceVehicleItemData").ToList();
            int done = 0, total = blueprints.Count + items.Count;
            foreach (var bp in blueprints)
            {
                if (progress != null && (++done % 10 == 0)) progress("Reading vehicle data " + done + "/" + total + "...");
                try
                {
                    var root = App.AssetManager.GetEbx(bp).RootObject;
                    var obj = Batch.Resolve((PointerRef)Batch.Get(root, "Object"), g => { var e = App.AssetManager.GetEbxEntry(g); return e == null ? null : App.AssetManager.GetEbx(e); });
                    uint hash = Convert.ToUInt32(Batch.Get(Batch.Get(obj, "VehicleBundleHash"), "Hash"));
                    if (!byHash.ContainsKey(hash)) byHash[hash] = bp;
                }
                catch { }
            }
            var result = new List<Vehicle>();
            if (progress != null) progress("Loading the game's text (in-game names)...");
            Names.Text("ID_STOCK_BUMPER");
            foreach (var e in items)
            {
                if (progress != null && (++done % 10 == 0)) progress("Reading vehicle data " + done + "/" + total + "...");
                try
                {
                    var asset = App.AssetManager.GetEbx(e);
                    var o = asset.RootObject;
                    var ptr = Batch.Get(o, "RaceVehicle");
                    if (!(ptr is PointerRef) || ((PointerRef)ptr).Type == PointerRefType.Null) continue;
                    var reference = Batch.Resolve((PointerRef)ptr, g => { var x = App.AssetManager.GetEbxEntry(g); return x == null ? null : App.AssetManager.GetEbx(x); });
                    var bundle = Batch.Get(reference, "VehicleBundleHash");
                    if (bundle == null) continue;
                    EbxAssetEntry bp;
                    if (!byHash.TryGetValue(Convert.ToUInt32(Batch.Get(bundle, "Hash")), out bp)) continue;
                    var ui = Names.ItemUi(o, p => Batch.Resolve((PointerRef)p, g => g == e.Guid ? asset : App.AssetManager.GetEbx(App.AssetManager.GetEbxEntry(g))));
                    string folder = bp.Name.Substring(0, bp.Name.LastIndexOf('/'));
                    result.Add(new Vehicle { Name = (string)ui["LongName"] ?? (string)ui["MediumName"] ?? e.Name, ShortName = (string)ui["MediumName"], Folder = folder, Blueprint = bp.Name, Item = e.Name });
                }
                catch { }
            }
            return result.OrderBy(v => v.Name, StringComparer.CurrentCultureIgnoreCase).ToList();
        }
    }
}
