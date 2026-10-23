<#
.SYNOPSIS
    Turns TickPlayer's auto-start on or off in VLC's settings (vlcrc).

.DESCRIPTION
    Auto-start runs lua\intf\tickplayer.lua as an extra VLC interface:
      extraintf=...:luaintf
      lua-intf=tickplayer
    VLC must be closed, because it rewrites vlcrc when it exits.
    A backup of the original file is kept as vlcrc.tickplayer-backup.

    Exit codes: 0 done, 1 error, 2 lua-intf is already used by another script.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, ParameterSetName = 'On')][switch]$Enable,
    [Parameter(Mandatory, ParameterSetName = 'Off')][switch]$Disable,
    [string]$ConfigPath = (Join-Path $env:APPDATA 'vlc\vlcrc')
)

$ErrorActionPreference = 'Stop'

function Split-Modules([string]$value) {
    @($value -split '[:,]' | Where-Object { $_ -ne '' })
}

# Sets "name=value" on the first active line for the option, else on its
# commented-out default ("#name="), else appends it. VLC ignores section
# headers when reading, so the position does not matter. A $null value
# comments the option out. ($value is untyped: [string] would turn $null into ''.)
function Set-Option([System.Collections.Generic.List[string]]$lines, [string]$name, $value) {
    $line = if ($value -eq $null) { "#$name=" } else { "$name=$value" }
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^$([regex]::Escape($name))=") { $lines[$i] = $line; return }
    }
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^#\s*$([regex]::Escape($name))=") { $lines[$i] = $line; return }
    }
    if ($value -ne $null) { $lines.Add($line) }
}

function Get-Option([System.Collections.Generic.List[string]]$lines, [string]$name) {
    foreach ($l in $lines) {
        if ($l -match "^$([regex]::Escape($name))=(.*)$") { return $Matches[1] }
    }
    return $null
}

try {
    $bom = $false
    $newline = "`r`n"
    $lines = New-Object 'System.Collections.Generic.List[string]'
    if (Test-Path -LiteralPath $ConfigPath) {
        $bytes = [IO.File]::ReadAllBytes($ConfigPath)
        $bom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
        $text = (New-Object Text.UTF8Encoding $false).GetString($bytes, $(if ($bom) { 3 } else { 0 }), $bytes.Length - $(if ($bom) { 3 } else { 0 }))
        if ($text -notmatch "`r`n") { $newline = "`n" }
        foreach ($l in ($text -split "`r?`n")) { $lines.Add($l) }
        if ($lines.Count -gt 0 -and $lines[$lines.Count - 1] -eq '') { $lines.RemoveAt($lines.Count - 1) }

        $backup = "$ConfigPath.tickplayer-backup"
        if (-not (Test-Path -LiteralPath $backup)) { Copy-Item -LiteralPath $ConfigPath -Destination $backup }
    }
    elseif ($Disable) {
        exit 0
    }
    else {
        New-Item -ItemType Directory -Force (Split-Path -Parent $ConfigPath) | Out-Null
        $bom = $true
    }

    $luaIntf = Get-Option $lines 'lua-intf'
    # @() keeps a one-item result an array; otherwise += would append to a string.
    $modules = @(Split-Modules (Get-Option $lines 'extraintf'))

    if ($Enable) {
        if ($luaIntf -and $luaIntf -notin @('dummy', 'tickplayer')) {
            Write-Warning "VLC's Lua interface is already set to '$luaIntf'; auto-start was not enabled."
            exit 2
        }
        if ($modules -notcontains 'luaintf') { $modules += 'luaintf' }
        Set-Option $lines 'extraintf' ($modules -join ':')
        Set-Option $lines 'lua-intf' 'tickplayer'
    }
    else {
        if ($luaIntf -ne 'tickplayer') { exit 0 }  # luaintf belongs to someone else's script
        $modules = @($modules | Where-Object { $_ -ne 'luaintf' })
        Set-Option $lines 'extraintf' $(if ($modules.Count) { $modules -join ':' } else { $null })
        Set-Option $lines 'lua-intf' $null
    }

    $out = ($lines -join $newline) + $newline
    $encoded = (New-Object Text.UTF8Encoding $false).GetBytes($out)
    if ($bom) { $encoded = [byte[]](0xEF, 0xBB, 0xBF) + $encoded }
    [IO.File]::WriteAllBytes($ConfigPath, $encoded)
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
