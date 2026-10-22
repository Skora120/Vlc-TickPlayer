<#
.SYNOPSIS
    Tests a built release on this machine.

.DESCRIPTION
    Always: the helper decodes 20 thumbnails of tests\sample.mp4 with the
    installed VLC's libVLC.

    With -Install (CI only; it changes the current user's VLC setup):
      1. install.cmd /auto installs the files and turns on auto-start;
      2. a headless VLC plays the sample, and the auto-start script must start
         the helper, which must open the video and exit when VLC exits;
      3. uninstall.cmd removes everything again.

.EXAMPLE
    scripts\test-release.ps1 -Release dist\TickPlayer-1.0.0
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Release,
    [ValidateSet('x64', 'x86')][string]$Arch = 'x64',
    [string]$VlcDir,
    [switch]$Install
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$Release = (Resolve-Path $Release).Path
if (-not $VlcDir) {
    $VlcDir = if ($Arch -eq 'x86') { "${env:ProgramFiles(x86)}\VideoLAN\VLC" } else { "$env:ProgramFiles\VideoLAN\VLC" }
}
$helperName = if ($Arch -eq 'x86') { 'TickPlayerHelper-x86.exe' } else { 'TickPlayerHelper.exe' }
$helper = Join-Path $Release "lua\extensions\tickplayer\$helperName"
$sample = (Resolve-Path (Join-Path $root 'tests\sample.mp4')).Path
$work = Join-Path ([IO.Path]::GetTempPath()) "tickplayer-test-$Arch"
if (Test-Path $work) { Remove-Item -Recurse -Force $work }

function Assert([bool]$condition, [string]$what) {
    if (-not $condition) { throw "FAILED: $what" }
    Write-Host "  ok: $what"
}

Write-Host "== Thumbnails with libVLC from $VlcDir"
$p = Start-Process $helper -ArgumentList '--test-thumbnails', "`"$VlcDir`"", "`"$(([Uri]$sample).AbsoluteUri)`"", "`"$work`"" -Wait -PassThru
Get-Content (Join-Path $work 'report.txt') | ForEach-Object { Write-Host "  $_" }
Assert ($p.ExitCode -eq 0) 'all 20 thumbnails decoded'

if (-not $Install) { return }

$lua = Join-Path $env:APPDATA 'vlc\lua'
$vlcrc = Join-Path $env:APPDATA 'vlc\vlcrc'
$files = 'extensions\tickplayer.lua', "extensions\tickplayer\$helperName", 'intf\tickplayer.lua', 'modules\tickplayer_core.lua'

Write-Host "== install.cmd /auto"
cmd /c "`"$Release\install.cmd`" /auto < nul" | ForEach-Object { Write-Host "  $_" }
Assert ($LASTEXITCODE -eq 0) 'install.cmd succeeded'
foreach ($f in $files) { Assert (Test-Path (Join-Path $lua $f)) "installed $f" }
$settings = Get-Content $vlcrc
Assert ($settings -contains 'lua-intf=tickplayer') 'vlcrc: lua-intf=tickplayer'
Assert (@($settings -match '^extraintf=(.*:)?luaintf(:.*)?$').Count -eq 1) 'vlcrc: extraintf includes luaintf'

Write-Host "== Auto-start in a headless VLC"
$log = Join-Path $env:LOCALAPPDATA 'TickPlayer\helper.log'
if (Test-Path $log) { Remove-Item $log }
# The user's settings may loop the playlist or pause at the end, and then
# VLC never exits, so turn those off for this run.
$vlc = Start-Process (Join-Path $VlcDir 'vlc.exe') -PassThru -ArgumentList `
    '-I', 'dummy', '--dummy-quiet', '--vout=dummy', '--aout=dummy', '--no-loop', '--no-repeat', '--no-random',
    '--no-play-and-pause', '--stop-time=8', '--play-and-exit', "`"$sample`""
if (-not $vlc.WaitForExit(60000)) {
    $vlc.Kill()
    throw 'FAILED: VLC did not exit'
}
$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline -and -not ((Test-Path $log) -and (Select-String -LiteralPath $log -Pattern 'Stopped' -Quiet))) {
    Start-Sleep -Milliseconds 250
}
if (Test-Path $log) { Get-Content $log | ForEach-Object { Write-Host "  $_" } }
Assert (Test-Path $log) 'the auto-start script launched the helper'
Assert (Select-String -LiteralPath $log -Pattern 'Media: file:' -Quiet) 'the helper received the playing file'
Assert (Select-String -LiteralPath $log -Pattern 'Opened in' -Quiet) 'the helper opened the video with libVLC'
Assert (Select-String -LiteralPath $log -Pattern 'VLC exited' -Quiet) 'the helper exited with VLC'

Write-Host "== uninstall.cmd"
cmd /c "`"$Release\uninstall.cmd`" < nul" | ForEach-Object { Write-Host "  $_" }
Assert ($LASTEXITCODE -eq 0) 'uninstall.cmd succeeded'
foreach ($f in $files) { Assert (-not (Test-Path (Join-Path $lua $f))) "removed $f" }
Assert (-not ((Get-Content $vlcrc) -contains 'lua-intf=tickplayer')) 'vlcrc: auto-start turned off'

Write-Host "All tests passed."
