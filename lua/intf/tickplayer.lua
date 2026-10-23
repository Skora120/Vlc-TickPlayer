--[[
  TickPlayer auto-start - https://github.com/Skora120/Vlc-TickPlayer

  A VLC Lua interface that turns TickPlayer on every time VLC starts, so you
  don't have to use View > TickPlayer. install.cmd enables it by setting, in
  VLC's preferences:
      extraintf = ...:luaintf     (Interface > Main interfaces > Lua interpreter)
      lua-intf  = tickplayer      (Interface > Main interfaces > Lua > Lua interface)

  It starts the helper when the first local file plays and keeps the session
  file up to date as the media changes. View > TickPlayer can turn it off
  for the current session or stop it from starting with VLC.

  License: MIT
]]

local core = require "tickplayer_core"

local POLL_US = 300000 -- check for media changes every 0.3 s

local libvlc = vlc.object.libvlc()
local session = nil
local helper = nil

local function stop()
    if session then
        core.write_session(session, false)
        session = nil
    end
end

-- One polling step. Returns false when auto-start has been turned off.
local function step()
    if vlc.var.get(libvlc, core.AUTO_VAR) ~= "on" then
        return false
    end
    local uri = core.current_uri()
    if not session then
        -- Wait for a local file, so the helper doesn't run for streams and
        -- finds VLC's window already open.
        if uri:match("^file:") then
            session = core.new_session("auto")
            if core.write_session(session, true) then
                core.launch(helper, session)
            else
                session = nil
                return false
            end
        end
    elseif uri ~= session.uri then
        core.write_session(session, true)
    end
    return true
end

local problem = core.unsupported()
if problem then
    vlc.msg.err("[TickPlayer] " .. problem)
    return
end
helper = core.find_helper()
if not helper then
    vlc.msg.err("[TickPlayer] TickPlayerHelper.exe not found; reinstall TickPlayer")
    return
end

vlc.var.create(libvlc, core.AUTO_VAR, "on")
vlc.msg.info("[TickPlayer] auto-start interface running")

-- vlc.misc.mwait raises an error when VLC shuts the interface down.
local ok, err = pcall(function()
    while step() do
        vlc.misc.mwait(vlc.misc.mdate() + POLL_US)
    end
end)
stop()
if not ok and not tostring(err):match("Interrupted") then
    vlc.msg.err("[TickPlayer] auto-start stopped: " .. tostring(err))
end
