# TickPlayer - VLC Timeline Preview Extension

**True hover-over-timeline thumbnail previews for VLC Media Player**

TickPlayer shows a floating thumbnail preview when you hover over VLC's seekbar, just like YouTube, Netflix, and other modern video players.

![TickPlayer Demo](docs/demo.gif)

## Features

- **Hover Preview** - See a thumbnail preview as you move your mouse over the timeline
- **Automatic Thumbnails** - Thumbnails are generated automatically using FFmpeg
- **Smart Caching** - Thumbnails are cached for instant previews on repeated views
- **Configurable** - Adjust thumbnail size, quality, and generation interval
- **Multi-Instance** - Works with multiple VLC windows simultaneously
- **Cross-Platform** - Windows, Linux, and macOS support

## Requirements

- **VLC Media Player** 3.0 or later
- **Python** 3.8 or later
- **FFmpeg** (auto-downloaded on first run)

## Installation

### Step 1: Install Python Dependencies

Open a terminal/command prompt and run:

```bash
pip install Pillow pywin32  # Windows
pip install Pillow python-xlib  # Linux
pip install Pillow pyobjc-framework-Cocoa pyobjc-framework-Quartz  # macOS
```

Or install from requirements.txt:
```bash
cd "%APPDATA%\vlc\lua\extensions\TickPlayer\overlay"
pip install -r requirements.txt
```

### Step 2: Enable VLC's HTTP Interface

1. Open VLC
2. Go to **Tools** > **Preferences**
3. Click **"All"** at the bottom-left (Show settings: All)
4. Navigate to **Interface** > **Main interfaces**
5. Check **"Web"**
6. Navigate to **Interface** > **Main interfaces** > **Lua**
7. Set a **Lua HTTP password** (e.g., "vlc")
8. Click **Save**
9. **Restart VLC**

### Step 3: Verify Installation

1. Open VLC
2. Go to **View** menu
3. You should see **"TickPlayer"** submenu with:
   - Enable Preview
   - Settings...

## Usage

1. **Open a video** in VLC
2. Click **View** > **TickPlayer** > **Enable Preview**
3. **Hover over the timeline** (seekbar) to see thumbnail previews
4. Click anywhere on the timeline to seek to that position

### First Time Use

On first activation:
- FFmpeg will be downloaded automatically (~80MB)
- Thumbnails will be generated for your video
- Subsequent views of the same video will use cached thumbnails

## Configuration

Access settings via **View** > **TickPlayer** > **Settings...**

| Setting | Description | Default |
|---------|-------------|---------|
| Starting Port | HTTP API port for VLC communication | 8080 |
| Interval Mode | Generate thumbnails every X seconds or X% | Percentage |
| Interval Value | Thumbnail spacing | 2% or 10s |
| Thumbnail Size | Preview dimensions | 240x135 |
| Quality | JPEG compression | Medium |
| Auto-purge | Delete cached thumbnails after N days | 30 days |
| Max Cache Size | Maximum disk space for cache | 500 MB |

## File Locations

| Item | Windows | Linux | macOS |
|------|---------|-------|-------|
| Extension | `%APPDATA%\vlc\lua\extensions\TickPlayer\` | `~/.local/share/vlc/lua/extensions/TickPlayer/` | `~/Library/Application Support/org.videolan.vlc/lua/extensions/TickPlayer/` |
| Config | `%APPDATA%\vlc\tickplayer_config.json` | `~/.config/vlc/tickplayer_config.json` | Same as Extension |
| Cache | `%LOCALAPPDATA%\TickPlayer\` | `~/.cache/tickplayer/` | `~/Library/Caches/TickPlayer/` |
| FFmpeg | `Extension/ffmpeg/ffmpeg.exe` | `Extension/ffmpeg/ffmpeg` | Same as Extension |

## Troubleshooting

### Preview doesn't appear

1. **Check VLC HTTP interface** is enabled (see Installation Step 2)
2. **Check the port** - Default is 8080, make sure it's not blocked
3. **Check Python dependencies** - Run `pip install -r requirements.txt`
4. **Check VLC messages** - View > Messages (verbose: 2) for errors

### Thumbnails not generating

1. **Check FFmpeg** - Should auto-download on first run
2. **Check video file** - Only local files are supported, not streams
3. **Check disk space** - Cache needs space for thumbnails

### High CPU usage

- Thumbnail generation uses CPU temporarily
- Once cached, CPU usage is minimal
- Reduce thumbnail count by increasing interval percentage

### Multiple VLC windows

- Each VLC instance needs its own HTTP port
- Configure different ports in Settings for each instance

## Technical Details

### Architecture

```
┌─────────────────────┐     ┌─────────────────────────────┐
│  VLC Lua Extension  │────>│     Python Overlay App      │
│  (tickplayer.lua)   │     │  (tickplayer_overlay.exe)   │
├─────────────────────┤     ├─────────────────────────────┤
│ • Launches overlay  │     │ • Window tracking           │
│ • Settings dialog   │     │ • Mouse position detection  │
│ • Session management│     │ • Thumbnail generation      │
└─────────────────────┘     │ • Preview window display    │
                            └─────────────────────────────┘
```

### Why a separate app?

VLC's Lua API doesn't expose:
- Mouse position events
- Ability to create floating windows
- Direct seekbar interaction

The Python overlay app provides these capabilities while integrating seamlessly with VLC.

## Building from Source

### Create standalone executable (optional)

```bash
pip install pyinstaller
cd overlay
pyinstaller --onefile --noconsole --name tickplayer_overlay main.py
```

The executable will be in `dist/tickplayer_overlay.exe`

## License

MIT License - See [LICENSE](LICENSE)

FFmpeg is used under LGPL. See `ffmpeg/LICENSE.txt` for details.

## Contributing

Contributions welcome! Please open an issue or pull request.

## Credits

- [FFmpeg](https://ffmpeg.org/) - Video processing
- [VLC](https://www.videolan.org/) - Media player
- [Pillow](https://pillow.readthedocs.io/) - Image processing
