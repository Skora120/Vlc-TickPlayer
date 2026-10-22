"""
TickPlayer Overlay - Main Entry Point

Coordinates all overlay components:
- VLC window tracking
- Mouse position monitoring
- Thumbnail generation and display
- Preview window management
"""

import argparse
import json
import os
import sys
import time
import platform
import logging
from pathlib import Path
from typing import Optional

# Setup logging to file for debugging (since we run with pythonw)
def setup_logging():
    if platform.system() == "Windows":
        log_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "TickPlayer"
    else:
        log_dir = Path.home() / ".cache" / "tickplayer"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "overlay.log"

    logging.basicConfig(
        level=logging.DEBUG,  # Enable debug logging for troubleshooting
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='w', encoding='utf-8'),
        ]
    )

    # Suppress verbose logging from third-party libraries
    logging.getLogger('comtypes').setLevel(logging.WARNING)
    logging.getLogger('winrt').setLevel(logging.WARNING)

    return log_file

log_file = setup_logging()
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from vlc_api import VLCHttpAPI, uri_to_path
from window_tracker import create_window_tracker, SeekbarBounds
from thumbnail_manager import ThumbnailManager, ThumbnailConfig
from ffmpeg_downloader import ensure_ffmpeg
from preview_window import PreviewWindowManager
from tooltip_ocr import get_tooltip_ocr


