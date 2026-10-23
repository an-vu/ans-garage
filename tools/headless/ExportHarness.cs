using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Serialization;
using Frosty.Core;
using Frosty.Core.Windows;
using FrostySdk;
using FrostySdk.Managers;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using AnsGarage;

// Runs An's Garage for Frosty without the Frosty window (read-only game access; never prints keys).
// Modes and arguments: see tools/headless/export.ps1.
class Harness {
// Shallow, readable dump of an EBX object: primitives, enum names, external references as asset names,
// internal references followed (depth-limited).
static JToken Dump(object o, FrostySdk.IO.EbxAsset asset, int depth) {
 if(o==null) return null;
 if(o is string || o.GetType().IsPrimitive) return JToken.FromObject(o);
 if(o.GetType().Name=="CString") return o.ToString();
 if(o.GetType().IsEnum) return o.ToString();
 if(o is FrostySdk.Ebx.PointerRef) {
  var p=(FrostySdk.Ebx.PointerRef)o;
  if(p.Type==FrostySdk.IO.PointerRefType.External) { var e=App.AssetManager.GetEbxEntry(p.External.FileGuid); return "-> "+(e==null?p.External.FileGuid.ToString():e.Name); }
  if(p.Type==FrostySdk.IO.PointerRefType.Internal && depth<4) return Dump(p.Internal,asset,depth+1);
  return p.Type.ToString();
 }
 if(o is System.Collections.IList) { var arr=new JArray(); int n=0; foreach(var x in (System.Collections.IList)o){ if(n++>=24) break; arr.Add(Dump(x,asset,depth+1)); } return arr; }
 if(depth>=5) return o.GetType().Name;
 var obj=new JObject{{"__Type",o.GetType().Name}};
 foreach(var prop in o.GetType().GetProperties()) {
  if(prop.GetIndexParameters().Length>0 || prop.Name.StartsWith("__")) continue;
  object v; try { v=prop.GetValue(o); } catch { continue; }
  if(v is Guid) v=v.ToString();
  try { obj[prop.Name]=Dump(v,asset,depth+1); } catch { obj[prop.Name]=v==null?null:v.ToString(); }
 }
 return obj;
}
// Instance id of an EBX object: its exported GUID, or "internal:<n>".
static string InstanceId(object o) {
 var p=o.GetType().GetProperty("__InstanceGuid"); if(p==null) return "?";
 dynamic g=p.GetValue(o);
 return g.IsExported ? ((Guid)g.ExportedGuid).ToString() : "internal:"+(int)g.InternalId;
}
static System.Collections.Generic.HashSet<ulong> Resources=new System.Collections.Generic.HashSet<ulong>();
// Flat dump of one object: every field, lists in full, internal references as "#<instance id>", resources as "res:<rid>".
static JToken Flat(object o, int depth) {
 if(o==null) return null;
 if(o is string || o.GetType().IsPrimitive) return JToken.FromObject(o);
 if(o.GetType().Name=="CString") return o.ToString();
 if(o.GetType().IsEnum) return o.ToString();
 if(o is Guid) return o.ToString();
 if(o is FrostySdk.Ebx.ResourceRef) { ulong rid=(ulong)(FrostySdk.Ebx.ResourceRef)o; if(rid!=0) Resources.Add(rid); return "res:"+rid.ToString("x16"); }
 if(o is FrostySdk.Ebx.PointerRef) {
  var p=(FrostySdk.Ebx.PointerRef)o;
  if(p.Type==FrostySdk.IO.PointerRefType.External) { var e=App.AssetManager.GetEbxEntry(p.External.FileGuid); return "-> "+(e==null?p.External.FileGuid.ToString():e.Name)+" #"+p.External.ClassGuid; }
  if(p.Type==FrostySdk.IO.PointerRefType.Internal) return "#"+InstanceId(p.Internal);
  return null;
 }
 if(o is System.Collections.IList) { var arr=new JArray(); foreach(var x in (System.Collections.IList)o) arr.Add(Flat(x,depth+1)); return arr; }
 if(depth>=8) return o.GetType().Name;
 var obj=new JObject{{"__Type",o.GetType().Name}};
 foreach(var prop in o.GetType().GetProperties()) {
  if(prop.GetIndexParameters().Length>0 || prop.Name.StartsWith("__")) continue;
  object v; try { v=prop.GetValue(o); } catch { continue; }
  try { obj[prop.Name]=Flat(v,depth+1); } catch { obj[prop.Name]=v==null?null:v.ToString(); }
 }
 return obj;
}
// The plugin reports progress to a Frosty task window; headless runs give it one that is never shown.
static FrostyTaskWindow NoWindow() { return (FrostyTaskWindow)FormatterServices.GetUninitializedObject(typeof(FrostyTaskWindow)); }
class Logger : FrostySdk.Interfaces.ILogger {
public void Log(string text,params object[] args){Console.WriteLine(text,args);}
public void LogWarning(string text,params object[] args){Console.WriteLine(text,args);}
public void LogError(string text,params object[] args){Console.WriteLine(text,args);}
}
static string editor,plugin;
[STAThread]
static int Main(string[] args) {
editor=Path.GetFullPath(args[0]);plugin=Path.GetFullPath(args[1]);
AppDomain.CurrentDomain.AssemblyResolve+=(s,e)=>{
 var name=new AssemblyName(e.Name).Name;
 if(name=="EbxClasses")return Assembly.LoadFrom(Path.Combine(editor,"Profiles","NFSUnboundSDK.dll"));
 foreach(var dir in new[]{plugin,editor,Path.Combine(editor,"Plugins"),Path.Combine(editor,"ThirdParty")}) {
 var p=Path.Combine(dir,name+".dll");if(File.Exists(p))return Assembly.LoadFrom(p);
 }return null;};
try { Run(args);return 0;}catch(Exception ex){Console.WriteLine(ex);return 1;}
}
[MethodImpl(MethodImplOptions.NoInlining)]
static void Run(string[] a) {
 Directory.SetCurrentDirectory(Path.GetFullPath(a[2]));
 ProfilesLibrary.Initialize();if(!ProfilesLibrary.SelectProfile("NeedForSpeedUnbound"))throw new Exception("Profile missing");
 byte[] keys=File.ReadAllBytes(Path.Combine(editor,"nfsunbound.key"));
 var key=new byte[16];Array.Copy(keys,key,16);KeyManager.Instance.AddKey("Key1",key);
 if(keys.Length>=32) {var k=new byte[16];Array.Copy(keys,16,k,0,16);KeyManager.Instance.AddKey("Key2",k);}
 if(keys.Length>=0x4020){var k=new byte[0x4000];Array.Copy(keys,32,k,0,k.Length);KeyManager.Instance.AddKey("Key3",k);}
 Console.WriteLine("Initializing source filesystem");
 var fs=new FileSystemManager(a[3]);foreach(var source in ProfilesLibrary.Sources)fs.AddSource(source.Path,source.SubDirs);fs.Initialize(key);
 var rm=new ResourceManager(fs);rm.Initialize();App.ResourceManager=rm;App.FileSystemManager=fs;
 TypeLibrary.Initialize();
 var am=new AssetManager(fs,rm);App.AssetManager=am;am.Initialize(false);
 Console.WriteLine("Loaded "+am.GetEbxCount()+" EBX assets");

 // A copy of the editor config (localization language); the user's real config is never written.
 Config.Load(Environment.GetEnvironmentVariable("UNBOUND_FROSTY_CONFIG_COPY"));
 App.Logger=new Logger();
 if(System.Windows.Application.Current==null)new System.Windows.Application();
 Assembly.LoadFrom(Path.Combine(editor,"Plugins","FsLocalizationPlugin.dll"));
 App.PluginManager=new Frosty.Core.PluginManager(App.Logger,Frosty.Core.PluginManagerType.Editor);
 App.PluginManager.Initialize();

 string mode=a[4];
 if(mode=="catalog") {
  var sw=System.Diagnostics.Stopwatch.StartNew(); var rows=new JArray(VehicleCatalog.BuildAndCache(m=>Console.WriteLine(m)).Select(v=>new JObject{{"Name",v.Name},{"ShortName",v.ShortName},{"Folder",v.Folder},{"Blueprint",v.Blueprint},{"Item",v.Item}}));
  File.WriteAllText(a[5],rows.ToString(Formatting.Indented));
  Console.WriteLine("CATALOG "+rows.Count+" vehicles in "+sw.Elapsed.TotalSeconds.ToString("0")+" s; localization: "+Names.Status+"; cached: "+(VehicleCatalog.Cached()!=null));
  return;
 }
 if(mode=="scan") {
  // Moving-parts scan: every vehicle's blueprint, keeping only animation objects, the connections touching them and
  // the names of their keyframe tracks (no geometry, no key data). a[5] = output json.
  var keep=new System.Collections.Generic.HashSet<string>{"NamedAnimationPropertyEntityData","TransformAnimationEntityData",
   "NormalisedRotationAnimationEntityData","NormalisedTranslationAnimationEntityData","SequenceEntityData",
   "TransformHubEntityData","TransformBlendEntityData","TransformMultiplierEntityData","RealmTransformCombinerEntityData",
   "AnimationComponentData","AnimateComponentEntityData","MathEntityData","CompareBoolEntityData"};
  var vehicles=VehicleCatalog.Cached()??VehicleCatalog.BuildAndCache(m=>Console.WriteLine(m));
  var result=new JArray();
  foreach(var v in vehicles) {
   try {
    var entry=am.GetEbxEntry(v.Blueprint); if(entry==null) continue;
    var asset=am.GetEbx(entry);
    var objects=new JObject(); var types=new System.Collections.Generic.Dictionary<string,string>();
    foreach(var o in asset.Objects) {
     string id=InstanceId(o), type=o.GetType().Name; types[id]=type;
     if(keep.Contains(type)||type.Contains("Anim")||type.Contains("Sequence")||type.EndsWith("PropertyTrackData")) objects[id]=Flat(o,0);
    }
    var root=Flat(asset.RootObject,0);
    var links=new JArray();
    foreach(string kind in new[]{"PropertyConnections","LinkConnections","EventConnections"})
     foreach(var c in (root[kind] as JArray)??new JArray()) {
      string s=((string)c["Source"]??"").TrimStart('#'), t=((string)c["Target"]??"").TrimStart('#');
      if(!objects.ContainsKey(s)&&!objects.ContainsKey(t)) continue;
      c["Kind"]=kind; c["SourceType"]=types.ContainsKey(s)?types[s]:s; c["TargetType"]=types.ContainsKey(t)?types[t]:t;
      links.Add(c);
     }
    var tracks=new JObject();
    foreach(var rid in Resources) { var re=am.GetResEntry(rid); tracks[rid.ToString("x16")]=re==null?null:re.Name; }
    Resources.Clear();
    result.Add(new JObject{{"Vehicle",v.Name},{"Blueprint",v.Blueprint},{"Objects",objects},{"Connections",links},{"Tracks",tracks}});
   } catch(Exception ex) { result.Add(new JObject{{"Vehicle",v.Name},{"Blueprint",v.Blueprint},{"Error",ex.Message}}); }
  }
  File.WriteAllText(a[5],result.ToString(Formatting.Indented));
  Console.WriteLine("SCANNED "+result.Count);
  return;
 }
 if(mode=="plates") {
  // License plate library: a[5] = output folder, a[6] = "plates" or "frames" for only that part (default both).
  var t=NoWindow();
  string part=a.Length>6?a[6]:"";
  var index=PlateLibrary.Export(Path.GetFullPath(a[5]),t,part!="frames",part!="plates");
  Console.WriteLine("PLATES "+((JArray)index["Plates"]).Count+" FRAMES "+((JArray)index["Frames"]).Count);
  return;
 }
 if(mode=="tires") {
  // Tire library (Falken and Toyo): a[5] = output folder.
  var t=NoWindow();
  var index=TireLibrary.Export(Path.GetFullPath(a[5]),t);
  Console.WriteLine("TIRES "+((JArray)index["Tires"]).Count+" items, "+((JObject)index["Blueprints"]).Count+" meshes");
  return;
 }
 if(mode=="rims") {
  // Rim library (real aftermarket brands): a[5] = output folder.
  var index=RimLibrary.Export(Path.GetFullPath(a[5]),NoWindow());
  Console.WriteLine("RIMS "+((JArray)index["Rims"]).Count+" items in "+((JArray)index["Folders"]).Count+" brand folders");
  return;
 }
 if(mode=="liveries") {
  // Stock liveries of an existing export: a[5] = export folder; a[6] = "list", "all" or keys (key1|key2).
  string export=Path.GetFullPath(a[5]);
  string scope=(string)JObject.Parse(File.ReadAllText(Path.Combine(export,"manifest.json")))["Scope"];
  var all=Liveries.Find(scope);
  foreach(var l in all) Console.WriteLine("LIVERY "+l.Key+" | "+l.Label+" | "+l.Diffuse);
  if(a[6]!="list") {
   var wanted=new System.Collections.Generic.HashSet<string>(a[6].Split('|'),StringComparer.OrdinalIgnoreCase);
   var index=Liveries.Export(export,all.Where(l=>a[6]=="all"||wanted.Contains(l.Key)),NoWindow());
   Console.WriteLine("LIVERIES "+((JArray)index["Liveries"]).Count);
  }
  return;
 }
 if(mode=="textures") {
  // Named texture assets (name1|name2) as DDS into a[6]/textures, with textures.json (game data; keep private).
  var run=new MaterialRun(Path.Combine(Path.GetFullPath(a[6]),"textures"),"textures");
  foreach(var name in a[5].Split('|')) {
   var e=am.GetEbxEntry(name);
   if(e==null) { run.Issue(name,"Texture asset not found"); continue; }
   try { run.ExportTextureAsset(e); } catch(Exception ex) { run.Issue(name,ex); }
  }
  run.SaveTextureIndex("Textures exported by the An's Garage headless tool; game data, keep private.");
  Console.WriteLine("TEXTURES done");
  return;
 }
 if(mode=="assets") {
  // EBX assets whose name contains any of the terms (term1|term2), with their types.
  var terms=a[5].Split('|');
  var found=new JArray(am.EnumerateEbx().Where(e=>terms.Any(t=>e.Name.IndexOf(t,StringComparison.OrdinalIgnoreCase)>=0))
   .OrderBy(e=>e.Name,StringComparer.OrdinalIgnoreCase).Select(e=>new JObject{{"Name",e.Name},{"Type",e.Type},{"Guid",e.Guid.ToString()}}));
  File.WriteAllText(a[6],found.ToString(Formatting.Indented));
  Console.WriteLine("ASSETS "+found.Count);
  return;
 }
 if(mode=="items") {
  // Every EBX asset of one type (e.g. TiresItemData): in-game names plus a shallow field dump with referenced asset
  // names, to study how the game structures an item family.
  var found=new JArray();
  foreach(var e in am.EnumerateEbx().Where(x=>x.Type==a[5])) {
   try {
    var asset=am.GetEbx(e);
    Func<object,object> resolve=p=>Batch.Resolve((FrostySdk.Ebx.PointerRef)p,g=>g==e.Guid?asset:am.GetEbx(am.GetEbxEntry(g)));
    found.Add(new JObject{{"Asset",e.Name},{"RootGuid",asset.RootInstanceGuid.ToString()},{"UI",Names.ItemUi(asset.RootObject,resolve)},{"Fields",Dump(asset.RootObject,asset,0)}});
   } catch(Exception ex) { found.Add(new JObject{{"Asset",e.Name},{"Error",ex.Message}}); }
  }
  File.WriteAllText(a[6],found.ToString(Formatting.Indented));
  Console.WriteLine("ITEMS "+found.Count);
  return;
 }
 if(mode=="dump") {
  // Every object of the named assets (name1|name2), keyed by instance id, to follow a blueprint's connections.
  var result=new JObject();
  foreach(var name in a[5].Split('|')) {
   var e=am.GetEbxEntry(name);
   if(e==null) { result[name]="not found"; continue; }
   var asset=am.GetEbx(e);
   var objects=new JObject();
   foreach(var o in asset.Objects) objects[InstanceId(o)]=Flat(o,0);
   result[e.Name]=new JObject{{"Type",e.Type},{"Root",InstanceId(asset.RootObject)},{"Objects",objects}};
  }
  // Referenced resources (e.g. sequence key data) as hex, with their resource type.
  var res=new JObject();
  foreach(var rid in Resources) {
   var entry=am.GetResEntry(rid);
   if(entry==null) { res[rid.ToString("x16")]="not found"; continue; }
   using(var s=am.GetRes(entry)) { var ms=new MemoryStream(); s.CopyTo(ms);
    res[rid.ToString("x16")]=new JObject{{"Name",entry.Name},{"Type",entry.ResType.ToString("x8")},{"Size",ms.Length},{"Hex",BitConverter.ToString(ms.ToArray()).Replace("-","")}}; }
  }
  result["Resources"]=res;
  File.WriteAllText(a[6],result.ToString(Formatting.Indented));
  Console.WriteLine("DUMPED "+result.Count);
  return;
 }
 if(mode=="hashes") {
  // EBX assets whose name hash (Frosty HashString, lower-case) is in the list: resolves shader default texture hashes.
  var wanted=new System.Collections.Generic.HashSet<uint>(a[5].Split('|').Select(x=>uint.Parse(x)));
  var found=new JArray(am.EnumerateEbx().Where(e=>wanted.Contains((uint)FrostySdk.Utils.HashString(e.Name,true)))
   .Select(e=>new JObject{{"Name",e.Name},{"Type",e.Type},{"Hash",(uint)FrostySdk.Utils.HashString(e.Name,true)},{"Guid",e.Guid.ToString()}}));
  File.WriteAllText(a[6],found.ToString(Formatting.Indented));
  Console.WriteLine("HASHES "+found.Count+" of "+wanted.Count+" resolved");
  return;
 }
 if(mode=="find-text") {
  // Localized strings (shorter than 60 characters) containing any term, keyed by string-id hash.
  var dbType=Assembly.LoadFrom(Path.Combine(editor,"Plugins","FsLocalizationPlugin.dll")).GetType("FsLocalizationPlugin.FsLocalizationStringDatabase");
  var db=Activator.CreateInstance(dbType);
  dbType.GetMethod("Initialize").Invoke(db,null);
  var getId=dbType.GetMethod("GetString",new[]{typeof(uint)});
  var hits=new JObject();
  foreach(object idObj in (System.Collections.IEnumerable)dbType.GetMethod("EnumerateStrings").Invoke(db,null)) {
   uint id=Convert.ToUInt32(idObj); string text=(string)getId.Invoke(db,new object[]{id});
   if(text!=null && text.Length<60 && a[5].Split('|').Any(t=>text.IndexOf(t,StringComparison.OrdinalIgnoreCase)>=0)) hits[id.ToString("x8")]=text;
  }
  File.WriteAllText(a[6],hits.ToString(Formatting.Indented));
  Console.WriteLine("FOUND "+hits.Count);
  return;
 }
 if(mode=="defaults") {
  // Shader default textures only (list next to the plugin): a[5] = export folder.
  Batch.ExportShaderDefaults(Path.GetFullPath(a[5]));
  Console.WriteLine("DEFAULTS done");
  return;
 }
 if(mode=="assembly") {
  // Re-run assembly on an existing export: a[5] = export folder, a[6] = RaceVehicleBlueprint asset name.
  string folder=Path.GetFullPath(a[5]);
  var manifest=JsonConvert.DeserializeObject<Manifest>(File.ReadAllText(Path.Combine(folder,"manifest.json")));
  var existing=new Batch(manifest.Scope,"",folder);
  existing.Manifest.Meshes.AddRange(manifest.Meshes);
  var run=new AssemblyRun(existing.Manifest,folder) {Blueprint=a[6]};
  var t=NoWindow();
  try {
   run.Run(); manifest.Errors.RemoveAll(e=>e.StartsWith("Assembly:"));
   foreach(var mesh in existing.Manifest.Meshes.Where(m=>m.Status=="pending").ToArray()) existing.ExportAdditional(mesh,t);
   foreach(var mesh in existing.Manifest.Meshes.Where(m=>!manifest.Meshes.Any(old=>old.Id==m.Id))) manifest.Meshes.Add(mesh);
   manifest.Blueprint=a[6];
   var materials=new MaterialRun(folder,manifest.Scope);
   foreach(var mesh in manifest.Meshes) materials.Process(mesh);
   materials.Save(true);
   MaterialRun.WriteJson(Path.Combine(folder,"manifest.json"),JObject.FromObject(manifest));
  } catch(Exception ex) { run.Issue("run",ex.Message); Console.WriteLine(ex); }
  finally { run.Save(); }
  Console.WriteLine("ASSEMBLY done; see assembly.log");
  return;
 }
 var batch=new Batch(a[5],"",a[6]);
 // Optional, in any order (PowerShell drops empty arguments): a blueprint name and "static".
 var extra=a.Skip(7).Where(x=>x.Length>0).ToList();
 if(extra.Remove("static")) batch.Manifest.MovingParts=false;
 if(extra.Count>0) batch.Blueprint=extra[0];
 var task=NoWindow();
 task.PropertyChanged+=(sender,eventArgs)=> {if(eventArgs.PropertyName=="Status")Console.WriteLine(task.Status);};
 batch.Run(task);batch.Save();
 Console.WriteLine("BATCH EXPORTED "+batch.Manifest.Meshes.Count(x=>x.Status=="exported")+" ERRORS "+batch.Manifest.Errors.Count);
 foreach(var error in batch.Manifest.Errors)Console.WriteLine(error);
}
}
