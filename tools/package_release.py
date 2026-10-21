"""Build the install packages into <release_dir>/<add-on version>/ (outside the repository).

usage: python tools/package_release.py [--profiles <profiles-agnostic.json>]
  UnboundBlender-<version>.zip               Blender add-on (Install from Disk)
  UnboundBatchExport-<version>-plugin.zip    Frosty plugin (bin\\ must be built first with build.ps1)
--profiles re-packs blender/unbound_batch/shader_profiles.json.gz from a new compile_all.py output first.
"""
import gzip
import hashlib
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
from settings import path as setting  # noqa: E402

addon = REPO / "blender" / "unbound_batch"
frosty = REPO / "frosty" / "UnboundBatchExport"
if "--profiles" in sys.argv:
    src = Path(sys.argv[sys.argv.index("--profiles") + 1])
    (addon / "shader_profiles.json.gz").write_bytes(gzip.compress(src.read_bytes(), 9))
version = ".".join(map(str, eval(re.search(r'"version": (\([^)]*\))', (addon / "__init__.py").read_text()).group(1))))
plugin_version = re.search(r'PluginVersion\("(\d+\.\d+\.\d+)', (frosty / "src" / "Plugin.cs").read_text()).group(1)
out = setting("release_dir") / version
out.mkdir(parents=True, exist_ok=True)

with zipfile.ZipFile(out / ("UnboundBlender-%s.zip" % version), "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(addon.iterdir()):
        if f.is_file() and f.suffix in (".py", ".json", ".gz"):
            z.write(f, "unbound_batch/" + f.name)
dll = frosty / "bin" / "UnboundBatchExport.dll"
if not dll.is_file():
    raise SystemExit("Build the Frosty plugin first: frosty/UnboundBatchExport/build.ps1")
with zipfile.ZipFile(out / ("UnboundBatchExport-%s-plugin.zip" % plugin_version), "w", zipfile.ZIP_DEFLATED) as z:
    for f in (dll, frosty / "UnboundShaderDefaults.json", frosty / "README.md", frosty / "CHANGELOG.md"):
        z.write(f, f.name)
for f in sorted(out.glob("*.zip")):
    print(f.name, f.stat().st_size, hashlib.sha256(f.read_bytes()).hexdigest()[:16])
