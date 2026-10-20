using System;
using System.IO;
using System.Reflection;

// Standalone native SDK filename test. No game, Frosty UI or mesh decoding involved.
public static class NativeFilenameSmoke
{
    static Assembly assembly;
    static object New(string name, params object[] args) { return Activator.CreateInstance(assembly.GetType("MeshSetPlugin.Fbx."+name,true),args); }
    static object Call(object obj,string method,params object[] args) { return obj.GetType().GetMethod(method).Invoke(obj,args); }
    public static int Main(string[] args)
    {
        string editor=Path.GetFullPath(args[0]), output=Path.GetFullPath(args[1]);
        Directory.CreateDirectory(output);
        Directory.SetCurrentDirectory(editor);
        AppDomain.CurrentDomain.AssemblyResolve += (s,e) => {
            string name=new AssemblyName(e.Name).Name+".dll";
            foreach(string dir in new [] {editor,Path.Combine(editor,"Plugins"),Path.Combine(editor,"ThirdParty")})
            { string path=Path.Combine(dir,name); if(File.Exists(path)) return Assembly.LoadFrom(path); }
            return null;
        };
        try {
            assembly=Assembly.LoadFrom(Path.Combine(editor,"Plugins","MeshSetPlugin.dll"));
            object manager=New("FbxManager");
            try {
                object settings=New("FbxIOSettings",manager,"IOSRoot"); Call(manager,"SetIOSettings",settings);
                object scene=New("FbxScene",manager,"Filename smoke test");
                object registry=manager.GetType().GetProperty("IOPluginRegistry").GetValue(manager,null);
                int count=(int)registry.GetType().GetProperty("WriterFormatCount").GetValue(registry,null), writer=-1;
                for(int i=0;i<count;i++) if(((string)Call(registry,"GetWriterFormatDescription",i)).Contains("binary")) {writer=i;break;}
                if(writer<0) throw new Exception("No binary writer");
                foreach(string name in new [] {"old.fbx.partial","new.partial.fbx"}) {
                    string path=Path.Combine(output,name); object exporter=New("FbxExporter",manager,"");
                    try {
                        if(!(bool)Call(exporter,"Initialize",path,writer,settings)) throw new Exception("Initialize failed");
                        if(!(bool)Call(exporter,"Export",scene,false)) throw new Exception("Export failed");
                    } finally { ((IDisposable)exporter).Dispose(); }
                    bool exact=File.Exists(path), appended=File.Exists(path+".fbx");
                    Console.WriteLine(name+": exact="+exact+", appended="+appended);
                    if(name.StartsWith("old") ? (exact || !appended) : (!exact || appended)) throw new Exception("Unexpected SDK filename behavior");
                }
            } finally { ((IDisposable)manager).Dispose(); }
            Console.WriteLine("PASS: real native SDK reproduces old bug and writes corrected filename exactly."); return 0;
        } catch(Exception ex) {Console.WriteLine(ex);return 1;}
    }
}
