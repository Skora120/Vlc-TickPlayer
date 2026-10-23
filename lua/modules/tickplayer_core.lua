--[[
  TickPlayer shared code, used by the View menu extension
  (lua/extensions/tickplayer.lua) and the auto-start interface
  (lua/intf/tickplayer.lua). https://github.com/Skora120/Vlc-TickPlayer

  Both start TickPlayerHelper.exe and keep a session file up to date with
  the playing media: key=value lines ending with "end=1", in
  %APPDATA%\vlc\tickplayer. The helper exits when the file says active=0,
  when the file disappears, or when VLC exits.

  License: MIT
]]

local core = {}

-- Name of a string variable on the libvlc object. The auto-start interface
-- sets it to "on" while it runs the helper; the extension sets it to "off"
-- to stop it. Absent when auto-start is not running.
core.AUTO_VAR = "tickplayer-auto"

local function has_module(list, name)
    for m in list:gmatch("[^:,]+") do
        if m == name then
            return true
        end
    end
    return false
end

local function one_line(s)
    return (s:gsub("[\r\n]", " "))
end

local function quote(s)
    return '"' .. s .. '"'
end

-- os.execute passes the command through the ANSI code page, which mangles
-- non-ASCII (UTF-8) paths such as C:\Users\Zoë. Paths under VLC's user
-- folder are rewritten to use %APPDATA%, which cmd.exe expands itself.
local function for_cmd(path)
    if not path:find("[\128-\255]") then
        return path
    end
    local userdata = vlc.config.userdatadir()
    if path:sub(1, #userdata) == userdata and userdata:lower():match("\\vlc$") then
        return "%APPDATA%\\vlc" .. path:sub(#userdata + 1)
    end
    vlc.msg.warn("[TickPlayer] path with non-ASCII characters may not work: " .. path)
    return path
end

-- Returns an error message if TickPlayer cannot run in this VLC, else nil.
function core.unsupported()
    if package.config:sub(1, 1) ~= "\\" then
        return "TickPlayer currently works on Windows only."
    end
    if not (vlc.io and vlc.io.open and vlc.io.mkdir) then
        return "This VLC is too old for TickPlayer. Please update to VLC 3.0.3 or newer."
    end
    return nil
end

-- Finds the helper executable that matches VLC's bitness, or nil.
function core.find_helper()
    -- 32-bit VLC sees PROCESSOR_ARCHITECTURE=x86, even on 64-bit Windows.
    local exe = (os.getenv("PROCESSOR_ARCHITECTURE") == "x86") and "TickPlayerHelper-x86.exe" or "TickPlayerHelper.exe"

    local dirs = {}
    -- This file is lua\modules\tickplayer_core.lua; the helper is in lua\extensions\tickplayer.
    local source = debug and debug.getinfo and debug.getinfo(1, "S").source or ""
    local lua_dir = source:match("^@(.*)[/\\]modules[/\\][^/\\]*$")
    if lua_dir then
        table.insert(dirs, lua_dir .. "\\extensions")
    end
    table.insert(dirs, vlc.config.userdatadir() .. "\\lua\\extensions")
    table.insert(dirs, vlc.config.datadir() .. "\\lua\\extensions")

    for _, d in ipairs(dirs) do
        local path = d .. "\\tickplayer\\" .. exe
        local f = vlc.io.open(path, "rb")
        if f then
            f:close()
            return path
        end
    end
    return nil
end

-- Creates a session (not yet written or started). kind goes into the file name.
function core.new_session(kind)
    local dir = vlc.config.userdatadir() .. "\\tickplayer"
    vlc.io.mkdir(dir, "0700")
    math.randomseed(os.time() + math.floor(os.clock() * 1000))
    return { path = string.format("%s\\session-%s-%08x.txt", dir, kind, math.random(0, 0x7fffffff)) }
end

-- URI of the playing media, or "".
function core.current_uri()
    local item = vlc.input.item()
    return item and item:uri() or ""
end

-- Writes the current state for the helper. Returns false if the file cannot be written.
function core.write_session(session, active)
    local uri, name, title = "", "", ""
    local item = vlc.input.item()
    if item then
        uri = item:uri() or ""
        name = item:name() or ""
        local metas = item:metas()
        title = (metas and metas.title) or ""
    end

    local f = vlc.io.open(session.path, "wb")
    if not f then
        vlc.msg.err("[TickPlayer] cannot write " .. session.path)
        return false
    end
    f:write(table.concat({
        "version=1",
        "active=" .. (active and "1" or "0"),
        "uri=" .. one_line(uri),
        "name=" .. one_line(name),
        "title=" .. one_line(title),
        "end=1",
        "",
    }, "\n"))
    f:close()
    session.uri = uri
    return true
end

-- Starts the helper for a session without waiting for it.
function core.launch(helper, session)
    local cmd = 'start "" ' .. quote(for_cmd(helper)) .. ' --session ' .. quote(for_cmd(session.path))
    vlc.msg.dbg("[TickPlayer] " .. cmd)
    os.execute(cmd)
end

-- True if VLC is set up to run the auto-start interface.
function core.autostart_configured()
    return (vlc.config.get("lua-intf") or "") == "tickplayer"
        and has_module(vlc.config.get("extraintf") or "", "luaintf")
end

-- Stops VLC from running the auto-start interface. VLC saves changed
-- settings when it exits, so this takes effect from the next start.
function core.disable_autostart()
    if (vlc.config.get("lua-intf") or "") ~= "tickplayer" then
        return
    end
    local kept = {}
    for m in (vlc.config.get("extraintf") or ""):gmatch("[^:,]+") do
        if m ~= "luaintf" then
            table.insert(kept, m)
        end
    end
    vlc.config.set("extraintf", table.concat(kept, ":"))
    vlc.config.set("lua-intf", "dummy")
end

return core
