using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using FrostySdk;
using FrostySdk.Ebx;
using FrostySdk.IO;
using UnboundBatchExport;
using Newtonsoft.Json.Linq;

public class FakeEbxObject
{
    private AssetClassGuid guid;
    public AssetClassGuid GetInstanceGuid() { return guid; }
    public void SetInstanceGuid(AssetClassGuid value) { guid=value; }
}
public class GraphFixture : FakeEbxObject
{
    public PointerRef Link { get; set; }
    public string UnknownPackedMeaning { get; set; }
}
public class FaultyFixture {public string Problem {get {throw new Exception("fixture getter failure");}}}
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
        Check(TextureTools.Supported("BC5_UNORM","TT_2d","Streaming"),"native normal-map DDS format accepted");
        Check(!TextureTools.Supported("UNKNOWN","TT_2d",""),"unknown DDS format is rejected before native silent fallback");
        Check(!TextureTools.Supported("BC1_UNORM","TT_CubeArray",""),"unsupported texture layout rejected");
        Check(!TextureTools.Supported("BC1_UNORM","TT_2d","SwizzledData"),"swizzled payload not mislabeled as normal DDS");
        Check(TextureTools.FileName("Car_Original_N")=="Car_Original_N","valid original texture filename preserved");
        Check(TextureTools.FileName("CON")!="" && TextureTools.FileName("CON")!="CON","reserved Windows texture name handled");
        var a=new GraphFixture();var b=new GraphFixture();
        var assetA=new EbxAsset(a);var assetB=new EbxAsset(b);
        Guid ga=Guid.NewGuid(),gb=Guid.NewGuid();
        a.Link=new PointerRef(new EbxImportReference {FileGuid=gb,ClassGuid=b.GetInstanceGuid().ExportedGuid});
        b.Link=new PointerRef(new EbxImportReference {FileGuid=ga,ClassGuid=a.GetInstanceGuid().ExportedGuid});
        a.UnknownPackedMeaning="unknown stays raw";
        var run=new MaterialRun(Path.GetTempPath(),"fixture",g=>g==ga?assetA:g==gb?assetB:null,g=>null);
        var pointer=new PointerRef(new EbxImportReference {FileGuid=ga,ClassGuid=a.GetInstanceGuid().ExportedGuid});
        var first=run.Reference(pointer,ga,"root");
        run.Reference(pointer,ga,"second");
        Check(((JArray)run.Document["Nodes"]).Count==2,"external material cycles and shared references deduplicate");
        Check((string)run.Document["Nodes"][0]["Raw"]["UnknownPackedMeaning"]=="unknown stays raw","unknown material values retained without semantic inference");
        Check(run.Reference(new PointerRef(Guid.NewGuid()),ga,"missing")["Unresolved"]!=null,"missing material reference logged in graph");
        Check(run.Capture(new FaultyFixture(),ga,"fault")["Problem"]["ReadError"]!=null,"one failing property does not discard material capture");
        var raw=run.Capture(new ResourceRef(resourceId),ga,"rid");
        Check((string)raw["Hex"]=="fedcba9876543210","resource metadata preserves unsigned ID as hex string");
        string dds=Path.GetTempFileName();
        try {
            using(var w=new BinaryWriter(File.Create(dds))) {
                var header=new byte[148]; w.Write(header);
                w.BaseStream.Position=0;w.Write(0x20534444U);w.Write(124);
                w.BaseStream.Position=12;w.Write(2);w.Write(4);
                w.BaseStream.Position=76;w.Write(32);w.BaseStream.Position=84;w.Write(0x30315844U);
                w.BaseStream.Position=128;w.Write(71);w.BaseStream.Position=148;w.Write(new byte[8]);
            }
            TextureTools.ValidateDds(dds,4,2);Check(true,"DX10 DDS header validation accepts matching dimensions");
            Throws(()=>TextureTools.ValidateDds(dds,3,2),"DDS dimension mismatch reported");
        } finally {File.Delete(dds);}
    }
}
