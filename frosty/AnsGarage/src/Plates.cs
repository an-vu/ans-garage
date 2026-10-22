using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;
using Frosty.Core;
using Frosty.Core.Windows;
using Newtonsoft.Json.Linq;

namespace AnsGarage
{
    public sealed class PlateLibraryMenu : MenuExtension
    {
        private static int busy;
        public override string TopLevelMenuName { get { return "Tools"; } }
        public override string SubLevelMenuName { get { return "An's Garage"; } }
        public override string MenuItemName { get { return "Export license plate library..."; } }
        public override RelayCommand MenuItemClicked { get { return new RelayCommand(o => Run()); } }
        private static void Run()
        {
            if (Interlocked.Exchange(ref busy, 1) != 0) return;
            try
            {
                using (var folder = new FolderBrowserDialog { Description = "Choose a folder for the license plate library (exported once, shared by all cars)" })
                {
                    if (folder.ShowDialog() != DialogResult.OK) return;
                    string target = Path.Combine(folder.SelectedPath, "AnsGarage_PlateLibrary");
                    Exception fatal = null; JObject index = null;
                    FrostyTaskWindow.Show("An's Garage: export license plate library", "Reading plates", task => {
                        try { index = PlateLibrary.Export(target, task); } catch (Exception ex) { fatal = ex; }
                    }, true, task => { });
                    MessageBox.Show(fatal != null ? "License plate library export failed: " + fatal.Message
                        : "License plate library exported: " + ((JArray)index["Plates"]).Count + " plates.\n" + target, "An's Garage");
                }
            }
            catch (Exception ex) { MessageBox.Show(ex.Message, "An's Garage"); }
            finally { Interlocked.Exchange(ref busy, 0); }
        }
    }

    // License plate backgrounds: real US states and territories, Japanese plates and the fictional NFS places. Game
    // logos, animated and themed plates are left out. Plates have no localized names, so labels are written here; the
    // background texture is what the plate shader's Ext_T_LicensePlate_Diffuse samples.
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

        public static JObject Export(string output, FrostyTaskWindow task)
        {
            Directory.CreateDirectory(output);
            var plates = new JArray();
            var run = new MaterialRun(Path.Combine(output, "textures"), "license plates");
            var groups = new[] { Tuple.Create("US states", States), Tuple.Create("US", Territories), Tuple.Create("Japan", Japan),
                                 Tuple.Create("NFS places", Places) };
            foreach (var group in groups)
                foreach (string row in group.Item2)
                {
                    string key = row.Split('|')[0], label = row.Split('|')[1], asset = Folder + key + "_d";
                    task.Update("Exporting " + label);
                    var entry = App.AssetManager.GetEbxEntry(asset);
                    if (entry == null) { run.Issue(asset, "Texture asset not found"); continue; }
                    try { run.ExportTextureAsset(entry); }
                    catch (Exception ex) { run.Issue(asset, ex); continue; }
                    plates.Add(new JObject { { "Key", key }, { "Label", label }, { "Group", group.Item1 }, { "Texture", entry.Name } });
                }
            run.SaveTextureIndex("License plate textures exported by An's Garage for Frosty; game data, keep private.");
            var index = new JObject { { "Schema", 1 }, { "PluginVersion", new Manifest().PluginVersion },
                { "Parameter", "Ext_T_LicensePlate_Diffuse" }, { "Plates", plates } };
            MaterialRun.WriteJson(Path.Combine(output, "plates.json"), index);
            return index;
        }
    }
}
