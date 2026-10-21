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
  var t=(FrostyTaskWindow)FormatterServices.GetUninitializedObject(typeof(FrostyTaskWindow));
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
 if(a.Length>7) batch.Blueprint=a[7];
 var task=(FrostyTaskWindow)FormatterServices.GetUninitializedObject(typeof(FrostyTaskWindow));
 task.PropertyChanged+=(sender,eventArgs)=> {if(eventArgs.PropertyName=="Status")Console.WriteLine(task.Status);};
 batch.Run(task);batch.Save();
 Console.WriteLine("BATCH EXPORTED "+batch.Manifest.Meshes.Count(x=>x.Status=="exported")+" ERRORS "+batch.Manifest.Errors.Count);
 foreach(var error in batch.Manifest.Errors)Console.WriteLine(error);
}
}
