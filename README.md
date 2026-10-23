# An's Garage

NFS Unbound vehicles in Blender: any car, the game's own part names, and materials compiled from the game's shaders. NFS Heat and Hot Pursuit Remastered are planned.

Two parts, always the same version:

- **An's Garage for Frosty** exports a vehicle from the game (Frosty Editor plugin).
- **An's Garage for Blender** imports it (Blender add-on).

## Layout

| Folder | What it is |
|---|---|
| `blender/ans_garage/` | An's Garage for Blender (Blender 4.1+, tested on 5.2.3): import, assembly, part switching, materials |
| `frosty/AnsGarage/` | An's Garage for Frosty: exports a vehicle (geometry, materials, assembly, names) |
| `tools/shader-compiler/` | Builds `shader_profiles.json.gz` from the game's vehicle shader database |
| `tools/headless/` | Runs the exporter without opening Frosty |
| `tools/package_release.py` | Builds the install ZIPs into the release folder |
| `tests/` | Blender test suite (`run_all.py`) |
| `docs/` | Development notes and data formats |

No game data is stored here: no textures, meshes, shader bytecode or disassembly. Local paths live in `../settings.json` (see `settings.example.json`); it is not committed.

## Use

1. Install An's Garage for Frosty (`frosty/AnsGarage/README.md`).
2. Install An's Garage for Blender: run `tools/package_release.py` (or zip `blender/ans_garage`), then in Blender use **Preferences → Add-ons → Install from Disk**.
3. In Frosty, choose **Tools → An's Garage → Export vehicle...**, then **Choose vehicle...**, then **Export...**.
4. Once, for every car: **Tools → An's Garage → Export shared parts (tires, rims, plates)...** into one folder, then set that folder in Blender (add-on preferences, **Shared parts folder**).
5. In Blender, press **N → An's Garage → Import car…** (or **File → Import → An's Garage vehicle (.json)**) and pick the export's `manifest.json`.
6. The car's section has its preset, body parts by in-game name, paint and livery, wheels, license plate, moving parts (0–1 sliders for doors, windows, hood, boot and active aero), materials, and dirt, dust and wet.

## Development

```powershell
copy settings.example.json ..\settings.json                       # then edit the paths
powershell -File frosty\AnsGarage\build.ps1                       # Frosty plugin -> bin\
powershell -File tools\headless\export.ps1 export <vehicle folder> <out dir> [blueprint]
python tools\shader-compiler\compile_all.py <shader_data_dir>\profiles-agnostic.json --jobs 12
python tools\package_release.py --profiles <shader_data_dir>\profiles-agnostic.json
python tests\run_all.py                                           # every test, 12 at a time; unchanged ones skipped
python tests\run_all.py quick                                     # nodes + Murciélago only
python tests\run_all.py full                                      # re-run everything (before a release)
```

- **Shader compiler input:** `<shader_data_dir>`, made locally from the installed game: `parsed.json`, the program tables, `asm/` (DXC disassembly) and `shader-defaults/`.
- **Re-packing profiles:** only needed when the compiler changes. The committed `shader_profiles.json.gz` is that compiler's output.

See `docs/development-notes.md` for how the pipeline works and what is still open.
