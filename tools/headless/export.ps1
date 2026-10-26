param([Parameter(Mandatory=$true)][string]$Mode,[string]$A='',[string]$B='',[string]$C='',[string]$D='')
# Runs An's Garage for Frosty without opening Frosty (paths from settings.json; destinations must be absolute).
#   catalog   <out.json>                         every vehicle by in-game name (also refreshes the picker cache)
#   export    <vehicle folder> <out dir> [blueprint] [static]   static (any position): no moving parts built on import
#   assembly  <export dir> <blueprint>           re-run assembly for an existing export
#   defaults  <out dir>                          shader textures (shared by all cars), as Export shared parts writes them
#   liveries  <export dir> <list|all|k1|k2...>   list a car's stock liveries, or add them to an existing export
#   hashes    <h1|h2|...> <out.json>             EBX assets whose name hash matches
#   find-text <term1|term2|...> <out.json>       localized strings containing a term
#   tires     <out dir>                          Falken and Toyo tire library (once, shared by all cars)
#   plates    <out dir> [plates|frames]          license plate library (once, shared by all cars); one part only
#   rims      <out dir>                          real-brand aftermarket rim library (once, shared by all cars)
#   scan      <out.json>                         moving parts of every vehicle (animation objects only, read-only)
#   items     <EBX type> <out.json>              every asset of a type, with names and a field dump
#   assets    <term1|term2|...> <out.json>       asset names containing a term
#   dump      <asset1|asset2|...> <out.json>     every object of the named assets, with internal references by id
#   textures  <asset1|asset2|...> <out dir>      named texture assets as DDS (research; game data, keep private)
# Build the plugin first (frosty\AnsGarage\build.ps1). Do not run while Frosty uses the same work folder.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\settings.ps1')
$work = $Settings.frosty_work_dir
$plugin = (Resolve-Path (Join-Path $PSScriptRoot '..\..\frosty\AnsGarage\bin')).Path
$fw = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319'
$refs = @('FrostyCore.dll','FrostySdk.dll','Newtonsoft.Json.dll') | ForEach-Object { '/r:' + (Join-Path $work $_) }
$refs += '/r:' + (Join-Path $plugin 'AnsGarage.dll')
$refs += @('WPF\PresentationFramework.dll','WPF\WindowsBase.dll','WPF\PresentationCore.dll','System.Xaml.dll','Microsoft.CSharp.dll') | ForEach-Object { '/r:' + (Join-Path $fw $_) }
$bin = Join-Path $work 'bin'
New-Item -ItemType Directory -Force $bin | Out-Null
$exe = Join-Path $bin 'ExportHarness.exe'
& (Join-Path $fw 'csc.exe') /nologo /platform:x64 ('/out:' + $exe) @refs (Join-Path $PSScriptRoot 'ExportHarness.cs')
if ($LASTEXITCODE -ne 0) { throw 'compile failed' }
$env:UNBOUND_FROSTY_CONFIG_COPY = Join-Path $work 'editor_config.copy.json'
Push-Location $work
try { & $exe $Settings.frosty_dir $plugin $work $Settings.game_dir $Mode $A $B $C $D } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'harness failed' }
