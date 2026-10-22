using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using Frosty.Core;
using Frosty.Core.Attributes;
using Frosty.Core.Windows;
using FrostySdk.Ebx;
using FrostySdk.IO;
using FrostySdk.Managers.Entries;
using FrostySdk.Resources;
using MeshSetPlugin.Resources;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TexturePlugin;

[assembly: RegisterMenuExtension(typeof(AnsGarage.MaterialsMenu))]
namespace AnsGarage
{
    public sealed class MaterialsMenu : MenuExtension
    {
        public override string TopLevelMenuName { get { return "Tools"; } }
        public override string SubLevelMenuName { get { return "An's Garage"; } }
        public override string MenuItemName { get { return "Refresh materials of existing export..."; } }
        public override RelayCommand MenuItemClicked { get { return new RelayCommand(o => {
            try {
                if(!FrostySdk.ProfilesLibrary.IsLoaded(FrostySdk.ProfileVersion.NeedForSpeedUnbound)) throw new InvalidOperationException("Load NFS Unbound first.");
                using(var dialog=new System.Windows.Forms.OpenFileDialog { Filter="Batch manifest|manifest.json",Title="Select the existing vehicle export manifest" }) {
                    if(dialog.ShowDialog()!=System.Windows.Forms.DialogResult.OK) return;
                    var manifest=JsonConvert.DeserializeObject<Manifest>(File.ReadAllText(dialog.FileName));
                    if(manifest==null || manifest.Schema!=1) throw new InvalidDataException("Unsupported batch manifest.");
                    var run=new MaterialRun(Path.GetDirectoryName(dialog.FileName),manifest.Scope);
                    FrostyTaskWindow.Show("Extracting vehicle materials","",task=> {
                        try { foreach(var mesh in manifest.Meshes) { if(run.Cancel) break; task.Update(mesh.Asset); run.Process(mesh); run.Save(); } }
                        catch(Exception ex) { run.Issue("run",ex); }
                        finally { run.Save(true); }
                    },true,task=>run.Cancel=true);
                    System.Windows.Forms.MessageBox.Show("Material extraction finished. Review materials.json and materials.log.\n"+run.Summary(),"An\'s Garage");
                }
            } catch(Exception ex) { System.Windows.Forms.MessageBox.Show(ex.Message,"An's Garage"); }
        }); } }
    }

