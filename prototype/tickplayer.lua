--[[
    TickPlayer - VLC Timeline Preview Extension

    Provides hover-over-timeline thumbnail previews for VLC Media Player.
    Works by launching a companion overlay application that displays
    thumbnail previews when hovering over VLC's seekbar.

    Author: TickPlayer Team
    License: MIT
    Version: 1.0.0
]]--

-- ============================================================================
-- CONFIGURATION
-- ============================================================================

local CONFIG = {
    -- Default settings (can be overridden by user config file)
    http_port = 8080,
    interval_mode = "percentage",  -- "seconds" or "percentage"
    interval_seconds = 10,
    interval_percentage = 2,
    thumbnail_width = 240,
    thumbnail_height = 135,
    quality = "medium",  -- "low", "medium", "high", "best"
    cache_purge_days = 30,
    cache_max_mb = 500,

    -- Internal settings
    overlay_process = nil,
    session_id = nil,
    is_active = false,
    config_file = nil,
    overlay_path = nil,
}

-- Quality to FFmpeg -q:v mapping
local QUALITY_MAP = {
    low = 8,
    medium = 5,
    high = 3,
    best = 1
}

-- ============================================================================
-- UTILITY FUNCTIONS (defined early for use throughout)
-- ============================================================================

-- Helper function to run commands and capture output
-- Note: On Windows, a brief console flash may occur for some commands
function run_command_silent(cmd)
    local is_windows = package.config:sub(1,1) == '\\'
    local full_cmd
    if is_windows then
        -- Use cmd.exe with output redirection
        full_cmd = 'cmd /c "' .. cmd .. '" 2>&1'
    else
        full_cmd = cmd .. ' 2>&1'
    end
    local handle = io.popen(full_cmd)
    if handle then
        local result = handle:read("*a")
        handle:close()
        return result
    end
    return nil
end

-- ============================================================================
-- EXTENSION DESCRIPTOR
-- ============================================================================

function descriptor()
    return {
        title = "TickPlayer",
        version = "1.0.0",
        author = "TickPlayer Team",
        url = "https://github.com/tickplayer/tickplayer",
        shortdesc = "Timeline Preview",
        description = [[
TickPlayer provides hover-over-timeline thumbnail previews for VLC.
When enabled, hovering over the seekbar shows a preview of that moment in the video.

Features:
- Floating thumbnail preview that follows your mouse
- Automatic thumbnail caching for instant previews
- Configurable thumbnail size and quality
- Multi-instance support
- Cross-platform (Windows, Linux, macOS)
        ]],
        capabilities = {"menu"}
    }
end

-- ============================================================================
-- MENU FUNCTIONS
-- ============================================================================

function menu()
    if CONFIG.is_active then
        return {"Disable Preview", "Settings...", "Setup..."}
    else
        return {"Enable Preview", "Settings...", "Setup..."}
    end
end

function trigger_menu(id)
    if id == 1 then
        toggle_preview()
    elseif id == 2 then
        show_settings()
    elseif id == 3 then
        show_setup()
    end
end

-- ============================================================================
-- CORE FUNCTIONS
-- ============================================================================

function activate()
    vlc.msg.info("[TickPlayer] Extension activated")

    -- Initialize paths
    init_paths()

    -- Load user configuration
    load_config()
end

function deactivate()
    vlc.msg.info("[TickPlayer] Extension deactivated")

    -- Ensure overlay is stopped
    if CONFIG.is_active then
        stop_overlay()
    end
end

function close()
    deactivate()
end

-- ============================================================================
-- PREVIEW TOGGLE
-- ============================================================================

function toggle_preview()
    if CONFIG.is_active then
        stop_overlay()
        vlc.msg.info("[TickPlayer] Preview disabled")
    else
        start_overlay()
        vlc.msg.info("[TickPlayer] Preview enabled")
    end
end

function start_overlay()
    -- Check if video is playing
    local item = vlc.input.item()
    if not item then
        show_message("No video playing", "Please open a video file first.")
        return
    end

    -- Get video URI
    local uri = item:uri()
    if not uri then
        show_message("Error", "Cannot determine video location.")
        return
    end

    -- Check if it's a local file
    if not uri:match("^file:///") then
        show_message("Local Files Only", "TickPlayer only supports local video files, not network streams.")
        return
    end

    -- Generate session ID
    CONFIG.session_id = generate_session_id()

    -- Get VLC process ID (platform-specific)
    local vlc_pid = get_vlc_pid()

    -- Find an available HTTP port
    local http_port = find_available_port(CONFIG.http_port)

    -- Write session info for overlay to read
    write_session_file(vlc_pid, http_port, uri)

    -- Enable VLC HTTP interface
    enable_http_interface(http_port)

    -- Launch overlay application
    launch_overlay(vlc_pid, CONFIG.session_id, http_port)

    CONFIG.is_active = true
