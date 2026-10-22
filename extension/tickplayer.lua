--[[
  TickPlayer - seekbar thumbnail previews for VLC media player (Windows)
  https://github.com/Skora120/TickPlayer

  Hover over VLC's seek bar to see a thumbnail of that moment, like on
  YouTube. Turn it on with View > TickPlayer.

  VLC's Lua API cannot draw over the interface or see the mouse, so this
  extension starts a small companion program (TickPlayerHelper.exe, in the
  "tickplayer" folder next to this file) and tells it which file is playing
  through a session file. The helper finds the seek bar with Windows UI
  Automation and makes thumbnails with VLC's own libVLC.

  License: MIT
]]

local VERSION = "1.0.0"

local session = nil -- { path = "<session file>" } while active

function descriptor()
    return {
        title = "TickPlayer",
        version = VERSION,
        author = "Skora120",
        url = "https://github.com/Skora120/TickPlayer",
        shortdesc = "TickPlayer", -- the text shown in the View menu
        description = "Shows a thumbnail of the video when you hover over the seek bar, "
            .. "like on YouTube. Turn it on or off with View > TickPlayer. Windows only.",
        capabilities = { "input-listener" },
    }
end

function activate()
    vlc.msg.info("[TickPlayer] " .. VERSION .. " activated")
    if package.config:sub(1, 1) ~= "\\" then
        fail("TickPlayer currently works on Windows only.")
        return
    end
    if not (vlc.io and vlc.io.open and vlc.io.mkdir) then
        fail("This VLC is too old for TickPlayer. Please update to VLC 3.0.3 or newer.")
        return
    end

    local helper = find_helper()
    if not helper then
        fail("TickPlayerHelper.exe was not found.\n\n"
            .. "Put the \"tickplayer\" folder from the download next to tickplayer.lua "
            .. "(in VLC's lua\\extensions folder) and restart VLC.")
        return
    end

    local dir = vlc.config.userdatadir() .. "\\tickplayer"
    vlc.io.mkdir(dir, "0700")
    math.randomseed(os.time() + math.floor(os.clock() * 1000))
    session = { path = string.format("%s\\session-%08x.txt", dir, math.random(0, 0x7fffffff)) }

    if not write_session(true) then
        session = nil
        fail("Could not write the session file in " .. dir)
        return
    end
    launch(helper, session.path)
end

function deactivate()
    if session then
        write_session(false) -- the helper sees active=0, exits and deletes the file
        session = nil
    end
    vlc.msg.info("[TickPlayer] deactivated")
end

function close()
    vlc.deactivate()
end

function input_changed()
    if session then
        write_session(true)
    end
end

-- Writes the current state for the helper. The "end=1" line lets the helper
-- tell a complete file from one that is still being written.
function write_session(active)
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
    return true
end

function one_line(s)
    return (s:gsub("[\r\n]", " "))
end

-- Finds the helper executable that matches VLC's bitness.
function find_helper()
    -- 32-bit VLC sees PROCESSOR_ARCHITECTURE=x86, even on 64-bit Windows.
    local exe = (os.getenv("PROCESSOR_ARCHITECTURE") == "x86") and "TickPlayerHelper-x86.exe" or "TickPlayerHelper.exe"

    local dirs = {}
    local source = debug and debug.getinfo and debug.getinfo(1, "S").source or ""
    local script_dir = source:match("^@(.*)[/\\][^/\\]*$")
    if script_dir then
        table.insert(dirs, script_dir)
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

-- Starts the helper without waiting for it.
function launch(helper, session_path)
    local cmd = 'start "" ' .. quote(for_cmd(helper)) .. ' --session ' .. quote(for_cmd(session_path))
    vlc.msg.dbg("[TickPlayer] " .. cmd)
    os.execute(cmd)
end

-- os.execute passes the command through the ANSI code page, which mangles
-- non-ASCII (UTF-8) paths such as C:\Users\Zoë. Paths under VLC's user
-- folder are rewritten to use %APPDATA%, which cmd.exe expands itself.
function for_cmd(path)
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

function quote(s)
    return '"' .. s .. '"'
end

function fail(message)
    vlc.msg.err("[TickPlayer] " .. message)
    local d = vlc.dialog("TickPlayer")
    d:add_label((message:gsub("\n", "<br>")), 1, 1, 1, 1)
    d:add_button("OK", function()
        d:delete()
        vlc.deactivate()
    end, 1, 2, 1, 1)
    d:show()
end
