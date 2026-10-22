using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using Frosty.Core;
using Frosty.Core.Windows;
using FrostySdk.Ebx;
using FrostySdk.IO;
using FrostySdk.Managers.Entries;
using Newtonsoft.Json.Linq;

namespace AnsGarage
{
    // Stock liveries: a car's StaticLiveryTexturesAsset (RaceVehicleCustomizationComponentData.StaticLiveryTextures,
    // kept in the car's folder) lists diffuse (_d) and material (_m) textures, and each StaticLiveryCustomizationItemData
    // picks one pair by index. On the car the pair goes to the paint shader's Ext_T_Livery_Diffuse and
    // Ext_T_Livery_Material. The designs are the game's own (AI racers, rivals, story, delivery and police cars).
    public static class Liveries
    {
        public sealed class Livery { public string Key, Label, Group, Diffuse, Material; public int Index; public JObject Car; }

        private static readonly Dictionary<string, string> Groups = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) {
            { "ai_persona", "AI racer" }, { "ai_rivals", "Rival" }, { "rewardcar", "Reward car" }, { "deliverycar", "Delivery" },
            { "loanercar", "Loaner" }, { "cops", "Police" }, { "trailer", "Trailer" }, { "narrative", "Story" },
            { "narrative_cars", "Story" }, { "event_cars", "Event" }, { "deluxeedition", "Deluxe Edition" }, { "icon", "Icon" } };

        // Every livery of the vehicles in the folder scope, in the game's index order. A livery whose car template
        // (TemplateItemData of the same name: the AI racer's, rival's or story car's whole setup) sets a paint, finish
        // or plate text carries them in Car.
        public static List<Livery> Find(string scope)
        {
            var found = new List<Livery>();
            var templates = App.AssetManager.EnumerateEbx().Where(e => e.Type == "TemplateItemData")
                .GroupBy(e => e.Name.Substring(e.Name.LastIndexOf('/') + 1).ToLowerInvariant()).ToDictionary(g => g.Key, g => g.First());
            foreach (var entry in App.AssetManager.EnumerateEbx().Where(e => e.Type == "StaticLiveryTexturesAsset" && Core.InScope(e.Name, scope)))
            {
                var root = App.AssetManager.GetEbx(entry).RootObject;
                var diffuse = Names(Batch.Get(root, "DiffuseTextures"));
                var material = Names(Batch.Get(root, "HighlightTextures"));
                string car = entry.Name.Substring(entry.Name.LastIndexOf('/') + 1);
                for (int i = 0; i < diffuse.Count; i++)
                {
                    if (diffuse[i] == null) continue;
                    string stem = diffuse[i].Substring(diffuse[i].LastIndexOf('/') + 1);
                    if (stem.EndsWith("_d", StringComparison.OrdinalIgnoreCase)) stem = stem.Substring(0, stem.Length - 2);
                    string folder = diffuse[i].Split('/').Reverse().Skip(1).FirstOrDefault() ?? "";
                    string group;
                    if (!Groups.TryGetValue(folder, out group)) group = "Livery";
                    EbxAssetEntry template;
                    found.Add(new Livery { Key = stem.ToLowerInvariant(), Index = i, Group = group, Label = Label(group, stem, car),
                        Diffuse = diffuse[i], Material = i < material.Count ? material[i] : null,
                        Car = templates.TryGetValue(stem.ToLowerInvariant(), out template) ? CarSetup(template) : null });
                }
            }
            return found;
        }

        // DefaultPaint, Material (finish) and DefaultLicensePlateText from a car template's property modifications.
        private static JObject CarSetup(EbxAssetEntry template)
        {
            var setup = new JObject { { "Template", template.Name } };
            var mods = Batch.Get(App.AssetManager.GetEbx(template).RootObject, "PropertyModifications") as System.Collections.IEnumerable;
            if (mods != null)
                foreach (object mod in mods)
                    foreach (object m in (Batch.Get(mod, "Modifications") as System.Collections.IEnumerable) ?? new object[0])
                    {
                        string name = Convert.ToString(Batch.Get(m, "PropertyName")), value = Convert.ToString(Batch.Get(m, "PropertyValue"));
                        if (name == "DefaultLicensePlateText") setup["PlateText"] = value;
                        else if (name == "DefaultPaint" || name == "Material")
                        {
                            var v = value.Trim('(', ')').Split(',').Select(x => double.Parse(x.Trim(), System.Globalization.CultureInfo.InvariantCulture));
                            setup[name == "DefaultPaint" ? "Paint" : "Finish"] = new JArray(v);
                        }
                    }
            return setup.Count > 1 ? setup : null;
        }