end

function stop_overlay()
    if CONFIG.session_id then
        -- Signal overlay to stop by removing session file
        remove_session_file()

        -- Kill overlay process if we have its reference
        kill_overlay_process()
    end

    CONFIG.is_active = false
    CONFIG.session_id = nil
end

-- ============================================================================
-- SETTINGS DIALOG
-- ============================================================================

local settings_dialog = nil

function show_settings()
    if settings_dialog then
        settings_dialog:delete()
    end

    settings_dialog = vlc.dialog("TickPlayer Settings")

    -- HTTP API Settings Section
    settings_dialog:add_label("<h3>HTTP API Settings</h3>", 1, 1, 4, 1)
    settings_dialog:add_label("Starting Port:", 1, 2, 1, 1)
    local port_input = settings_dialog:add_text_input(tostring(CONFIG.http_port), 2, 2, 1, 1)
    settings_dialog:add_label("(Range: 1024-65535)", 3, 2, 2, 1)

    -- Thumbnail Generation Section
    settings_dialog:add_label("<h3>Thumbnail Generation</h3>", 1, 3, 4, 1)

    settings_dialog:add_label("Interval Mode:", 1, 4, 1, 1)
    local interval_dropdown = settings_dialog:add_dropdown(2, 4, 2, 1)
    interval_dropdown:add_value("Every X seconds", 1)
    interval_dropdown:add_value("Percentage of duration", 2)

    settings_dialog:add_label("Interval (seconds):", 1, 5, 1, 1)
    local interval_sec_input = settings_dialog:add_text_input(tostring(CONFIG.interval_seconds), 2, 5, 1, 1)

    settings_dialog:add_label("Interval (%):", 3, 5, 1, 1)
    local interval_pct_input = settings_dialog:add_text_input(tostring(CONFIG.interval_percentage), 4, 5, 1, 1)

    -- Thumbnail Size
    settings_dialog:add_label("Thumbnail Width:", 1, 6, 1, 1)
    local width_input = settings_dialog:add_text_input(tostring(CONFIG.thumbnail_width), 2, 6, 1, 1)
    settings_dialog:add_label("Height:", 3, 6, 1, 1)
    local height_input = settings_dialog:add_text_input(tostring(CONFIG.thumbnail_height), 4, 6, 1, 1)

    -- Size presets
    settings_dialog:add_button("Small (160x90)", function()
        width_input:set_text("160")
        height_input:set_text("90")
    end, 1, 7, 1, 1)
    settings_dialog:add_button("Medium (240x135)", function()
        width_input:set_text("240")
        height_input:set_text("135")
    end, 2, 7, 1, 1)
    settings_dialog:add_button("Large (320x180)", function()
        width_input:set_text("320")
        height_input:set_text("180")
    end, 3, 7, 1, 1)

    -- Quality
    settings_dialog:add_label("Quality:", 1, 8, 1, 1)
    local quality_dropdown = settings_dialog:add_dropdown(2, 8, 2, 1)
    quality_dropdown:add_value("Low", 1)
    quality_dropdown:add_value("Medium", 2)
    quality_dropdown:add_value("High", 3)
    quality_dropdown:add_value("Best", 4)

    -- Cache Management Section
    settings_dialog:add_label("<h3>Cache Management</h3>", 1, 9, 4, 1)

    settings_dialog:add_label("Auto-purge after:", 1, 10, 1, 1)
    local purge_input = settings_dialog:add_text_input(tostring(CONFIG.cache_purge_days), 2, 10, 1, 1)
    settings_dialog:add_label("days (0 = never)", 3, 10, 2, 1)

    settings_dialog:add_label("Max cache size:", 1, 11, 1, 1)
    local cache_size_input = settings_dialog:add_text_input(tostring(CONFIG.cache_max_mb), 2, 11, 1, 1)
    settings_dialog:add_label("MB", 3, 11, 1, 1)

    settings_dialog:add_button("Clear Cache Now", clear_cache, 1, 12, 2, 1)

    -- Action Buttons
    settings_dialog:add_button("Save Settings", function()
        -- Validate and save settings
        local new_port = tonumber(port_input:get_text())
        if new_port and new_port >= 1024 and new_port <= 65535 then
            CONFIG.http_port = new_port
        end

        local interval_mode_val = interval_dropdown:get_value()
        CONFIG.interval_mode = (interval_mode_val and interval_mode_val == 1) and "seconds" or "percentage"

        CONFIG.interval_seconds = tonumber(interval_sec_input:get_text()) or CONFIG.interval_seconds
        CONFIG.interval_percentage = tonumber(interval_pct_input:get_text()) or CONFIG.interval_percentage
        CONFIG.thumbnail_width = tonumber(width_input:get_text()) or CONFIG.thumbnail_width
        CONFIG.thumbnail_height = tonumber(height_input:get_text()) or CONFIG.thumbnail_height

        local quality_val = quality_dropdown:get_value()
        CONFIG.quality = ({"low", "medium", "high", "best"})[quality_val or 2] or "medium"

        CONFIG.cache_purge_days = tonumber(purge_input:get_text()) or CONFIG.cache_purge_days
        CONFIG.cache_max_mb = tonumber(cache_size_input:get_text()) or CONFIG.cache_max_mb

        save_config()
        settings_dialog:delete()
        settings_dialog = nil
        vlc.msg.info("[TickPlayer] Settings saved")
    end, 1, 13, 1, 1)

    settings_dialog:add_button("Reset to Defaults", function()
        port_input:set_text("8080")
        interval_sec_input:set_text("10")
        interval_pct_input:set_text("2")
        width_input:set_text("240")
        height_input:set_text("135")
        purge_input:set_text("30")
        cache_size_input:set_text("500")
    end, 2, 13, 1, 1)

    settings_dialog:add_button("Close", function()
        settings_dialog:delete()
        settings_dialog = nil
    end, 3, 13, 1, 1)

    settings_dialog:show()
