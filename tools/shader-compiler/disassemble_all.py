"""Read-only DXIL disassembly via the game's dxcompiler.dll (IDxcCompiler::Disassemble)."""
import ctypes as c, hashlib, json, struct, sys, uuid
from pathlib import Path
src, dst, dxdll = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
dst.mkdir(exist_ok=True)
dx = c.WinDLL(dxdll)
create = dx.DxcCreateInstance
create.argtypes = [c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p)]
create.restype = c.c_long
def obj(clsid, iid):
    out = c.c_void_p()
    hr = create(c.create_string_buffer(uuid.UUID(clsid).bytes_le), c.create_string_buffer(uuid.UUID(iid).bytes_le), c.byref(out))
    assert hr >= 0, hex(hr)
    return out
compiler = obj("73e22d93-e6ce-47f3-b5bf-f0664f39c1b0", "8c210bf3-011f-4422-8d70-6f9acb8db617")
library = obj("6245d6af-66e0-48fd-80b4-4d271796748c", "e5204dc7-d18c-4c3c-bdfb-851673980fe7")
def vt(o, i, res, *args):
    return c.WINFUNCTYPE(res, c.c_void_p, *args)(c.cast(o, c.POINTER(c.POINTER(c.c_void_p)))[0][i])
report = []
for item in json.loads((src / "index.json").read_text()):
    d = (src / item["File"]).read_bytes()
    off = d.find(b"DXBC")
    size = struct.unpack_from("<I", d, off + 24)[0]
    blob = d[off:off + size]
    buf = c.create_string_buffer(blob, len(blob))
    enc = c.c_void_p()
    # IDxcLibrary::CreateBlobWithEncodingFromPinned (vtable 6)
    assert vt(library, 6, c.c_long, c.c_void_p, c.c_uint32, c.c_uint32, c.POINTER(c.c_void_p))(library, buf, len(blob), 0, c.byref(enc)) >= 0
    res = c.c_void_p()
    hr = vt(compiler, 5, c.c_long, c.c_void_p, c.POINTER(c.c_void_p))(compiler, enc, c.byref(res))
    if hr < 0:
        print("FAIL", item["Name"], hex(hr & 0xffffffff)); continue
    ptr = vt(res, 3, c.c_void_p)(res); n = vt(res, 4, c.c_size_t)(res)
    text = c.string_at(ptr, n).rstrip(b"\0").decode("utf-8")
    vt(res, 2, c.c_uint)(res); vt(enc, 2, c.c_uint)(enc)
    guid = item["Name"].split("/")[-1]
    (dst / (guid + ".asm")).write_text(text, encoding="utf-8")
    report.append({**item, "Offset": off, "Length": size, "SHA256": hashlib.sha256(blob).hexdigest(), "Lines": len(text.splitlines())})
(dst / "disassembly-index.json").write_text(json.dumps(report, indent=1))
print("disassembled", len(report))
