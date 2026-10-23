@echo off
setlocal
rem Removes TickPlayer, its auto-start setting and its cached thumbnails
rem for the current Windows user.

tasklist /fi "imagename eq vlc.exe" 2>nul | find /i "vlc.exe" >nul
if not errorlevel 1 (
    echo VLC is running. Close all VLC windows, then run uninstall.cmd again.
    echo.
    pause
    exit /b 1
)

if exist "%~dp0tickplayer-autostart.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tickplayer-autostart.ps1" -Disable
)

set "LUA=%APPDATA%\vlc\lua"
if exist "%LUA%\extensions\tickplayer.lua" del /f /q "%LUA%\extensions\tickplayer.lua"
if exist "%LUA%\extensions\tickplayer" rmdir /s /q "%LUA%\extensions\tickplayer"
if exist "%LUA%\intf\tickplayer.lua" del /f /q "%LUA%\intf\tickplayer.lua"
if exist "%LUA%\modules\tickplayer_core.lua" del /f /q "%LUA%\modules\tickplayer_core.lua"
if exist "%APPDATA%\vlc\tickplayer" rmdir /s /q "%APPDATA%\vlc\tickplayer"
if exist "%LOCALAPPDATA%\TickPlayer" rmdir /s /q "%LOCALAPPDATA%\TickPlayer"

echo TickPlayer was removed.
echo.
pause
exit /b 0
