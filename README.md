# An's Garage

NFS Unbound vehicles in Blender: any car, the game's own part names, and materials compiled from the game's shaders. NFS Heat and Hot Pursuit Remastered are planned.

## Layout

| Folder | What it is |
|---|---|
| `blender/unbound_batch/` | Blender add-on (4.0+, tested on 5.2.2): import, assembly, part switching, materials |
| `frosty/UnboundBatchExport/` | Frosty Editor plugin: exports a vehicle (geometry, materials, assembly, names) |
| `tools/shader-compiler/` | Builds `shader_profiles.json.gz` from the game's vehicle shader database |
| `tools/headless/` | Runs the exporter without opening Frosty |
| `tools/package_release.py` | Builds the install ZIPs into the release folder |
| `tests/` | Blender test suite (`run_all.py`) |
| `docs/` | Development notes and data formats |

No game data is stored here: no textures, meshes, shader bytecode or disassembly. Local paths live in `../settings.json` (see `settings.example.json`); it is not committed.

## Use

1. Install the Frosty plugin (`frosty/UnboundBatchExport/README.md`).
2. Install the add-on: zip `blender/unbound_batch` (or run `tools/package_release.py`), then in Blender use **Preferences → Add-ons → Install from Disk**.
3. In Frosty, choose **Tools → Unbound vehicle batch export...**, then **Choose vehicle...**, then **Export...**.
4. In Blender, choose **File → Import → Unbound batch manifest (.json)**, then pick the export's `manifest.json`.
5. Press **N → Unbound** for presets, parts by in-game name, and vehicle paint.

## Development

```powershell
copy settings.example.json ..\settings.json                       # then edit the paths
powershell -File frosty\UnboundBatchExport\build.ps1              # Frosty plugin -> bin\
powershell -File tools\headless\export.ps1 export <vehicle folder> <out dir> [blueprint]
python tools\shader-compiler\compile_all.py <shader_data_dir>\profiles-agnostic.json --jobs 12
python tools\package_release.py --profiles <shader_data_dir>\profiles-agnostic.json
python tests\run_all.py                                           # existing, fresh, nodes
```

- **Shader compiler input:** `<shader_data_dir>`, made locally from the installed game: `parsed.json`, the program tables, `asm/` (DXC disassembly) and `shader-defaults/`.
- **Re-packing profiles:** only needed when the compiler changes. The committed `shader_profiles.json.gz` is that compiler's output.

See `docs/development-notes.md` for how the pipeline works and what is still open.
