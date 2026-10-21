# Machine-specific paths for the PowerShell tools (dot-source this file). Same rules as tools/settings.py:
# settings.json next to the repository folder, or $env:ANS_GARAGE_SETTINGS; relative paths resolve against it.
$repo = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$file = if ($env:ANS_GARAGE_SETTINGS) { $env:ANS_GARAGE_SETTINGS } else { Join-Path (Split-Path -Parent $repo) 'settings.json' }
if (!(Test-Path -LiteralPath $file)) { throw "Settings not found: $file (copy settings.example.json there and fill it in)" }
$Settings = @{}
$base = Split-Path -Parent (Resolve-Path -LiteralPath $file).Path
(Get-Content -Raw -LiteralPath $file | ConvertFrom-Json).PSObject.Properties | ForEach-Object {
    if ($_.Name.StartsWith('_')) { return }
    $value = if ([System.IO.Path]::IsPathRooted($_.Value)) { $_.Value } else { Join-Path $base $_.Value }
    $Settings[$_.Name] = [System.IO.Path]::GetFullPath($value)
}
