param([Parameter(Mandatory=$true)][string]$FrostyDir, [string]$ScratchDir = "$env:TEMP\UnboundBatchExportTests")
$ErrorActionPreference = 'Stop'
$FrostyDir = (Resolve-Path -LiteralPath $FrostyDir).Path
$package = Split-Path $PSScriptRoot
New-Item -ItemType Directory -Force $ScratchDir | Out-Null
$ScratchDir = (Resolve-Path -LiteralPath $ScratchDir).Path
$exe = Join-Path $ScratchDir 'Tests.exe'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$references = @((Join-Path $FrostyDir 'FrostySdk.dll'), (Join-Path $FrostyDir 'Plugins\MeshSetPlugin.dll'), (Join-Path $package 'plugin\UnboundBatchExport.dll'), 'Microsoft.CSharp.dll','System.Core.dll')
$references += (Join-Path $FrostyDir 'Newtonsoft.Json.dll')
$argsList = @('/nologo','/target:exe','/platform:x64',('/out:'+$exe)) + @($references | ForEach-Object { '/r:' + $_ }) + (Join-Path $PSScriptRoot 'Tests.cs')
& $compiler @argsList
if ($LASTEXITCODE -ne 0) { throw 'Test compilation failed' }
& $exe $FrostyDir (Join-Path $package 'plugin')
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
