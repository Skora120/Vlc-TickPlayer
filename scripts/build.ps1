<#
.SYNOPSIS
    Builds both helper flavours and packages a release zip in dist\.

.DESCRIPTION
    Requires the .NET SDK (6 or newer) on Windows. The helper targets
    .NET Framework 4.8, which Windows 10 and 11 already include.

    Output:
      dist\TickPlayer-<version>\        the unpacked release
      dist\TickPlayer-<version>.zip     what users download

    The release mirrors VLC's lua folder, so a manual install is "copy the
    lua folder into %APPDATA%\vlc".
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$project = Join-Path $root 'helper\TickPlayerHelper.csproj'
$extension = Join-Path $root 'lua\extensions\tickplayer.lua'

# The extension and the helper carry the same version number.
$version = (Select-Xml -Path $project -XPath '//Version').Node.InnerText
$luaVersion = [regex]::Match((Get-Content -Raw $extension), 'local VERSION = "([^"]+)"').Groups[1].Value
if ($version -ne $luaVersion) {
    throw "Version mismatch: TickPlayerHelper.csproj has $version, tickplayer.lua has $luaVersion"
}
Write-Host "Building TickPlayer $version"

foreach ($platform in 'x64', 'x86') {
    dotnet build $project -c Release "-p:Platform=$platform" -nologo -v:q
    if ($LASTEXITCODE -ne 0) { throw "Build failed for $platform" }
}

$name = "TickPlayer-$version"
$dist = Join-Path $root 'dist'
$stage = Join-Path $dist $name
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }

Copy-Item -Recurse (Join-Path $root 'lua') (Join-Path $stage 'lua')
$helperDir = Join-Path $stage 'lua\extensions\tickplayer'
New-Item -ItemType Directory -Force $helperDir | Out-Null
Copy-Item (Join-Path $root 'helper\bin\x64\Release\TickPlayerHelper.exe') $helperDir
Copy-Item (Join-Path $root 'helper\bin\x86\Release\TickPlayerHelper-x86.exe') $helperDir
Copy-Item (Join-Path $root 'scripts\install.cmd'), (Join-Path $root 'scripts\uninstall.cmd'), (Join-Path $root 'scripts\tickplayer-autostart.ps1') $stage
Copy-Item (Join-Path $root 'LICENSE') (Join-Path $stage 'LICENSE.txt')

$zip = Join-Path $dist "$name.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip
Write-Host "Created $zip"
