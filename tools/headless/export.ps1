param([Parameter(Mandatory=$true)][string]$Mode,[string]$A='',[string]$B='',[string]$C='')
# Runs UnboundBatchExport without opening Frosty (paths from settings.json; destinations must be absolute).
#   catalog   <out.json>                         every vehicle by in-game name (also refreshes the picker cache)
#   export    <vehicle folder> <out dir> [blueprint]
#   assembly  <export dir> <blueprint>           re-run assembly for an existing export
#   defaults  <export dir>                       shader default textures only
#   hashes    <h1|h2|...> <out.json>             EBX assets whose name hash matches
#   find-text <term1|term2|...> <out.json>       localized strings containing a term
# Build the plugin first (frosty\UnboundBatchExport\build.ps1). Do not run while Frosty uses the same work folder.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\settings.ps1')
$work = $Settings.frosty_work_dir
$plugin = (Resolve-Path (Join-Path $PSScriptRoot '..\..\frosty\UnboundBatchExport\bin')).Path
$fw = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319'
$refs = @('FrostyCore.dll','FrostySdk.dll','Newtonsoft.Json.dll') | ForEach-Object { '/r:' + (Join-Path $work $_) }
$refs += '/r:' + (Join-Path $plugin 'UnboundBatchExport.dll')
$refs += @('WPF\PresentationFramework.dll','WPF\WindowsBase.dll','WPF\PresentationCore.dll','System.Xaml.dll','Microsoft.CSharp.dll') | ForEach-Object { '/r:' + (Join-Path $fw $_) }
$bin = Join-Path $work 'bin'
New-Item -ItemType Directory -Force $bin | Out-Null
$exe = Join-Path $bin 'ExportHarness.exe'
& (Join-Path $fw 'csc.exe') /nologo /platform:x64 ('/out:' + $exe) @refs (Join-Path $PSScriptRoot 'ExportHarness.cs')
if ($LASTEXITCODE -ne 0) { throw 'compile failed' }
$env:UNBOUND_FROSTY_CONFIG_COPY = Join-Path $work 'editor_config.copy.json'
Push-Location $work
try { & $exe $Settings.frosty_dir $plugin $work $Settings.game_dir $Mode $A $B $C } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'harness failed' }
