@echo off
setlocal
rem Installs TickPlayer for the current Windows user. No admin rights needed.
rem Run it from the extracted release folder.
rem
rem   install.cmd           asks whether TickPlayer should start with VLC (default: yes)
rem   install.cmd /auto     starts with VLC, no question
rem   install.cmd /manual   only the View ^> TickPlayer menu item

set "SRC=%~dp0"
set "LUA=%APPDATA%\vlc\lua"

if not exist "%SRC%lua\extensions\tickplayer.lua" (
    echo The TickPlayer files were not found next to install.cmd.
    echo Extract the whole zip file first, then run install.cmd from the extracted folder.
    goto :fail
)

tasklist /fi "imagename eq vlc.exe" 2>nul | find /i "vlc.exe" >nul
if not errorlevel 1 (
    echo VLC is running. Close all VLC windows, then run install.cmd again.
    goto :fail
)

for %%D in ("%LUA%\extensions\tickplayer" "%LUA%\intf" "%LUA%\modules") do (
    if not exist "%%~D" mkdir "%%~D"
)
copy /y "%SRC%lua\extensions\tickplayer.lua" "%LUA%\extensions\" >nul || goto :copyfail
copy /y "%SRC%lua\extensions\tickplayer\*.exe" "%LUA%\extensions\tickplayer\" >nul || goto :copyfail
copy /y "%SRC%lua\intf\tickplayer.lua" "%LUA%\intf\" >nul || goto :copyfail
copy /y "%SRC%lua\modules\tickplayer_core.lua" "%LUA%\modules\" >nul || goto :copyfail

rem Downloaded files carry a "from the internet" mark that can make
rem SmartScreen block the helper when VLC starts it. Remove the mark.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$l = Join-Path $env:APPDATA 'vlc\lua'; Get-ChildItem -LiteralPath (Join-Path $l 'extensions\tickplayer') | Unblock-File; 'extensions\tickplayer.lua', 'intf\tickplayer.lua', 'modules\tickplayer_core.lua' | ForEach-Object { Unblock-File -LiteralPath (Join-Path $l $_) }" >nul 2>&1

echo TickPlayer was installed to %LUA%
echo.

if /i "%~1"=="/auto" goto :autostart
if /i "%~1"=="/manual" goto :manual
choice /c YN /t 60 /d Y /m "Turn TickPlayer on automatically every time VLC starts"
if errorlevel 2 goto :manual

:autostart
powershell -NoProfile -ExecutionPolicy Bypass -File "%SRC%tickplayer-autostart.ps1" -Enable
if errorlevel 2 (
    echo Auto-start was not turned on because VLC already uses another Lua interface.
    echo Turn TickPlayer on with View ^> TickPlayer instead.
    goto :done
)
if errorlevel 1 (
    echo VLC's settings could not be changed. Turn TickPlayer on with View ^> TickPlayer instead.
    goto :done
)
echo.
echo Done. TickPlayer starts automatically with VLC: open a video and hover over the seek bar.
echo To stop it from starting with VLC, choose View ^> TickPlayer.
goto :done

:manual
powershell -NoProfile -ExecutionPolicy Bypass -File "%SRC%tickplayer-autostart.ps1" -Disable >nul 2>&1
echo.
echo Done. Start VLC, open a video and turn TickPlayer on with View ^> TickPlayer.

:done
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