        private static List<string> Names(object list)
        {
            var names = new List<string>();
            if (list is System.Collections.IEnumerable)
                foreach (object p in (System.Collections.IEnumerable)list)
                {
                    var r = p is PointerRef ? (PointerRef)p : new PointerRef();
                    var e = r.Type == PointerRefType.External ? App.AssetManager.GetEbxEntry(r.External.FileGuid) : null;
                    names.Add(e == null ? null : e.Name);
                }
            return names;
        }

        // From the texture name without the car's own words: "AI_Rival_Livery_Medusa_lamborghini_murcielagosv_2010" on
        // car_lamborghini_murcielagosv_2010 -> "Rival: Medusa"; "RewardCar_Livery01_..." -> "Reward car 1".
        private static string Label(string group, string stem, string car)
        {
            var carWords = new HashSet<string>(car.ToLowerInvariant().Split('_'));
            var skip = new HashSet<string> { "ai", "persona", "rival", "livery", "car", "rewardcar", "deliverycar", "loanercar", "staticliveryitem", "police", "template", "trailer" };
            string number = null;
            var words = new List<string>();
            foreach (string w in stem.Split('_'))
            {
                string lower = w.ToLowerInvariant();
                var m = System.Text.RegularExpressions.Regex.Match(lower, @"^livery_?0*(\d+)$");
                if (m.Success) { number = m.Groups[1].Value; continue; }
                if (w.Length == 0 || carWords.Contains(lower) || skip.Contains(lower)) continue;
                words.Add(System.Text.RegularExpressions.Regex.Replace(w, "(?<=[a-z])(?=[A-Z])", " "));
            }
            if (words.Count == 0) return group + " " + (number ?? "");
            return group + ": " + string.Join(" ", words) + (number == null ? "" : " " + number);
        }

        // Exports the chosen liveries' textures into <export>/liveries and merges them into liveries.json there, so
        // liveries can be added to an export later.
        public static JObject Export(string export, IEnumerable<Livery> chosen, FrostyTaskWindow task)
        {
            string folder = Path.Combine(export, "liveries");
            Directory.CreateDirectory(folder);
            string indexPath = Path.Combine(folder, "liveries.json");
            var index = File.Exists(indexPath) ? JObject.Parse(File.ReadAllText(indexPath)) : new JObject { { "Schema", 1 } };
            var rows = index["Liveries"] as JArray ?? new JArray();
            var run = new MaterialRun(Path.Combine(folder, "textures"), "liveries");
            foreach (var l in chosen)
            {
                if (rows.Any(r => (string)r["Key"] == l.Key)) continue;
                if (task != null) task.Update("Exporting livery " + l.Label);
                bool ok = true;
                foreach (string asset in new[] { l.Diffuse, l.Material }.Where(a => a != null))
                {
                    var entry = App.AssetManager.GetEbxEntry(asset);
                    if (entry == null) { run.Issue(asset, "Texture asset not found"); ok = false; continue; }
                    try { run.ExportTextureAsset(entry); } catch (Exception ex) { run.Issue(asset, ex); ok = false; }
                }
                if (ok) rows.Add(new JObject { { "Key", l.Key }, { "Label", l.Label }, { "Group", l.Group }, { "Index", l.Index },
                    { "Diffuse", l.Diffuse }, { "Material", l.Material }, { "Car", l.Car } });
            }
            run.SaveTextureIndex("Livery textures exported by An's Garage for Frosty; game data, keep private.", true);
            index["PluginVersion"] = Core.Version;
            index["Parameters"] = new JObject { { "Diffuse", "Ext_T_Livery_Diffuse" }, { "Material", "Ext_T_Livery_Material" } };
            index["Liveries"] = new JArray(rows.OrderBy(r => (string)r["Label"], StringComparer.OrdinalIgnoreCase));
            MaterialRun.WriteJson(indexPath, index);
            return index;
        }