class TickPlayerOverlay:
    """Main overlay application"""

    def __init__(self, vlc_pid: Optional[int] = None,
                 session_id: Optional[str] = None,
                 http_port: int = 8080):
        """
        Initialize TickPlayer overlay.

        Args:
            vlc_pid: VLC process ID to attach to
            session_id: Session ID from Lua extension
            http_port: VLC HTTP API port
        """
        self.vlc_pid = vlc_pid
        self.session_id = session_id
        self.http_port = http_port

        # Components
        self.vlc_api: Optional[VLCHttpAPI] = None
        self.window_tracker = None
        self.thumbnail_manager: Optional[ThumbnailManager] = None
        self.preview_manager: Optional[PreviewWindowManager] = None
        self.tooltip_ocr = None  # OCR for reading tooltip time

        # State
        self.vlc_hwnd: Optional[int] = None
        self.current_video_path: Optional[str] = None
        self.current_duration: float = 0
        self.thumbnails_ready = False
        self.running = False
        self.session_video_uri: Optional[str] = None  # Video URI from session file

        # Configuration
        self.config = ThumbnailConfig()
        self.session_dir = self._get_session_dir()

    def _get_session_dir(self) -> Path:
        """Get session directory path"""
        if platform.system() == "Windows":
            base = Path(os.environ.get("LOCALAPPDATA", ""))
        elif platform.system() == "Darwin":
            base = Path.home() / "Library" / "Caches"
        else:
            base = Path.home() / ".cache"
        return base / "TickPlayer" / "sessions"

    def _load_session_config(self) -> bool:
        """Load configuration from session file"""
        if not self.session_id:
            return False

        session_file = self.session_dir / f"{self.session_id}.json"
        if not session_file.exists():
            print(f"Session file not found: {session_file}")
            return False

        try:
            with open(session_file, 'r') as f:
                data = json.load(f)

            # Update configuration
            config_data = data.get("config", {})
            self.config.width = config_data.get("thumbnail_width", 240)
            self.config.height = config_data.get("thumbnail_height", 135)
            self.config.quality = config_data.get("quality", "medium")
            self.config.interval_mode = config_data.get("interval_mode", "percentage")
            self.config.interval_seconds = config_data.get("interval_seconds", 10)
            self.config.interval_percentage = config_data.get("interval_percentage", 2.0)

            # Get VLC PID and port from session
            self.vlc_pid = int(data.get("vlc_pid", 0)) or self.vlc_pid
            self.http_port = data.get("http_port", self.http_port)

            # Get video URI from session file (this is set by Lua extension)
            video_uri = data.get("video_uri", "")
            self.session_video_uri = video_uri if video_uri else None

            return True

        except Exception as e:
            logger.error(f"Error loading session config: {e}")
            return False

    def _check_stop_signal(self) -> bool:
        """Check if stop signal has been sent"""
        if not self.session_id:
            return False

        stop_file = self.session_dir / f"stop_{self.session_id}"
        if stop_file.exists():
            stop_file.unlink()
            return True

        # Also check if session file was removed
        session_file = self.session_dir / f"{self.session_id}.json"
        return not session_file.exists()

    def initialize(self) -> bool:
        """
        Initialize all components.

        Returns:
            True if initialization successful
        """
        print("Initializing TickPlayer Overlay...")

        # Load session configuration
        self._load_session_config()

        # Ensure FFmpeg is available
        ffmpeg_path = ensure_ffmpeg()
        if not ffmpeg_path:
            print("ERROR: FFmpeg not available")
            return False
        print(f"FFmpeg ready")

        # Initialize VLC API
        self.vlc_api = VLCHttpAPI(port=self.http_port, password="tickplayer")

        # Wait for VLC API to become available
        print(f"Connecting to VLC on port {self.http_port}...", end="", flush=True)
        for attempt in range(10):
            if self.vlc_api.is_available():
                print(" Connected!")
                break
            time.sleep(1)
        else:
            print(" Not available")
            print("Enable HTTP interface: Tools > Preferences > All > Interface > Main interfaces > Web")

        # Initialize window tracker
        self.window_tracker = create_window_tracker()

        # Find VLC window
        self.vlc_hwnd = self.window_tracker.find_vlc_window(self.vlc_pid)
        if self.vlc_hwnd:
            print(f"VLC window found")
        else:
            print("VLC window not found (will retry)")

        # Initialize thumbnail manager
        self.thumbnail_manager = ThumbnailManager(ffmpeg_path)

        # Initialize preview window
        self.preview_manager = PreviewWindowManager(
            thumb_width=self.config.width,
            thumb_height=self.config.height
        )
        self.preview_manager.initialize()

        # Initialize tooltip detector (for detecting when user hovers over seekbar)
        # We use tooltip visibility as a reliable indicator, with visual seekbar
        # detection for accurate position calculation (more reliable than OCR)
        try:
            self.tooltip_ocr = get_tooltip_ocr()
            print("Tooltip detection enabled")
            logger.info("Tooltip detector initialized")
        except Exception as e:
            logger.warning(f"Tooltip detector not available: {e}")
            self.tooltip_ocr = None

        print("Ready!")
        logger.info("Initialization complete")
        return True

    def _update_video_info(self):
        """Update current video information from VLC"""
        if not self.vlc_api or not self.vlc_api.is_available():
            return

        status = self.vlc_api.get_status()
        if not status:
            return

        # Get video URI - try multiple sources
        uri = status.file_uri
        if not uri:
            uri = self.vlc_api.get_current_file_uri()

        # Fallback to session file URI (set by Lua extension when video was opened)
        if not uri and self.session_video_uri:
            uri = self.session_video_uri

        if uri:
            video_path = uri_to_path(uri)
            duration = status.length

            # Check if video changed
            if video_path != self.current_video_path or duration != self.current_duration:
                self.current_video_path = video_path
                self.current_duration = duration
                self.thumbnails_ready = False

                if video_path and duration > 0:
                    logger.info(f"Video: {Path(video_path).name} ({duration}s)")
                    print(f"Video: {Path(video_path).name} ({duration}s)")
                    self._generate_thumbnails()

    def _generate_thumbnails(self):
        """Generate thumbnails for current video"""
        if not self.current_video_path or not self.thumbnail_manager:
            return

        if not os.path.exists(self.current_video_path):
            print(f"Video file not found: {self.current_video_path}")
            return

        # Check if already cached
        if self.thumbnail_manager.is_cached(
            self.current_video_path, self.current_duration, self.config
        ):
            print("Using cached thumbnails")
            self.thumbnails_ready = True
            return

        # Generate thumbnails
        print("Generating thumbnails...")

        def progress(current, total):
            print(f"\rGenerating thumbnails: {current}/{total}", end="")

        thumbnails = self.thumbnail_manager.generate_thumbnails(
            self.current_video_path,
            self.current_duration,
            self.config,
            progress_callback=progress
        )

        print()
        if thumbnails:
            print(f"Generated {len(thumbnails)} thumbnails")
            self.thumbnails_ready = True
        else:
            print("Failed to generate thumbnails")

    def run(self):
        """Main event loop"""
        self.running = True
        last_video_check = 0
        video_check_interval = 2.0  # Check for new video every 2 seconds

        logger.info("TickPlayer Overlay running")
        print("\nTickPlayer Overlay running. Press Ctrl+C to stop.")

        try:
            while self.running:
                # Check for stop signal
                if self._check_stop_signal():
                    logger.info("Stop signal received")
                    print("\nStop signal received")
                    break

                # Try to find VLC window if not found
                if not self.vlc_hwnd or not self.window_tracker.is_window_valid(self.vlc_hwnd):
                    self.vlc_hwnd = self.window_tracker.find_vlc_window(self.vlc_pid)
                    if not self.vlc_hwnd:
                        self.preview_manager.hide_preview()
                        time.sleep(0.5)
                        continue

                # Periodically check for video changes
                current_time = time.time()
                if current_time - last_video_check > video_check_interval:
                    self._update_video_info()
                    last_video_check = current_time

                # Only show preview when VLC's tooltip is visible
                timestamp = None
                show_preview = False
                tooltip_found = False

                if self.thumbnails_ready:
                    tooltip_window = None

                    # Check if VLC tooltip is visible (confirms user is hovering over seekbar)
                    if self.tooltip_ocr:
                        tooltip_window = self.tooltip_ocr._find_tooltip_window(self.vlc_pid)

                    if tooltip_window:
                        tooltip_found = True
                        logger.debug(f"Tooltip found: hwnd={tooltip_window}")

                        # Use position-based calculation with visually-detected seekbar bounds
                        # This is more reliable than OCR which has recognition issues
                        is_over, position = self.window_tracker.is_cursor_over_seekbar(self.vlc_hwnd)
                        if position is not None:
                            timestamp = position * self.current_duration
                            timestamp = max(0, min(timestamp, self.current_duration))
                            show_preview = True
                            logger.debug(f"Position time: {timestamp:.1f}s (pos={position:.3f})")

                if show_preview and timestamp is not None:
                    # Get thumbnail for this time
                    thumb_path = self.thumbnail_manager.get_thumbnail_for_time(
                        self.current_video_path,
                        self.current_duration,
                        timestamp
                    )

                    if thumb_path:
                        # Get FRESH cursor position for preview placement
                        cursor_x, cursor_y = self.window_tracker.get_cursor_position()

                        # Get FRESH seekbar bounds for Y position
                        seekbar = self.window_tracker.get_seekbar_bounds(self.vlc_hwnd)
                        if seekbar:
                            preview_y = seekbar.top
                        else:
                            preview_y = cursor_y

                        # Show preview at cursor X, seekbar Y
                        self.preview_manager.show_preview(
                            cursor_x, preview_y,
                            str(thumb_path), timestamp
                        )
                    else:
                        self.preview_manager.hide_preview()
                else:
                    # Hide preview when not over seekbar or no timestamp
                    self.preview_manager.hide_preview()

                # Update preview window
                self.preview_manager.update()

                # Small delay to prevent CPU overload
                time.sleep(0.016)  # ~60 FPS

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            print("\nInterrupted by user")
        except Exception as e:
            logger.exception(f"Error in main loop: {e}")
            raise
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources"""
        print("Cleaning up...")

        if self.preview_manager:
            self.preview_manager.destroy()

        # Remove session file
        if self.session_id:
            session_file = self.session_dir / f"{self.session_id}.json"
            if session_file.exists():
                session_file.unlink()

        print("Cleanup complete")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="TickPlayer Overlay")
    parser.add_argument("--pid", type=int, help="VLC process ID")
    parser.add_argument("--session", type=str, help="Session ID")
    parser.add_argument("--port", type=int, default=8080, help="VLC HTTP API port")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")

    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("TickPlayer Overlay Starting")
    logger.info("=" * 50)
    logger.info(f"Log file: {log_file}")
    logger.info(f"Platform: {platform.system()}")
    logger.info(f"PID: {args.pid}")
    logger.info(f"Session: {args.session}")
    logger.info(f"Port: {args.port}")

    print("=" * 50)
    print("TickPlayer Overlay")
    print("=" * 50)
    print(f"Log file: {log_file}")
    print(f"Platform: {platform.system()}")
    print(f"PID: {args.pid}")
    print(f"Session: {args.session}")
    print(f"Port: {args.port}")
    print()

    try:
        overlay = TickPlayerOverlay(
            vlc_pid=args.pid,
            session_id=args.session,
            http_port=args.port
        )

        if overlay.initialize():
            overlay.run()
        else:
            logger.error("Failed to initialize overlay")
            print("Failed to initialize overlay")
            sys.exit(1)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    main()
