param([string]$FrostyDir)
# Builds bin\AnsGarage.dll (+ UnboundShaderDefaults.json). Copy both into Frosty's Plugins folder.
$ErrorActionPreference = 'Stop'
if (!$FrostyDir) { . (Join-Path $PSScriptRoot '..\..\tools\settings.ps1'); $FrostyDir = $Settings.frosty_dir }
$FrostyDir = (Resolve-Path -LiteralPath $FrostyDir).Path
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$framework = Split-Path $compiler
$refs = @('FrostyCore.dll','FrostySdk.dll','FrostyControls.dll','Plugins\MeshSetPlugin.dll','Plugins\TexturePlugin.dll','Newtonsoft.Json.dll') | ForEach-Object { Join-Path $FrostyDir $_ }
$refs += @('System.dll','System.Core.dll','System.Windows.Forms.dll','System.Drawing.dll','Microsoft.CSharp.dll','WPF\WindowsBase.dll','WPF\PresentationCore.dll','WPF\PresentationFramework.dll','System.Xaml.dll') | ForEach-Object { Join-Path $framework $_ }
foreach ($ref in $refs) { if (!(Test-Path -LiteralPath $ref)) { throw "Missing dependency: $ref" } }
$destination = Join-Path $PSScriptRoot 'bin'
New-Item -ItemType Directory -Force $destination | Out-Null
$arguments = @('/nologo','/target:library','/platform:x64','/optimize+','/warn:4',('/out:' + (Join-Path $destination 'AnsGarage.dll')))
$arguments += $refs | ForEach-Object { '/reference:' + $_ }
$arguments += Get-ChildItem (Join-Path $PSScriptRoot 'src') -Filter *.cs | ForEach-Object { $_.FullName }
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw 'Compilation failed' }
Copy-Item (Join-Path $PSScriptRoot 'UnboundShaderDefaults.json') $destination -Force
Write-Output "Built $destination\AnsGarage.dll"
