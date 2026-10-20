using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using FrostySdk;
using FrostySdk.Ebx;
using FrostySdk.IO;
using UnboundBatchExport;

public class FakeEbxObject
{
    private AssetClassGuid guid;
    public AssetClassGuid GetInstanceGuid() { return guid; }
    public void SetInstanceGuid(AssetClassGuid value) { guid=value; }
}
public static class Tests
{
    static int passed;
    static void Check(bool ok, string name) { if(!ok) throw new Exception("FAIL: " + name); ++passed; Console.WriteLine("PASS: " + name); }
    static void Throws(Action action, string name) { try { action(); } catch(InvalidDataException) { Check(true,name); return; } throw new Exception("Expected error: " + name); }
    public static int Main(string[] args)
    {
        string editor=Path.GetFullPath(args[0]), plugin=Path.GetFullPath(args[1]);
        AppDomain.CurrentDomain.AssemblyResolve += (s,e) => {
            string name=new AssemblyName(e.Name).Name + ".dll";
            foreach(string dir in new [] {plugin,editor,Path.Combine(editor,"Plugins"),Path.Combine(editor,"ThirdParty")})
            { string p=Path.Combine(dir,name); if(File.Exists(p)) return Assembly.LoadFrom(p); }
            return null;
        };
        try { Run(); Console.WriteLine("TOTAL PASS: " + passed); return 0; }
        catch(Exception ex) { Console.WriteLine(ex); return 1; }
    }
    [MethodImpl(MethodImplOptions.NoInlining)]
    static void Run()
    {
        Check(Core.InScope("VEHICLES/car/mesh","vehicles/car"),"case-insensitive path scope");
        Check(!Core.InScope("vehicles/carbon/mesh","vehicles/car"),"path boundary avoids adjacent vehicle");
        Check(!Core.InScope("vehicles/car", ""),"empty scope never selects entire game");
        Check(Core.SafeName("../CON:<x>").IndexOf('.')<0,"filesystem name sanitization");
        Check(Core.Id("a")!=Core.Id("b") && Core.Id("a")==Core.Id("a"),"deterministic distinct identities");
        string finalFbx=Path.Combine("parts","LOD0.fbx");
        string pendingFbx=Core.PendingFbxPath(finalFbx);
        Check(Path.GetExtension(pendingFbx)==".fbx","temporary export retains native FBX extension");
        Check(pendingFbx!=finalFbx && Path.GetDirectoryName(pendingFbx)==Path.GetDirectoryName(finalFbx),"pending FBX is distinct in same destination directory");
        const ulong resourceId=0xFEDCBA9876543210UL;
        object resource=new ResourceRef(resourceId);
        Check(Batch.GetResourceId(resource)==resourceId,"boxed real SDK ResourceRef preserves full unsigned 64-bit ID");
        var meshFixture=new { MeshSetResource=new ResourceRef(resourceId) };
        Check(Batch.GetResourceId(Batch.Get(meshFixture,"MeshSetResource"))==resourceId,"reflected mesh resource follows actual export conversion path");
        Check(Batch.GetResourceId((object)resourceId)==resourceId,"plain boxed UInt64 supported");
        Throws(()=>Batch.GetResourceId(null),"missing mesh resource rejected");
        Throws(()=>Batch.GetResourceId(ResourceRef.Zero),"zero resource reference rejected");
        Throws(()=>Batch.GetResourceId("FEDCBA9876543210"),"unexpected resource type rejected explicitly");
        var identity=new double[] {1,0,0,0,1,0,0,0,1,12,34,56};
        Check(Core.IsRigid(identity),"translation preserved in rigid transform acceptance");
        Check(Core.IsRigid(new double[] {0,1,0,-1,0,0,0,0,1,1,2,3}),"rotation accepted");
        var scale=(double[])identity.Clone(); scale[0]=2; Check(!Core.IsRigid(scale),"lossy scale rejected");
        var mirror=(double[])identity.Clone(); mirror[0]=-1; Check(!Core.IsRigid(mirror),"reflection rejected");
        var shear=(double[])identity.Clone(); shear[1]=0.5; Check(!Core.IsRigid(shear),"shear rejected");
        var invalid=(double[])identity.Clone(); invalid[9]=double.NaN; Check(!Core.IsRigid(invalid),"non-finite translation rejected");
        var root=new FakeEbxObject(); var child=new FakeEbxObject(); var ebx=new EbxAsset(root,child);
        Guid file=Guid.NewGuid(); Guid childId=child.GetInstanceGuid().ExportedGuid;
        Check(Object.ReferenceEquals(Batch.Resolve(new PointerRef(child), g=>null),child),"internal reference resolved");
        Check(Object.ReferenceEquals(Batch.Resolve(new PointerRef(new EbxImportReference {FileGuid=file,ClassGuid=childId}),g=>g==file ? ebx : null),child),"external file plus non-root class GUID resolved");
        Check(Object.ReferenceEquals(Batch.Resolve(new PointerRef(file),g=>ebx),root),"empty class GUID uses root");
        Throws(()=>Batch.Resolve(new PointerRef(new EbxImportReference {FileGuid=file,ClassGuid=Guid.NewGuid()}),g=>ebx),"missing class never silently substitutes root");
        Throws(()=>Batch.Resolve(new PointerRef(file),g=>null),"missing file reported");
        Throws(()=>Batch.Resolve(default(PointerRef),g=>ebx),"null pointer reported");
        string tmp=Path.GetTempFileName();
        try {
            File.WriteAllText(tmp,"invalid"); Check(!Core.HasBinaryFbxHeader(tmp),"invalid FBX rejected");
            File.WriteAllBytes(tmp,System.Text.Encoding.ASCII.GetBytes("Kaydara FBX Binary  \0\x1a\0xxxx"));
            Check(Core.HasBinaryFbxHeader(tmp),"binary FBX signature recognized (not content validation)");
        } finally { File.Delete(tmp); }
        var assembly=typeof(Batch).Assembly;
        Check(assembly.GetTypes().Length>0,"plugin types load against release assemblies");
        Check(typeof(MeshSetPlugin.FBXExporter).GetMethod("ExportFBX").GetParameters().Length==10,"native exporter signature available");
        Check(assembly.GetCustomAttributes(false).Length>0,"plugin registration attributes load");
    }
}
