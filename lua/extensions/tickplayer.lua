--[[
  TickPlayer - seekbar thumbnail previews for VLC media player (Windows)
  https://github.com/Skora120/TickPlayer

  Hover over VLC's seek bar to see a thumbnail of that moment, like on
  YouTube.

  VLC's Lua API cannot draw over the interface or see the mouse, so
  TickPlayer starts a small companion program (TickPlayerHelper.exe, in the
  "tickplayer" folder next to this file) and tells it which file is playing.
  The helper finds the seek bar with Windows UI Automation and makes
  thumbnails with VLC's own libVLC.

  Normally TickPlayer starts with VLC (see lua/intf/tickplayer.lua). This
  extension is the View > TickPlayer menu item: it turns previews on by hand
  when auto-start is off, and offers to turn auto-start off when it is on.

  License: MIT
]]

local VERSION = "1.0.0"

local core = nil    -- lua/modules/tickplayer_core.lua, loaded on activation
local session = nil -- manual session while this extension runs the helper

function descriptor()
    return {
        title = "TickPlayer",
        version = VERSION,
        author = "Skora120",
        url = "https://github.com/Skora120/TickPlayer",
        shortdesc = "TickPlayer", -- the text shown in the View menu
        description = "Shows a thumbnail of the video when you hover over the seek bar, "
            .. "like on YouTube. Windows only.",
        capabilities = { "input-listener" },
    }
end

function activate()
    vlc.msg.info("[TickPlayer] " .. VERSION .. " activated")
    -- VLC only sets up the module path for activated extensions, so the
    -- shared code can't be loaded at the top of this file.
    local ok, loaded = pcall(require, "tickplayer_core")
    if not ok then
        vlc.msg.err("[TickPlayer] " .. tostring(loaded))
        message("TickPlayer is not installed completely (tickplayer_core.lua is missing).\n\n"
            .. "Run install.cmd from the download again.")
        return
    end
    core = loaded

    local problem = core.unsupported()
    if problem then
        message(problem)
        return
    end

    if vlc.var.get(vlc.object.libvlc(), core.AUTO_VAR) == "on" then
        autostart_dialog()
        return
    end

    local helper = core.find_helper()
    if not helper then
        message("TickPlayerHelper.exe was not found.\n\n"
            .. "Run install.cmd from the download again.")
        return
    end
    session = core.new_session("manual")
    if not core.write_session(session, true) then
        session = nil
        message("Could not write TickPlayer's session file.")
        return
    end
    core.launch(helper, session)
end

function deactivate()
    if session then
        core.write_session(session, false) -- the helper sees active=0, exits and deletes the file
        session = nil
    end
    vlc.msg.info("[TickPlayer] deactivated")
end

function close()
    vlc.deactivate()
end

function input_changed()
    if session then
        core.write_session(session, true)
    end
end

-- Shown when auto-start already runs TickPlayer in this VLC.
function autostart_dialog()
    local d = vlc.dialog("TickPlayer")
    d:add_label("TickPlayer is already on: it starts automatically with VLC.", 1, 1, 3, 1)
    d:add_button("Keep it on", function()
        d:delete()
        vlc.deactivate()
    end, 1, 2, 1, 1)
    d:add_button("Turn off until VLC restarts", function()
        vlc.var.set(vlc.object.libvlc(), core.AUTO_VAR, "off")
        d:delete()
        vlc.deactivate()
    end, 2, 2, 1, 1)
    d:add_button("Turn off and don't start with VLC", function()
        vlc.var.set(vlc.object.libvlc(), core.AUTO_VAR, "off")
        core.disable_autostart()
        d:delete()
        vlc.deactivate()
    end, 3, 2, 1, 1)
    d:show()
end

function message(text)
    vlc.msg.err("[TickPlayer] " .. text)
    local d = vlc.dialog("TickPlayer")
    d:add_label((text:gsub("\n", "<br>")), 1, 1, 1, 1)
    d:add_button("OK", function()
        d:delete()
        vlc.deactivate()
    end, 1, 2, 1, 1)
    d:show()
end