end

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

function init_paths()
    -- Determine OS
    local is_windows = package.config:sub(1,1) == '\\'

    if is_windows then
        -- Windows paths
        local appdata = os.getenv("APPDATA") or ""
        local localappdata = os.getenv("LOCALAPPDATA") or ""
        local programfiles = os.getenv("ProgramFiles") or "C:\\Program Files"

        CONFIG.config_file = appdata .. "\\vlc\\tickplayer_config.json"
        CONFIG.cache_dir = localappdata .. "\\TickPlayer\\cache"
        CONFIG.session_dir = localappdata .. "\\TickPlayer\\sessions"

        -- Overlay path - check Program Files first, then AppData
        CONFIG.overlay_path = programfiles .. "\\VideoLAN\\VLC\\lua\\extensions\\TickPlayer\\overlay\\tickplayer_overlay.exe"
        CONFIG.overlay_script = programfiles .. "\\VideoLAN\\VLC\\lua\\extensions\\TickPlayer\\overlay\\main.py"
        CONFIG.setup_script = programfiles .. "\\VideoLAN\\VLC\\lua\\extensions\\TickPlayer\\overlay\\setup.py"
    else
        -- Unix paths (Linux/macOS)
        local home = os.getenv("HOME") or ""

        if is_macos() then
            CONFIG.config_file = home .. "/Library/Application Support/org.videolan.vlc/tickplayer_config.json"
            CONFIG.cache_dir = home .. "/Library/Caches/TickPlayer"
            CONFIG.session_dir = home .. "/Library/Caches/TickPlayer/sessions"
            CONFIG.overlay_path = home .. "/Library/Application Support/org.videolan.vlc/lua/extensions/TickPlayer/overlay/tickplayer_overlay"
        else
            CONFIG.config_file = home .. "/.config/vlc/tickplayer_config.json"
            CONFIG.cache_dir = home .. "/.cache/tickplayer"
            CONFIG.session_dir = home .. "/.cache/tickplayer/sessions"
            CONFIG.overlay_path = home .. "/.local/share/vlc/lua/extensions/TickPlayer/overlay/tickplayer_overlay"
        end
    end

    -- Create directories if needed
    create_directory(CONFIG.cache_dir)
    create_directory(CONFIG.session_dir)
end

