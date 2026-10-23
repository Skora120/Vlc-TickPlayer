# Changelog

## 1.0.0 (unreleased)

First release.

- Thumbnail preview when hovering over VLC's seek bar, in windowed and
  fullscreen mode.
- Seek bar found with Windows UI Automation; mouse position mapped to time
  with VLC's own formula.
- Thumbnails decoded with the installed VLC's libVLC (no FFmpeg or Python),
  cached under `%LOCALAPPDATA%\TickPlayer`.
- Per-user install and uninstall scripts; 64-bit and 32-bit helpers.
