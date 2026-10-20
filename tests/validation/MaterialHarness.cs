using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using Frosty.Core;
using FrostySdk;
using FrostySdk.Managers;
using Newtonsoft.Json;
using UnboundBatchExport;
using System.Linq;
using System.Runtime.Serialization;
using Frosty.Core.Windows;
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
 var manifest=JsonConvert.DeserializeObject<Manifest>(File.ReadAllText(a[4]));
 var run=new MaterialRun(a[5],manifest.Scope);
 int n=0;
 if(a.Length<8 || a[7]!="geometry-only") {
 foreach(var mesh in manifest.Meshes) {Console.WriteLine((++n)+"/"+manifest.Meshes.Count+" "+mesh.Asset);run.Process(mesh);run.Save();}
 run.Save(true);Console.WriteLine(run.Summary());
 }
 var geometry=Path.GetFullPath(a[6]);Directory.CreateDirectory(geometry);
 Config.Load(Path.Combine(Directory.GetCurrentDirectory(),"phase2-test-config.json"));
 App.Logger=new Logger();
 if(System.Windows.Application.Current==null)new System.Windows.Application();
 App.PluginManager=new Frosty.Core.PluginManager(App.Logger,Frosty.Core.PluginManagerType.Editor);
 App.PluginManager.Initialize();
 var batch=new Batch(manifest.Scope,"",geometry);
 // Tests only: progress setters do not need a visible WPF window. No UI is launched.
 var task=(FrostyTaskWindow)FormatterServices.GetUninitializedObject(typeof(FrostyTaskWindow));
 var selected=new[]{manifest.Meshes.First(x=>x.Type=="RigidMeshAsset"),manifest.Meshes.First(x=>x.Type=="CompositeMeshAsset")};
 foreach(var source in selected) {
     var mesh=JsonConvert.DeserializeObject<MeshRecord>(JsonConvert.SerializeObject(source));
     mesh.CompositeTransforms.Clear();
     mesh.Object=am.GetEbx(am.GetEbxEntry(Guid.Parse(mesh.FileGuid))).GetObject(Guid.Parse(mesh.ClassGuid));
     typeof(Batch).GetMethod("Export",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(batch,new object[]{mesh,task});
     Console.WriteLine("GEOMETRY REGRESSION: "+mesh.Type+" "+mesh.Asset+" "+mesh.Status);
     File.WriteAllText(Path.Combine(geometry,mesh.Id+".json"),JsonConvert.SerializeObject(mesh,Formatting.Indented));
 }
}
}

