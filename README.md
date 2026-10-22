# TickPlayer

[![Build](https://github.com/Skora120/Vlc-TickPlayer/actions/workflows/build.yml/badge.svg)](https://github.com/Skora120/Vlc-TickPlayer/actions/workflows/build.yml)

**Seekbar thumbnail previews for VLC media player on Windows.** Hover over the
seek bar and see that moment of the video, like on YouTube.

![TickPlayer showing a thumbnail above VLC's seek bar](docs/screenshot.png)

- Live previews while you hover, in a normal window and in fullscreen
- On by default: starts with VLC, nothing to click
- Uses your VLC's own decoder, so anything VLC plays from disk can be
  previewed. No FFmpeg, no Python, nothing else to install
- Thumbnails are cached, so reopening a video is instant
- Works with multiple monitors and display scaling
- Small (about 60 KB), installs per user without admin rights, and makes no
  network connections

## Requirements

- Windows 10 or 11
- VLC 3.0.x, 64-bit or 32-bit, with the standard interface (not a skin)
- Video files on your computer or a network share (not streams or discs)

## Install

1. Download `TickPlayer-<version>.zip` from the
   [Releases](https://github.com/Skora120/Vlc-TickPlayer/releases) page.
2. Extract the zip.
3. Close VLC and double-click **`install.cmd`**. It asks whether TickPlayer
   should start automatically with VLC; press **Y** (the default).
4. Start VLC, open a video and hover over the seek bar.

`install.cmd /auto` and `install.cmd /manual` skip the question.

### Installing by hand

1. Before extracting, right-click the zip, choose **Properties** and tick
   **Unblock**. Otherwise Windows may show a security warning when VLC starts
   the helper.
2. Copy the `lua` folder from the zip into `%APPDATA%\vlc\`, merging it with
   the `lua` folder that may already be there.
3. To start TickPlayer with VLC, open **Tools → Preferences**, choose
   **Show settings: All**, then:
   - **Interface → Main interfaces**: tick **Lua interpreter**;
   - **Interface → Main interfaces → Lua**: set **Lua interface** to
     `tickplayer`.

   Click **Save** and restart VLC. Skip this step if you prefer to turn it on
   from the View menu.

## Use

- With auto-start (the default), TickPlayer is on whenever VLC runs. The
  first time you hover over a new video you may see "Loading preview…" for a
  moment; thumbnails then appear as you move along the bar.
- **View → TickPlayer** controls it:
  - with auto-start on, it offers **Turn off until VLC restarts** and **Turn
    off and don't start with VLC**;
  - with auto-start off, it turns previews on (a check mark appears) and off.
    VLC does not remember this between sessions.
- To turn auto-start back on, run `install.cmd` again.

## Uninstall

Run `uninstall.cmd` from the zip. It turns auto-start off and removes
TickPlayer and its thumbnail cache. To uninstall by hand, undo the preference
changes above and delete these from `%APPDATA%\vlc\lua\`:
`extensions\tickplayer.lua`, `extensions\tickplayer\`, `intf\tickplayer.lua`
and `modules\tickplayer_core.lua`, plus the folder `%LOCALAPPDATA%\TickPlayer`.

## Troubleshooting

| Problem | What to do |
|---|---|
| TickPlayer is not in the View menu | Check that `tickplayer.lua` is directly in `%APPDATA%\vlc\lua\extensions\`, then restart VLC. |
| "TickPlayerHelper.exe was not found" or "not installed completely" | Run `install.cmd` from the extracted zip again. |
| No preview appears | Previews work for local files only, and not with VLC skins. Check the log at `%LOCALAPPDATA%\TickPlayer\helper.log`. |
| It doesn't start automatically | Run `install.cmd` again and press **Y**. VLC can run only one Lua interface, so auto-start can't be turned on if another one is set (the installer tells you), and it doesn't run when an app such as Syncplay starts VLC with its own. Use **View → TickPlayer** then. |
| A console window flashes when TickPlayer starts | VLC scripts can only start programs through the command prompt. It is harmless. |
| SmartScreen or antivirus warning | The helper is not code-signed. `install.cmd` removes the "downloaded from the internet" mark. You can also build it yourself (see below). |
| TickPlayer appears twice in the View menu | Another `tickplayer.lua` exists in VLC's program folder (`C:\Program Files\VideoLAN\VLC\lua\extensions`). Delete one of them. |

Found a bug? [Open an issue](https://github.com/Skora120/Vlc-TickPlayer/issues)
and attach `%LOCALAPPDATA%\TickPlayer\helper.log`.

## How it works

VLC's Lua scripts cannot see the mouse or draw over VLC's interface, so a
pure VLC extension cannot do this. TickPlayer has two parts:

1. **Lua scripts** that start the helper and write the URI of the playing
   media to a small session file (in `%APPDATA%\vlc\tickplayer`), updating it
   when the media changes:
   - `lua\intf\tickplayer.lua`, a VLC interface script that VLC runs at
     startup when auto-start is on;
   - `lua\extensions\tickplayer.lua`, the **View → TickPlayer** menu item;
   - `lua\modules\tickplayer_core.lua`, the code both share.

   VLC does not remember turned-on extensions, which is why auto-start uses
   an interface script. `install.cmd` turns it on by setting two VLC
   preferences (`extraintf` and `lua-intf`, the same ones as in the manual
   steps above) and keeps a backup of VLC's settings as
   `%APPDATA%\vlc\vlcrc.tickplayer-backup`.
2. **`TickPlayerHelper.exe`**, a small .NET Framework 4.8 program (.NET
   Framework 4.8 is part of Windows 10 and 11). It:
   - finds VLC's seek bar with Windows UI Automation. VLC's Qt interface
     exposes its sliders to accessibility tools, and the seek bar is the
     widest one;
   - converts the mouse position to a time with the same formula VLC uses
     for its own time tooltip;
   - decodes frames with a hidden libVLC player loaded from your VLC
     installation, seeking to exact times;
   - shows them in a borderless window that never takes focus or clicks.

   It exits when TickPlayer is turned off or VLC closes.

## Limitations

- **Windows only.** VLC on macOS uses a native interface instead of Qt, and
  Linux would need an AT-SPI version of the seek bar lookup. Contributions
  are welcome.
- **VLC 3.0.x.** VLC 4 has a new interface and has not been tested.
- The skins interface is not supported.
- Network streams, DVDs and other non-file media are not previewed.
- VLC runs only one Lua interface at a time, so auto-start can't be combined
  with another Lua interface script (VLC's web interface is separate and
  works alongside).

## Building from source

You need Windows and the [.NET SDK](https://dotnet.microsoft.com/download)
6 or newer (only for building).

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

This builds the 64-bit and 32-bit helpers and creates
`dist\TickPlayer-<version>.zip`.

To check thumbnail generation on its own:

```powershell
helper\bin\x64\Release\TickPlayerHelper.exe --test-thumbnails "C:\Program Files\VideoLAN\VLC" "file:///C:/Videos/movie.mkv" thumbtest
```

It saves 20 frames and the timings to `thumbtest\report.txt`.
`scripts\test-release.ps1 -Release dist\TickPlayer-<version>` runs the same
check against a built release.

### Continuous integration

Every push and pull request runs [`.github/workflows/build.yml`](.github/workflows/build.yml):

1. **build**: builds both helpers and the release zip.
2. **test**: on clean Windows machines with stock 64-bit and 32-bit VLC,
   `scripts\test-release.ps1 -Install` checks that libVLC produces
   thumbnails, that `install.cmd` installs and turns on auto-start, that a
   headless VLC starts the helper through the auto-start script, and that
   `uninstall.cmd` removes everything.
3. **release** (tags only): publishes a GitHub release with the zip, a
   `SHA256SUMS.txt` file and the version's notes from `CHANGELOG.md`.

### Releasing

1. Update the version in `helper/TickPlayerHelper.csproj` and
   `lua/extensions/tickplayer.lua` (the build fails if they differ).
2. In `CHANGELOG.md`, give the version a heading like `## 1.0.1 - 2026-11-02`
   and list the changes under it.
3. Commit, then tag and push:

   ```powershell
   git tag v1.0.1
   git push origin main v1.0.1
   ```

   The workflow tests the build and publishes the release. A tag with a
   suffix, such as `v1.1.0-beta.1`, becomes a pre-release.

### Layout

```
lua/extensions/tickplayer.lua     View > TickPlayer menu item
lua/intf/tickplayer.lua           auto-start interface script
lua/modules/tickplayer_core.lua   code shared by both
helper/                           TickPlayerHelper (C#, .NET Framework 4.8)
scripts/                          build, test, install, uninstall, auto-start settings
tests/sample.mp4                  60-second clip used by the tests
.github/                          CI workflow, Dependabot, issue template
```

The `lua` folder mirrors VLC's own, and the release zip has the same layout.

The first commit contains the original prototype: a Python overlay that
guessed the seek bar's position from screen pixels.

## License

[MIT](LICENSE)