    public sealed class MaterialRun
    {
        public volatile bool Cancel;
        public readonly JObject Document;
        private readonly string output;
        private readonly Dictionary<Guid,EbxAsset> assets=new Dictionary<Guid,EbxAsset>();
        private readonly Dictionary<string,JObject> nodes=new Dictionary<string,JObject>();
        private readonly Dictionary<ulong,JObject> textures=new Dictionary<ulong,JObject>();
        private readonly JArray issues=new JArray(), meshRecords=new JArray(), textureRecords=new JArray(), nodeRecords=new JArray();
        private readonly Func<Guid,EbxAsset> loader;
        private readonly Func<Guid,EbxAssetEntry> entryLookup;
        // Public injection points are for tests; production uses Frosty's existing managers.
        public MaterialRun(string directory,string scope,Func<Guid,EbxAsset> load=null,Func<Guid,EbxAssetEntry> lookup=null)
        {
            output=directory;
            loader=load ?? (g=> { var e=App.AssetManager.GetEbxEntry(g); return e==null?null:App.AssetManager.GetEbx(e); });
            entryLookup=lookup ?? (g=>App.AssetManager.GetEbxEntry(g));
            Document=new JObject {{"Schema", 1}, {"PluginVersion", "1.0.2"}, {"Scope", scope}, {"CreatedUtc", DateTime.UtcNow.ToString("o")}, {"Status", "in_progress"}, {"Meshes", meshRecords}, {"Nodes", nodeRecords}, {"Textures", textureRecords}, {"Issues", issues}, {"Policy", "Raw source graph and ordered override layers. No inferred channel packing, UV selection, shader reconstruction or positional material matching."}, {"FbxMaterialPolicy", "Existing FBX is unchanged. Section.MaterialId maps to mesh.Materials; FBX exporter emits section geometry but disables FBX materials."}, {"Limits", new JObject {{"Nodes", 20000}, {"Depth", 48}, {"CollectionItems", 100000}}}};
        }
        public void Issue(string path,Exception ex) { Issue(path,ex.GetType().Name+": "+ex.Message); }
        public void Issue(string path,string message) { issues.Add(new JObject {{"Path", path}, {"Message", message}}); }
        private EbxAsset Load(Guid file)
        {
            EbxAsset value;
            if(!assets.TryGetValue(file,out value)) { value=loader(file); if(value==null) throw new InvalidDataException("Missing EBX "+file); assets[file]=value; }
            return value;
        }
        public static string ObjectKey(Guid file,object obj)
        {
            var method=obj.GetType().GetMethod("GetInstanceGuid",Type.EmptyTypes);
            if(method==null) throw new InvalidDataException("Referenced object has no instance identity: "+obj.GetType().FullName);
            var guid=(AssetClassGuid)method.Invoke(obj,null);
            return file.ToString("N")+":"+(guid.IsExported?guid.ExportedGuid.ToString("N"):"internal:"+guid.InternalId);
        }
        public JToken Reference(PointerRef ptr,Guid owner,string path,int depth=0)
        {
            var result=new JObject {{"Kind", ptr.Type.ToString()}, {"FileGuid", ptr.Type==PointerRefType.External?ptr.External.FileGuid:owner}, {"ClassGuid", ptr.External.ClassGuid}};
            if(ptr.Type==PointerRefType.Null) return result;
            try {
                if(Cancel) throw new OperationCanceledException();
                Guid file=ptr.Type==PointerRefType.External?ptr.External.FileGuid:owner;
                object obj=Batch.Resolve(ptr,Load);
                string key=ObjectKey(file,obj); result["Node"]=key;
                if(nodes.ContainsKey(key)) return result;
                if(depth>48 || nodes.Count>=20000) throw new InvalidDataException("Reference traversal limit reached; graph incomplete.");
                var entry=entryLookup(file);
                var node=new JObject {{"Id", key}, {"FileGuid", file}, {"Asset", entry==null?null:entry.Name}, {"Type", obj.GetType().Name}};
                nodes.Add(key,node); nodeRecords.Add(node); // register before following cycles
                node["Raw"]=Snapshot(obj,file,path,depth+1,new HashSet<object>(ReferenceComparer.Instance));
                if(IsTextureType(obj.GetType())) {
                    try { node["TextureResource"]=ExportTexture(obj,file,key,entry==null?null:entry.Name); }
                    catch(Exception ex) { node["TextureError"]=ex.Message; Issue(path,ex); }
                }
                else if(obj.GetType().Name.IndexOf("Shader",StringComparison.OrdinalIgnoreCase)>=0)
                    node["Interpretation"]="Source shader metadata only; compiled shader behavior not reconstructed.";
            } catch(Exception ex) { result["Unresolved"]=ex.Message; Issue(path,ex); }
            return result;
        }
        public JToken Capture(object value,Guid owner,string path)
        { return Snapshot(value,owner,path,0,new HashSet<object>(ReferenceComparer.Instance)); }
        private static bool IsTextureType(Type type)
        {
            while(type!=null) {if(type.Name=="TextureAsset")return true;type=type.BaseType;}
            return false;
        }
        private JToken Snapshot(object value,Guid owner,string path,int depth,HashSet<object> stack)
        {
            if(value==null) return JValue.CreateNull();
            if(value is PointerRef) return Reference((PointerRef)value,owner,path,depth);
            if(value is ResourceRef) return new JObject {{"Type", "ResourceRef"}, {"Hex", ((ulong)(ResourceRef)value).ToString("x16")}};
            if(value is AssetClassGuid) {var g=(AssetClassGuid)value;return new JObject {{"ExportedGuid", g.ExportedGuid}, {"InternalId", g.InternalId}};}
            var type=value.GetType();
            if(type==typeof(string) || type==typeof(Guid) || type.IsPrimitive || type==typeof(decimal)) return JToken.FromObject(value);
            if(type.IsEnum) return new JObject {{"Type", type.Name}, {"Name", value.ToString()}, {"Numeric", Convert.ToInt64(value)}};
            if(type.Name=="CString" || type.Name=="FileRef") return new JObject {{"Type", type.Name}, {"Value", value.ToString()}};
            if(depth>48) {Issue(path,"Depth limit; value not expanded.");return new JObject {{"Truncated", type.FullName}};}
            if(!type.IsValueType && !stack.Add(value)) {Issue(path,"Embedded object cycle; expansion stopped.");return new JObject {{"Cycle", type.FullName}};}
            try {
                if(value is byte[]) return new JObject {{"Type", "byte[]"}, {"Base64", Convert.ToBase64String((byte[])value)}};
                var items=value as IEnumerable;
                if(items!=null) {
                    var array=new JArray(); int i=0;
                    foreach(var item in items) {if(Cancel || i>=100000) {Issue(path,"Collection truncated by limit/cancellation.");break;} array.Add(Snapshot(item,owner,path+"["+i+++"]",depth+1,stack));}
                    return array;
                }
                var fields=new JObject {{"$type", type.FullName}};
                foreach(var p in type.GetProperties(BindingFlags.Public|BindingFlags.Instance).Where(p=>p.CanRead && p.GetIndexParameters().Length==0).OrderBy(p=>p.Name))
                    try { fields[p.Name]=Snapshot(p.GetValue(value,null),owner,path+"."+p.Name,depth+1,stack); }
                    catch(Exception ex) {fields[p.Name]=new JObject {{"ReadError", ex.Message}};Issue(path+"."+p.Name,ex);}
                foreach(var f in type.GetFields(BindingFlags.Public|BindingFlags.Instance).OrderBy(f=>f.Name))
                    if(fields[f.Name]==null) try {fields[f.Name]=Snapshot(f.GetValue(value),owner,path+"."+f.Name,depth+1,stack);} catch(Exception ex) {Issue(path+"."+f.Name,ex);}
                return fields;
            } finally {if(!type.IsValueType) stack.Remove(value);}
        }
        public void Process(MeshRecord mesh)
        {
            var record=new JObject {{"MeshId", mesh.Id}, {"Asset", mesh.Asset}, {"FileGuid", mesh.FileGuid}, {"ClassGuid", mesh.ClassGuid}, {"Fbx", mesh.Fbx}, {"GeometryStatus", mesh.Status}, {"Slots", new JArray()}, {"Sections", new JArray()}, {"Variants", new JArray()}};
            meshRecords.Add(record);
            try {
                Guid file=Guid.Parse(mesh.FileGuid);
                var asset=Load(file);
                object obj=mesh.InternalId!=null?asset.GetObject(new AssetClassGuid(Int32.Parse(mesh.InternalId))):
                    (Guid.Parse(mesh.ClassGuid)==Guid.Empty?asset.RootObject:asset.GetObject(Guid.Parse(mesh.ClassGuid)));
                if(obj==null) throw new InvalidDataException("Mesh object no longer resolves.");
                var slots=(JArray)record["Slots"];
                var materials=Batch.Get(obj,"Materials") as IEnumerable;
                if(materials==null) throw new InvalidDataException("Mesh has no Materials collection.");
                int index=0;
                foreach(var mat in materials) {
                    var slot=new JObject {{"Index", index++}, {"Source", Capture(mat,file,mesh.Id+".Materials")}, {"TextureUvAssociation", "Unspecified unless explicitly present in source fields (for example DisplacementMapTexCoord)."}, {"PackedChannelMeanings", JValue.CreateNull()}, {"SemanticClassification", JValue.CreateNull()}};
                    slots.Add(slot);
                }
                try {
                    var res=App.AssetManager.GetResEntry(Batch.GetResourceId(Batch.Get(obj,"MeshSetResource")));
                    var set=App.AssetManager.GetResAs<MeshSet>(res);
                    if(set==null || set.Lods.Count==0) throw new InvalidDataException("No LOD0 mesh resource.");
                    int sectionIndex=0,exportedIndex=0;
                    foreach(var section in set.Lods[0].Sections) {
                        var uv=new JArray();
                        var attributes=new JArray();
                        foreach(var elem in section.GeometryDeclDesc[0].Elements)
                        {
                            attributes.Add(new JObject {{"Usage",elem.Usage.ToString()},{"Format",elem.Format.ToString()},{"StreamIndex",elem.StreamIndex},{"Offset",elem.Offset}});
                            if(elem.Usage.ToString().IndexOf("TexCoord",StringComparison.Ordinal)>=0)
                                uv.Add(new JObject {{"Usage", elem.Usage.ToString()}, {"Format", elem.Format.ToString()}, {"StreamIndex", elem.StreamIndex}, {"Offset", elem.Offset}});
                        }
                        var sec=new JObject {{"SectionIndex", sectionIndex++}, {"Name", section.Name}, {"FbxNodeName", section.Name}, {"MaterialSlot", section.MaterialId}, {"Renderable", set.Lods[0].IsSectionRenderable(section)}, {"PrimitiveCount", section.PrimitiveCount}, {"UvAttributes", uv}, {"Lod", 0}};
                        sec["VertexAttributes"]=attributes;
                        // Match FBXExporter.FBXExportSubObject's actual traversal.
                        // TexCoord suffix is NOT the exported UV layer ordinal.
                        var bindings=new JArray();var seenUsages=new HashSet<string>();
                        var decl=section.GeometryDeclDesc[0];
                        for(int streamIndex=0;streamIndex<decl.Streams.Length;streamIndex++) {
                            int stride=decl.Streams[streamIndex].VertexStride,currentStride=0;
                            if(stride==0)continue;
                            foreach(var element in decl.Elements) {
                                string usage=element.Usage.ToString();
                                if(usage=="Unknown" || element.StreamIndex!=streamIndex || currentStride>=stride)continue;
                                bool regular=usage.Length==9 && usage.StartsWith("TexCoord") && usage[8]>='0' && usage[8]<='7';
                                bool handled=new[]{"Pos","BinormalSign","Normal","Binormal","Tangent","TangentSpace","Color0","Color1","DisplacementMapTexCoord"}.Contains(usage);
                                string format=element.Format.ToString();
                                bool extra=!handled&&(format=="Half2"||format=="Float2"||format=="Short2N");
                                if((regular || usage=="RadiosityTexCoord" || extra) && seenUsages.Add(usage)) {
                                    int ordinal=bindings.Count;
                                    bindings.Add(new JObject {{"SourceUsage",usage},{"BlenderLayer",regular?"UVChannel"+ordinal:usage},
                                        {"Evidence","Native Frosty FBXExporter stream/declaration traversal"},
                                        {"ValueConversion",regular||usage=="RadiosityTexCoord"?"(U, 1-V)":"Native auxiliary attribute conversion; no V flip"}});
                                }
                                currentStride+=element.Size;
                            }
                        }
                        sec["FbxUvBindings"]=bindings;
                        sec["MaterialAssignmentPolicy"]="Each native FBX section is a separate mesh; all its faces use this MaterialSlot. No per-face array is inferred across sections.";
                        sec["FbxLodParent"]=set.Lods[0].ShortName;
                        sec["FbxChildOrdinal"]=set.Lods[0].IsSectionRenderable(section)?(JToken)new JValue(exportedIndex++):JValue.CreateNull();
                        sec["MatchingNote"]="Names may repeat; match MeshId + LOD parent + child ordinal, not Blender's globally suffixed name alone.";
                        ((JArray)record["Sections"]).Add(sec);
                        if(section.MaterialId<0 || section.MaterialId>=slots.Count) Issue(mesh.Id+".Sections","Material index out of range: "+section.MaterialId);
                    }
                } catch(Exception ex) {Issue(mesh.Id+".Sections",ex);}
                foreach(var variant in mesh.Variants) {
                    if(Cancel) break;
                    var v=new JObject {{"Database", variant.Database}, {"DatabaseGuid", variant.DatabaseGuid}, {"Row", variant.Row}, {"Hash", variant.Hash}, {"Assignments", new JArray()}};
                    ((JArray)record["Variants"]).Add(v);
                    try {
                        Guid dbFile=Guid.Parse(variant.DatabaseGuid);
                        var rows=Batch.Get(Load(dbFile).RootObject,"Entries") as IList;
                        if(rows==null || variant.Row<0 || variant.Row>=rows.Count) throw new InvalidDataException("Database row no longer available.");
                        object row=rows[variant.Row];
                        var rowMesh=(PointerRef)Batch.Get(row,"Mesh");
                        var referenced=Batch.Resolve(rowMesh,Load);
                        var rowOwner=rowMesh.Type==PointerRefType.External?rowMesh.External.FileGuid:dbFile;
                        if(ObjectKey(rowOwner,referenced)!=ObjectKey(file,obj)) throw new InvalidDataException("Stale manifest: database row points to a different mesh.");
                        string hash=Convert.ToUInt32(Batch.Get(row,"VariationAssetNameHash")).ToString("x8");
                        if(hash!=variant.Hash) throw new InvalidDataException("Stale manifest: variation hash changed.");
                        var rawRow=new JObject();
                        foreach(var p in row.GetType().GetProperties().Where(p=>p.Name!="Mesh" && p.GetIndexParameters().Length==0))
                            rawRow[p.Name]=Capture(p.GetValue(row,null),dbFile,mesh.Id+".Variant."+variant.Row+"."+p.Name);
                        v["Raw"]=rawRow;
                        var assignments=Batch.Get(row,"Materials") as IEnumerable;
                        if(assignments!=null) foreach(var assignment in assignments) {
                            var source=Capture(Batch.Get(assignment,"Material"),dbFile,"variant.Material");
                            var target=Capture(Batch.Get(assignment,"MaterialVariation"),dbFile,"variant.MaterialVariation");
                            string baseKey=(string)source["Node"];
                            var matched=slots.OfType<JObject>().Where(s=>baseKey!=null && (string)s["Source"]["Node"]==baseKey).Select(s=>(int)s["Index"]).ToArray();
                            ((JArray)v["Assignments"]).Add(new JObject {{"Slots", new JArray(matched)}, {"Material", source}, {"Override", target}, {"Resolution", matched.Length>0?"exact_object_identity":"unresolved_no_positional_guess"}});
                            if(matched.Length==0) Issue(mesh.Id+".Variant."+variant.Row,"Material assignment does not match a base slot.");
                        }
                    } catch(Exception ex) {v["Error"]=ex.Message;Issue(mesh.Id+".Variant."+variant.Row,ex);}
                }
                record["Status"]=Cancel?"cancelled":"captured";
            } catch(Exception ex) {record["Status"]="failed";record["Error"]=ex.Message;Issue(mesh.Id,ex);}
        }
        private string ExportTexture(object obj,Guid file,string nodeId,string name)
        {
            ulong rid=Batch.GetResourceId(Batch.Get(obj,"Resource"));
            JObject record;
            if(textures.TryGetValue(rid,out record)) {
                ((JArray)record["Aliases"]).Add(new JObject {{"Node", nodeId}, {"Asset", name}, {"FileGuid", file}});
                return rid.ToString("x16");
            }
            record=new JObject {{"ResourceId", rid.ToString("x16")}, {"Status", "pending"}, {"Aliases", new JArray(new JObject {{"Node", nodeId}, {"Asset", name}, {"FileGuid", file}})}, {"PackedChannels", "Preserved unchanged; meanings unknown unless explicitly recorded in source shader fields."}, {"Role", JValue.CreateNull()}, {"UVChannel", JValue.CreateNull()}};
            textures[rid]=record; textureRecords.Add(record);
            try {
                var res=App.AssetManager.GetResEntry(rid);
                if(res==null) throw new InvalidDataException("Missing texture RES "+rid.ToString("x16"));
                using(var texture=App.AssetManager.GetResAs<Texture>(res)) {
                    if(texture==null || texture.Data==null) throw new InvalidDataException("Texture data missing.");
                    record["Format"]=texture.PixelFormat; record["Flags"]=texture.Flags.ToString();record["TextureType"]=texture.Type.ToString();
                    record["Width"]=texture.Width;record["Height"]=texture.Height;record["Depth"]=texture.Depth;
                    record["MipCount"]=texture.MipCount;record["FirstMip"]=texture.FirstMip;record["MipSizes"]=new JArray(texture.MipSizes);
                    record["ChunkId"]=texture.ChunkId;record["ResourceName"]=res.Name;
                    record["ColorSpace"]=texture.PixelFormat.IndexOf("SRGB",StringComparison.OrdinalIgnoreCase)>=0 || texture.Flags.HasFlag(TextureFlags.SrgbGamma)?"sRGB":"unspecified";
                    string basename=Path.GetFileName(Core.Normalize(name??res.Name));
                    string safe=TextureTools.FileName(basename);
                    string folder="textures/"+rid.ToString("x16");
                    Directory.CreateDirectory(Path.Combine(output,folder));
                    // Always preserve the original decompressed texture payload for unsupported DDS layouts/formats.
                    string raw=folder+"/"+safe+".texture-data.bin";
                    using(var stream=File.Create(Path.Combine(output,raw))) {texture.Data.Position=0;texture.Data.CopyTo(stream);}
                    record["RawData"]=raw;record["RawSha256"]=TextureTools.HashFile(Path.Combine(output,raw));
                    if(!TextureTools.Supported(texture.PixelFormat,texture.Type.ToString(),texture.Flags.ToString()))
                        throw new NotSupportedException("Unsupported native DDS format/layout; raw payload and metadata retained.");
                    string relative=folder+"/"+safe+".dds", path=Path.Combine(output,relative);
                    string pending=Path.Combine(Path.GetDirectoryName(path),safe+".partial.dds");
                    try {
                        new TextureExporter().Export(texture,pending,"*.dds",false);
                        TextureTools.ValidateDds(pending,texture.Width,texture.Height);
                        if(texture.Type==TextureType.TT_2d && TextureTools.DdsPayloadHash(pending)!=(string)record["RawSha256"])
                            throw new InvalidDataException("DDS payload differs from original 2D texture data.");
                        ReplaceFile(pending,path);
                        record["Path"]=relative;record["Sha256"]=TextureTools.HashFile(path);record["Status"]="exported";
                        record["Validation"]=texture.Type==TextureType.TT_2d?"DDS header + exact source payload SHA256":"DDS header; upstream face/mip reordering used";
                    } finally {if(File.Exists(pending)) File.Delete(pending);}
                }
            } catch(Exception ex) {record["Status"]="unsupported_or_failed";record["Error"]=ex.Message;Issue(nodeId,ex);}
            return rid.ToString("x16");
        }
        public string Summary() {return textureRecords.Count(t=>(string)t["Status"]=="exported")+" DDS textures; "+issues.Count+" issues.";}
        // Shader-default textures (shared vehicle textures read by the compiled shader profiles).
        public string ExportTextureAsset(EbxAssetEntry entry)
        {
            var obj=Load(entry.Guid).RootObject;
            return ExportTexture(obj,entry.Guid,ObjectKey(entry.Guid,obj),entry.Name);
        }
        public void SaveTextureIndex(string note)
        {
            Directory.CreateDirectory(output);
            WriteJson(Path.Combine(output,"textures.json"),new JObject {{"Schema",1},{"PluginVersion","1.0.2"},{"Scope","shader defaults"},
                {"Note",note},{"Textures",textureRecords},{"Issues",issues}});
        }
        public void Save(bool completed=false)
        {
            Directory.CreateDirectory(output);
            Document["UnsupportedInterpretations"]=new JArray("Compiled shader behavior/ShaderBlockDepot semantics are not decoded.", "Generic texture role, packed-channel meaning and UV selection remain unknown unless explicitly present in raw source.", "Override layers are preserved separately; no guessed final material merge.");
            Document["Status"]=Cancel?"cancelled":completed?(issues.Count==0?"completed":"completed_with_issues"):"in_progress";
            WriteJson(Path.Combine(output,"materials.json"),Document);
            File.WriteAllLines(Path.Combine(output,"materials.log"),issues.Select(i=>(string)i["Path"]+": "+(string)i["Message"]));
        }
        public static void WriteJson(string path,JToken document)
        {
            string temp=path+".tmp";File.WriteAllText(temp,document.ToString(Formatting.Indented));
            ReplaceFile(temp,path);
        }
        // Atomic replace; retried because indexers and antivirus briefly lock freshly written files.
        public static void ReplaceFile(string source,string path)
        {
            for(int attempt=0;;attempt++) {
                try { if(File.Exists(path)) File.Replace(source,path,null); else File.Move(source,path); return; }
                catch(IOException) { if(attempt>=20) throw; System.Threading.Thread.Sleep(250); }
                catch(UnauthorizedAccessException) { if(attempt>=20) throw; System.Threading.Thread.Sleep(250); }
            }
        }
    }
    internal sealed class ReferenceComparer : IEqualityComparer<object>
    {
        public static readonly ReferenceComparer Instance=new ReferenceComparer();
        public new bool Equals(object a,object b) {return Object.ReferenceEquals(a,b);}
        public int GetHashCode(object value) {return System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(value);}
    }
    public static class TextureTools
    {
        private static readonly HashSet<string> Formats=new HashSet<string>(("NormalDXT1 NormalDXN BC1A_SRGB BC1A_UNORM BC1_SRGB BC1_UNORM BC2_SRGB BC3_SRGB BC3A_SRGB BC3_UNORM BC3A_UNORM BC4_UNORM BC5_UNORM BC6U_FLOAT BC7 BC7_SRGB BC7_UNORM R8_UNORM R16G16B16A16_FLOAT R16G16B16A16_UNORM ARGB32F R32G32B32A32_FLOAT R9G9B9E5F R9G9B9E5_FLOAT R8G8B8A8_UNORM R8G8B8A8_SRGB R10G10B10A2_UNORM L8 L16 ARGB8888").Split(' '));
        public static bool Supported(string format,string type,string flags)
        {return Formats.Contains(format) && new[]{"TT_2d","TT_Cube","TT_3d","TT_2dArray"}.Contains(type) && !flags.Contains("SwizzledData");}
        public static string FileName(string name)
        {
            if(String.IsNullOrWhiteSpace(name)) return "texture";
            string result=new string(name.Select(c=>Path.GetInvalidFileNameChars().Contains(c)?'_':c).ToArray()).TrimEnd('.',' ');
            if(result.Length>100) result=result.Substring(0,80)+"_"+Core.Id(name).Substring(0,16);
            string first=result.Split('.')[0].ToUpperInvariant();
            if(new[]{"CON","PRN","AUX","NUL","COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9","LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9"}.Contains(first)) result="_"+result;
            return result.Length==0?"texture":result;
        }
        public static string HashFile(string path) {using(var s=File.OpenRead(path))using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(s)).Replace("-","").ToLowerInvariant();}
        public static void ValidateDds(string path,int width,int height)
        {
            using(var r=new BinaryReader(File.OpenRead(path))) {
                if(r.BaseStream.Length<=128 || r.ReadUInt32()!=0x20534444 || r.ReadUInt32()!=124)throw new InvalidDataException("Invalid DDS header.");
                r.BaseStream.Position=12;if(r.ReadInt32()!=height || r.ReadInt32()!=width)throw new InvalidDataException("DDS dimensions mismatch.");
                r.BaseStream.Position=76;if(r.ReadInt32()!=32)throw new InvalidDataException("Invalid DDS pixel-format header.");
                r.BaseStream.Position=84;uint fourcc=r.ReadUInt32();
                if(fourcc==0)throw new InvalidDataException("Unrecognized DDS format.");
                if(fourcc==0x30315844) {if(r.BaseStream.Length<=148)throw new InvalidDataException("Truncated DX10 DDS.");r.BaseStream.Position=128;if(r.ReadInt32()==0)throw new InvalidDataException("Unknown DXGI format.");}
            }
        }
        public static string DdsPayloadHash(string path)
        {
            using(var s=File.OpenRead(path))using(var r=new BinaryReader(s))using(var sha=SHA256.Create()) {
                s.Position=84;uint fourcc=r.ReadUInt32();s.Position=fourcc==0x30315844?148:128;
                return BitConverter.ToString(sha.ComputeHash(s)).Replace("-","").ToLowerInvariant();
            }
        }
    }
}
