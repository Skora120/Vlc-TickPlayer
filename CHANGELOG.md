# Changelog

## 1.0.0 (unreleased)

First release.

- Thumbnail preview when hovering over VLC's seek bar, in windowed and
  fullscreen mode. The preview is the exact frame VLC jumps to when that
  spot is clicked. It appears once that frame is decoded (usually within
  0.3 s); a slower one is preceded by a dimmed nearby thumbnail.
- On by default: a Lua interface script starts TickPlayer with VLC. The
  installer enables it (with a backup of VLC's settings); View → TickPlayer
  can turn it off for the session or for good.
- Seek bar found with Windows UI Automation; mouse position mapped to a
  seek position with VLC's own formula.
- Thumbnails decoded with the installed VLC's libVLC (no FFmpeg or Python),
  cached under `%LOCALAPPDATA%\TickPlayer`.
- Per-user install and uninstall scripts; 64-bit and 32-bit helpers.
- Release zip mirrors VLC's `lua` folder.
