@echo off
setlocal
rem Installs TickPlayer for the current Windows user. No admin rights needed.
rem Run it from the extracted release folder (next to tickplayer.lua).

set "SRC=%~dp0"
set "DEST=%APPDATA%\vlc\lua\extensions"

if not exist "%SRC%tickplayer.lua" (
    echo tickplayer.lua was not found next to install.cmd.
    echo Extract the whole zip file first, then run install.cmd from the extracted folder.
    goto :fail
)
if not exist "%SRC%tickplayer\TickPlayerHelper.exe" (
    echo The tickplayer folder is missing. Extract the whole zip file first.
    goto :fail
)

tasklist /fi "imagename eq vlc.exe" 2>nul | find /i "vlc.exe" >nul
if not errorlevel 1 (
    echo VLC is running. Close all VLC windows, then run install.cmd again.
    goto :fail
)

if not exist "%DEST%\tickplayer" mkdir "%DEST%\tickplayer"
copy /y "%SRC%tickplayer.lua" "%DEST%\" >nul || goto :copyfail
copy /y "%SRC%tickplayer\*.exe" "%DEST%\tickplayer\" >nul || goto :copyfail

rem Downloaded files carry a "from the internet" mark that can make
rem SmartScreen block the helper when VLC starts it. Remove the mark.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath (Join-Path $env:APPDATA 'vlc\lua\extensions\tickplayer') | Unblock-File; Unblock-File -LiteralPath (Join-Path $env:APPDATA 'vlc\lua\extensions\tickplayer.lua')" >nul 2>&1

echo.
echo TickPlayer was installed to:
echo   %DEST%
echo.
echo Start VLC, open a video and turn it on with View ^> TickPlayer.

for %%P in ("%ProgramFiles%" "%ProgramFiles(x86)%") do (
    if exist "%%~P\VideoLAN\VLC\lua\extensions\tickplayer.lua" (
        echo.
        echo Note: another copy exists in "%%~P\VideoLAN\VLC\lua\extensions".
        echo VLC will list TickPlayer twice. Delete that copy ^(needs admin rights^).
    )
)
echo.
pause
exit /b 0

:copyfail
echo Copying failed. Make sure VLC is closed and try again.
:fail
echo.
pause
exit /b 1