function is_macos()
    -- Simple heuristic to detect macOS
    local f = io.popen("uname -s 2>/dev/null")
    if f then
        local result = f:read("*a")
        f:close()
        return result and result:match("Darwin")
    end
    return false
end

function create_directory(path)
    local is_windows = package.config:sub(1,1) == '\\'
    if is_windows then
        -- Use mkdir with 2>nul to suppress errors if exists
        os.execute('mkdir "' .. path .. '" 2>nul')
    else
        os.execute('mkdir -p "' .. path .. '" 2>/dev/null')
    end
end

function generate_session_id()
    -- Generate a unique session ID
    math.randomseed(os.time() + math.floor(os.clock() * 1000))
    local chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    local id = ""
    for i = 1, 16 do
        local idx = math.random(1, #chars)
        id = id .. chars:sub(idx, idx)
    end
    return id
end

function get_vlc_pid()
    -- Get VLC's process ID (platform-specific)
    local is_windows = package.config:sub(1,1) == '\\'

    if is_windows then
        -- On Windows, use WMIC to get VLC PID
        local result = run_command_silent('wmic process where "name=\'vlc.exe\'" get ProcessId')
        if result then
            -- Parse the PID from output (skip header line)
            for line in result:gmatch("[^\r\n]+") do
                local pid = line:match("^%s*(%d+)%s*$")
                if pid then
                    return pid
                end
            end
        end
    else
        -- On Unix, use pgrep
        local handle = io.popen("pgrep -x vlc 2>/dev/null | head -1")
        if handle then
            local result = handle:read("*a")
            handle:close()
            return result:match("(%d+)")
        end
    end

    return "0"  -- Fallback
end

function find_available_port(start_port)
    -- For now, just return the configured port
    -- In a real implementation, we would check if the port is in use
    return start_port
end

function write_session_file(pid, port, uri)
    local is_windows = package.config:sub(1,1) == '\\'
    local sep = is_windows and "\\" or "/"
    local session_file = CONFIG.session_dir .. sep .. CONFIG.session_id .. ".json"

    local f = io.open(session_file, "w")
    if f then
        -- Escape the URI for JSON
        local escaped_uri = uri:gsub("\\", "\\\\"):gsub('"', '\\"')

        local content = string.format([[{
    "vlc_pid": "%s",
    "http_port": %d,
    "video_uri": "%s",
    "config": {
        "interval_mode": "%s",
        "interval_seconds": %d,
        "interval_percentage": %.1f,
        "thumbnail_width": %d,
        "thumbnail_height": %d,
        "quality": "%s",
        "cache_dir": "%s"
    }
}]], pid, port, escaped_uri,
            CONFIG.interval_mode,
            CONFIG.interval_seconds,
            CONFIG.interval_percentage,
            CONFIG.thumbnail_width,
            CONFIG.thumbnail_height,
            CONFIG.quality,
            CONFIG.cache_dir:gsub("\\", "\\\\"))

        f:write(content)
        f:close()
        vlc.msg.info("[TickPlayer] Session file written: " .. session_file)
    else
        vlc.msg.err("[TickPlayer] Failed to write session file")
    end
end

function remove_session_file()
    if CONFIG.session_id then
        local is_windows = package.config:sub(1,1) == '\\'
        local sep = is_windows and "\\" or "/"
        local session_file = CONFIG.session_dir .. sep .. CONFIG.session_id .. ".json"
        os.remove(session_file)
    end
end

function enable_http_interface(port)
    -- VLC HTTP interface should be enabled via preferences
    -- This is informational - user needs to enable it manually
    vlc.msg.info("[TickPlayer] HTTP interface should be enabled on port " .. port)
    vlc.msg.info("[TickPlayer] Enable at: Tools > Preferences > All > Interface > Main interfaces > Web")
end

function launch_overlay(pid, session_id, port)
    local is_windows = package.config:sub(1,1) == '\\'
    local cmd

    -- Check if compiled overlay exists
    local overlay_check = io.open(CONFIG.overlay_path, "r")
    if overlay_check then
        overlay_check:close()
        if is_windows then
            -- Use start /b for background execution
            cmd = string.format('start /b "" "%s" --pid %s --session %s --port %d',
                CONFIG.overlay_path, pid, session_id, port)
        else
            cmd = string.format('"%s" --pid %s --session %s --port %d &',
                CONFIG.overlay_path, pid, session_id, port)
        end
    else
        -- Try Python script directly
        local py_path = CONFIG.overlay_script or (CONFIG.overlay_path:gsub("%.exe$", ".py"):gsub("tickplayer_overlay$", "main.py"))
        local script_check = io.open(py_path, "r")
        if script_check then
            script_check:close()
            if is_windows then
                -- Use python.exe with start to show console for debugging
                -- Change to pythonw and /b for silent operation after testing
                cmd = string.format('start "TickPlayer" python "%s" --pid %s --session %s --port %d',
                    py_path, pid, session_id, port)
            else
                cmd = string.format('python3 "%s" --pid %s --session %s --port %d &',
                    py_path, pid, session_id, port)
            end
        else
            vlc.msg.err("[TickPlayer] Overlay application not found at: " .. py_path)
            show_message("Overlay Not Found",
                "The TickPlayer overlay application was not found.\n" ..
                "Please ensure it is installed at:\n" .. py_path ..
                "\n\nTry running Setup first (View > TickPlayer > Setup...)")
            return
        end
    end

    vlc.msg.info("[TickPlayer] Launching overlay: " .. cmd)
    os.execute(cmd)
end

function kill_overlay_process()
    -- Signal overlay to stop by creating stop file
    local is_windows = package.config:sub(1,1) == '\\'
    local sep = is_windows and "\\" or "/"
    local stop_file = CONFIG.session_dir .. sep .. "stop_" .. (CONFIG.session_id or "")

    local f = io.open(stop_file, "w")
    if f then
        f:write("stop")
        f:close()
    end

    -- Also try to kill by session ID
    if is_windows then
        -- On Windows, the overlay will check for the stop file
    else
        os.execute('pkill -f "tickplayer.*' .. (CONFIG.session_id or "") .. '" 2>/dev/null')
    end
end

function show_message(title, message)
    local dlg = vlc.dialog(title)
    dlg:add_label(message, 1, 1, 1, 1)
    dlg:add_button("OK", function() dlg:delete() end, 1, 2, 1, 1)
    dlg:show()
end

function clear_cache()
    local is_windows = package.config:sub(1,1) == '\\'

    if is_windows then
        -- Use rmdir to remove cache directory
        os.execute('rmdir /s /q "' .. CONFIG.cache_dir .. '" 2>nul')
    else
        os.execute('rm -rf "' .. CONFIG.cache_dir .. '" 2>/dev/null')
    end

    create_directory(CONFIG.cache_dir)

    show_message("Cache Cleared", "Thumbnail cache has been cleared.")
end

-- ============================================================================
-- SETUP DIALOG
-- ============================================================================

local setup_dialog = nil
local setup_status_label = nil

function show_setup()
    if setup_dialog then
        setup_dialog:delete()
    end

    setup_dialog = vlc.dialog("TickPlayer Setup")

    -- Title
    setup_dialog:add_label("<h2>TickPlayer Auto-Setup</h2>", 1, 1, 3, 1)
    setup_dialog:add_label("This will automatically configure everything needed for TickPlayer.", 1, 2, 3, 1)

    -- Status section
    setup_dialog:add_label("<h3>Current Status</h3>", 1, 3, 3, 1)

    -- Python status (will be checked when clicking Check Status)
    setup_dialog:add_label("[?] Python", 1, 4, 1, 1)
    local python_label = setup_dialog:add_label("Click 'Check Status' to verify", 2, 4, 2, 1)

    -- Check dependencies (will be updated after check)
    setup_dialog:add_label("[?] Python Dependencies", 1, 5, 1, 1)
    local deps_label = setup_dialog:add_label("Click 'Check Status' to verify", 2, 5, 2, 1)

    -- Check VLC HTTP
    setup_dialog:add_label("[?] VLC HTTP Interface", 1, 6, 1, 1)
    local http_label = setup_dialog:add_label("Click 'Check Status' to verify", 2, 6, 2, 1)

    -- Status message area
    setup_dialog:add_label("<h3>Setup Progress</h3>", 1, 7, 3, 1)
    setup_status_label = setup_dialog:add_label("Ready. Click 'Check Status' or 'Run Auto-Setup'.", 1, 8, 3, 1)

    -- Buttons
    setup_dialog:add_button("Check Status", function()
        check_setup_status(python_label, deps_label, http_label)
    end, 1, 9, 1, 1)

    setup_dialog:add_button("Run Auto-Setup", function()
        run_auto_setup()
    end, 2, 9, 1, 1)

    setup_dialog:add_button("Close", function()
        setup_dialog:delete()
        setup_dialog = nil
    end, 3, 9, 1, 1)

    -- Instructions
    setup_dialog:add_label("<h3>What Auto-Setup Does</h3>", 1, 10, 3, 1)
    setup_dialog:add_label("1. Installs Python packages (Pillow, pywin32)", 1, 11, 3, 1)
    setup_dialog:add_label("2. Configures VLC HTTP interface", 1, 12, 3, 1)
    setup_dialog:add_label("3. Downloads FFmpeg (on first use)", 1, 13, 3, 1)
    setup_dialog:add_label("", 1, 14, 3, 1)
    setup_dialog:add_label("<i>Note: VLC restart required after setup</i>", 1, 15, 3, 1)

    setup_dialog:show()
end

function check_python_installed()
    local is_windows = package.config:sub(1,1) == '\\'
    local cmd
    if is_windows then
        cmd = 'python --version 2>&1'
    else
        cmd = 'python3 --version 2>/dev/null'
    end
    local result = run_command_silent(cmd)
    return result and result:match("Python")
end

function check_setup_status(python_label, deps_label, http_label)
    if setup_status_label then
        setup_status_label:set_text("Checking status...")
    end
    setup_dialog:update()

    -- First check Python (simple check without PowerShell wrapper)
    local is_windows = package.config:sub(1,1) == '\\'
    local python_ok = check_python_installed()

    if python_label then
        if python_ok then
            python_label:set_text("[OK] Python installed")
        else
            python_label:set_text("[X] Python not found - install Python 3.8+")
        end
    end
    setup_dialog:update()

    if not python_ok then
        if setup_status_label then
            setup_status_label:set_text("Python not found. Please install Python 3.8+ first.")
        end
        setup_dialog:update()
        return
    end

    -- Now run the full setup check via Python script
    local python_cmd = is_windows and "python" or "python3"
    local cmd = python_cmd .. ' "' .. CONFIG.setup_script .. '" --check 2>&1'

    local result = run_command_silent(cmd)

    if result and result ~= "" then
        vlc.msg.info("[TickPlayer] Status check output: " .. result)

        -- Parse results
        local deps_ok = result:match("Pillow: OK") or result:match("all_deps_ok.*true")
        local http_ok = result:match("Configured: Yes") or result:match("vlc_http_configured.*true")

        if deps_label then
            if deps_ok then
                deps_label:set_text("[OK] All packages installed")
            else
                deps_label:set_text("[X] Missing packages - run setup")
            end
        end

        if http_label then
            if http_ok then
                http_label:set_text("[OK] Enabled and configured")
            else
                http_label:set_text("[X] Not configured - run setup")
            end
        end

        if setup_status_label then
            if deps_ok and http_ok then
                setup_status_label:set_text("All checks passed! TickPlayer is ready to use.")
            else
                setup_status_label:set_text("Some items need setup. Click 'Run Auto-Setup'.")
            end
        end
    else
        if setup_status_label then
            setup_status_label:set_text("Could not run setup script. Check if setup.py exists.")
        end
    end

    setup_dialog:update()
end

function run_auto_setup()
    if setup_status_label then
        setup_status_label:set_text("Running auto-setup... This may take a minute.")
    end
    setup_dialog:update()

    local is_windows = package.config:sub(1,1) == '\\'
    local python_cmd = is_windows and "python" or "python3"
    local cmd = python_cmd .. ' "' .. CONFIG.setup_script .. '" --port ' .. CONFIG.http_port .. ' 2>&1'

    vlc.msg.info("[TickPlayer] Running: " .. cmd)

    local result = run_command_silent(cmd)

    if result and result ~= "" then
        vlc.msg.info("[TickPlayer] Setup output: " .. result)

        -- Check for success indicators
        local success = result:match("Setup completed successfully") or result:match('"success": true')
        local needs_restart = result:match("restart VLC") or result:match('"needs_restart": true')

        -- Check for specific errors
        local pip_error = result:match("pip error: ([^\n]+)")
        local error_msg = result:match("Error: ([^\n]+)")

        if setup_status_label then
            if success then
                if needs_restart then
                    setup_status_label:set_text("Setup complete! Please RESTART VLC for changes to take effect.")
                else
                    setup_status_label:set_text("Setup complete! TickPlayer is ready to use.")
                end
            elseif pip_error then
                setup_status_label:set_text("Pip error: " .. pip_error:sub(1, 80))
            elseif error_msg then
                setup_status_label:set_text("Error: " .. error_msg:sub(1, 80))
            elseif result:match("not recognized") or result:match("not found") then
                setup_status_label:set_text("Python not found. Please install Python 3.8+ first.")
            elseif result:match("ModuleNotFoundError") or result:match("ImportError") then
                setup_status_label:set_text("Missing Python module. Try running: pip install Pillow pywin32")
            else
                -- Show first meaningful line of output as status
                local first_line = result:match("([^\n]+)")
                if first_line and #first_line > 0 then
                    setup_status_label:set_text("Output: " .. first_line:sub(1, 80))
                else
                    setup_status_label:set_text("Setup finished. Check 'Check Status' for results.")
                end
            end
        end
    else
        if setup_status_label then
            -- Check if setup script exists
            local f = io.open(CONFIG.setup_script, "r")
            if f then
                f:close()
                setup_status_label:set_text("Could not run setup. Is Python installed and in PATH?")
            else
                setup_status_label:set_text("Setup script not found at: " .. CONFIG.setup_script:sub(1, 50) .. "...")
            end
        end
    end

    setup_dialog:update()
end

-- ============================================================================
-- CONFIGURATION PERSISTENCE
-- ============================================================================

function load_config()
    local f = io.open(CONFIG.config_file, "r")
    if f then
        local content = f:read("*a")
        f:close()

        -- Simple JSON parsing for our config structure
        local port = content:match('"http_port"%s*:%s*(%d+)')
        local interval_mode = content:match('"interval_mode"%s*:%s*"([^"]+)"')
        local interval_sec = content:match('"interval_seconds"%s*:%s*(%d+)')
        local interval_pct = content:match('"interval_percentage"%s*:%s*([%d.]+)')
        local width = content:match('"thumbnail_width"%s*:%s*(%d+)')
        local height = content:match('"thumbnail_height"%s*:%s*(%d+)')
        local quality = content:match('"quality"%s*:%s*"([^"]+)"')
        local purge = content:match('"cache_purge_days"%s*:%s*(%d+)')
        local max_mb = content:match('"cache_max_mb"%s*:%s*(%d+)')

        if port then CONFIG.http_port = tonumber(port) end
        if interval_mode then CONFIG.interval_mode = interval_mode end
        if interval_sec then CONFIG.interval_seconds = tonumber(interval_sec) end
        if interval_pct then CONFIG.interval_percentage = tonumber(interval_pct) end
        if width then CONFIG.thumbnail_width = tonumber(width) end
        if height then CONFIG.thumbnail_height = tonumber(height) end
        if quality then CONFIG.quality = quality end
        if purge then CONFIG.cache_purge_days = tonumber(purge) end
        if max_mb then CONFIG.cache_max_mb = tonumber(max_mb) end

        vlc.msg.info("[TickPlayer] Configuration loaded from " .. CONFIG.config_file)
    else
        vlc.msg.info("[TickPlayer] No config file found, using defaults")
    end
end

function save_config()
    -- Ensure config directory exists
    local is_windows = package.config:sub(1,1) == '\\'
    local config_dir
    if is_windows then
        config_dir = CONFIG.config_file:match("(.*\\)")
    else
        config_dir = CONFIG.config_file:match("(.*/)")
    end
    if config_dir then
        create_directory(config_dir)
    end

    local f = io.open(CONFIG.config_file, "w")
    if f then
        local content = string.format([[{
    "http_port": %d,
    "interval_mode": "%s",
    "interval_seconds": %d,
    "interval_percentage": %.1f,
    "thumbnail_width": %d,
    "thumbnail_height": %d,
    "quality": "%s",
    "cache_purge_days": %d,
    "cache_max_mb": %d
}]], CONFIG.http_port,
            CONFIG.interval_mode,
            CONFIG.interval_seconds,
            CONFIG.interval_percentage,
            CONFIG.thumbnail_width,
            CONFIG.thumbnail_height,
            CONFIG.quality,
            CONFIG.cache_purge_days,
            CONFIG.cache_max_mb)

        f:write(content)
        f:close()
        vlc.msg.info("[TickPlayer] Configuration saved to " .. CONFIG.config_file)
    else
        vlc.msg.err("[TickPlayer] Failed to save configuration")
    end
end
