@echo off
setlocal
rem Removes TickPlayer and its cached thumbnails for the current Windows user.

tasklist /fi "imagename eq vlc.exe" 2>nul | find /i "vlc.exe" >nul
if not errorlevel 1 (
    echo VLC is running. Close all VLC windows, then run uninstall.cmd again.
    echo.
    pause
    exit /b 1
)

set "EXT=%APPDATA%\vlc\lua\extensions"
if exist "%EXT%\tickplayer.lua" del /f /q "%EXT%\tickplayer.lua"
if exist "%EXT%\tickplayer" rmdir /s /q "%EXT%\tickplayer"
if exist "%APPDATA%\vlc\tickplayer" rmdir /s /q "%APPDATA%\vlc\tickplayer"
if exist "%LOCALAPPDATA%\TickPlayer" rmdir /s /q "%LOCALAPPDATA%\TickPlayer"

echo TickPlayer was removed.
echo.
pause
exit /b 0