        // Checkboxes for the liveries, all ticked: untick the ones to leave out. Already exported ones are listed as done.
        public static CheckedListBox Picker(List<Livery> liveries, ICollection<string> exported = null)
        {
            var box = new CheckedListBox { Width = 680, Height = 220, CheckOnClick = true, Dock = DockStyle.Fill };
            Fill(box, liveries, exported);
            return box;
        }

        public static void Fill(CheckedListBox box, List<Livery> liveries, ICollection<string> exported = null)
        {
            box.Items.Clear();
            foreach (var l in liveries.Where(l => exported == null || !exported.Contains(l.Key)).OrderBy(l => l.Label, StringComparer.OrdinalIgnoreCase))
                box.Items.Add(new Item(l), true);
        }

        public static List<Livery> Checked(CheckedListBox box) { return box.CheckedItems.Cast<Item>().Select(i => i.Livery).ToList(); }

        private sealed class Item
        {
            public readonly Livery Livery;
            public Item(Livery l) { Livery = l; }
            public override string ToString() { return Livery.Label; }
        }
    }

    // Liveries left out of an export can be added later without exporting the car again.
    public sealed class AddLiveriesMenu : MenuExtension
    {
        public override string TopLevelMenuName { get { return "Tools"; } }
        public override string SubLevelMenuName { get { return "An's Garage"; } }
        public override string MenuItemName { get { return "Add liveries to an existing export..."; } }
        public override RelayCommand MenuItemClicked { get { return new RelayCommand(o => Run()); } }

        private static void Run()
        {
            try
            {
                string export;
                using (var folder = new FolderBrowserDialog { Description = "Choose the car's export folder (the one with manifest.json)" })
                {
                    if (folder.ShowDialog() != DialogResult.OK) return;
                    export = folder.SelectedPath;
                }
                string manifest = Path.Combine(export, "manifest.json");
                if (!File.Exists(manifest)) { MessageBox.Show("No manifest.json in that folder.", "An's Garage"); return; }
                string scope = (string)JObject.Parse(File.ReadAllText(manifest))["Scope"];
                var all = Liveries.Find(scope);
                string indexPath = Path.Combine(export, "liveries", "liveries.json");
                var done = File.Exists(indexPath) ? new HashSet<string>(((JArray)JObject.Parse(File.ReadAllText(indexPath))["Liveries"]).Select(r => (string)r["Key"])) : new HashSet<string>();
                if (all.All(l => done.Contains(l.Key))) { MessageBox.Show(all.Count == 0 ? "This car has no stock liveries." : "Every livery of this car is already exported.", "An's Garage"); return; }
                using (var form = new Form())
                {
                    Ui.Setup(form, "An's Garage: add liveries");
                    var g = Ui.Grid(1);
                    g.Controls.Add(Ui.Text("Liveries not yet in this export (" + done.Count + " already are). Untick the ones you don't want:"));
                    var box = Liveries.Picker(all, done);
                    g.Controls.Add(box);
                    var go = Ui.Button("Add"); go.DialogResult = DialogResult.OK;
                    var cancel = Ui.Button("Cancel"); cancel.DialogResult = DialogResult.Cancel;
                    g.Controls.Add(Ui.Buttons(cancel, go));
                    form.Controls.Add(g); form.AcceptButton = go; form.CancelButton = cancel;
                    if (form.ShowDialog() != DialogResult.OK) return;
                    var chosen = Liveries.Checked(box);
                    JObject index = null;
                    FrostyTaskWindow.Show("An's Garage: add liveries", "Exporting", task => index = Liveries.Export(export, chosen, task));
                    MessageBox.Show(((JArray)index["Liveries"]).Count + " liveries in this export now.", "An's Garage");
                }
            }
            catch (Exception ex) { MessageBox.Show(ex.Message, "An's Garage"); }
        }
    }
}
