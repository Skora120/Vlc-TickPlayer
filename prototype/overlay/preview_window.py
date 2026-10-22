"""
Preview Window

Floating borderless window that displays thumbnail previews
above VLC's seekbar when hovering over the timeline.
"""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from pathlib import Path
from typing import Optional, Tuple
import platform


class PreviewWindow:
    """Floating preview window for thumbnail display"""

    def __init__(self, width: int = 240, height: int = 135):
        """
        Initialize preview window.

        Args:
            width: Thumbnail width
            height: Thumbnail height
        """
        self.thumb_width = width
        self.thumb_height = height
        self.padding = 8
        self.timestamp_height = 25

        # Calculate total window size
        self.window_width = width + (self.padding * 2)
        self.window_height = height + self.timestamp_height + (self.padding * 2)

        self.root: Optional[tk.Tk] = None
        self.canvas: Optional[tk.Canvas] = None
        self.image_id: Optional[int] = None
        self.text_id: Optional[int] = None
        self.current_image: Optional[ImageTk.PhotoImage] = None

        self._visible = False
        self._current_thumb_path: Optional[str] = None

    def create(self):
        """Create the preview window"""
        self.root = tk.Tk()
        self.root.title("TickPlayer Preview")

        # Make window borderless and always on top
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        # Set transparency (Windows and macOS)
        if platform.system() == "Windows":
            self.root.attributes("-transparentcolor", "#010101")
            bg_color = "#010101"
        elif platform.system() == "Darwin":
            self.root.attributes("-transparent", True)
            bg_color = "systemTransparent"
        else:
            bg_color = "#2b2b2b"

        # Configure window
        self.root.configure(bg=bg_color)
        self.root.geometry(f"{self.window_width}x{self.window_height}")

        # Create canvas for drawing
        self.canvas = tk.Canvas(
            self.root,
            width=self.window_width,
            height=self.window_height,
            bg="#2b2b2b",
            highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Draw rounded rectangle background
        self._draw_background()

        # Create placeholder for image
        self.image_id = self.canvas.create_image(
            self.window_width // 2,
            self.padding + self.thumb_height // 2,
            anchor=tk.CENTER
        )

        # Create timestamp text
        self.text_id = self.canvas.create_text(
            self.window_width // 2,
            self.padding + self.thumb_height + self.timestamp_height // 2 + 2,
            text="00:00:00",
            font=("Segoe UI", 11, "bold"),
            fill="#ffffff"
        )

        # Start hidden
        self.hide()

        # Disable window interactions
        self.root.bind("<Button-1>", lambda e: "break")
        self.root.bind("<Button-2>", lambda e: "break")
        self.root.bind("<Button-3>", lambda e: "break")

    def _draw_background(self):
        """Draw rounded rectangle background with shadow effect"""
        # Shadow (slightly offset darker rectangle)
        self._round_rectangle(
            self.canvas, 2, 2,
            self.window_width - 2, self.window_height - 2,
            radius=12, fill="#1a1a1a"
        )

        # Main background
        self._round_rectangle(
            self.canvas, 0, 0,
            self.window_width - 4, self.window_height - 4,
            radius=10, fill="#2b2b2b"
        )

        # Thumbnail area background (darker)
        self._round_rectangle(
            self.canvas,
            self.padding - 2, self.padding - 2,
            self.padding + self.thumb_width + 2,
            self.padding + self.thumb_height + 2,
            radius=6, fill="#1a1a1a"
        )

    def _round_rectangle(self, canvas, x1, y1, x2, y2, radius=10, **kwargs):
        """Draw a rounded rectangle on canvas"""
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    def update_thumbnail(self, thumb_path: str):
        """
        Update displayed thumbnail.

        Args:
            thumb_path: Path to thumbnail image file
        """
        if not self.root or not self.canvas:
            return

        if thumb_path == self._current_thumb_path:
            return  # No change needed

        try:
            # Load and resize image
            img = Image.open(thumb_path)
            img = img.resize((self.thumb_width, self.thumb_height), Image.Resampling.LANCZOS)

            # Convert to PhotoImage
            self.current_image = ImageTk.PhotoImage(img)

            # Update canvas
            self.canvas.itemconfig(self.image_id, image=self.current_image)
            self._current_thumb_path = thumb_path

        except Exception as e:
            pass  # Silently ignore errors

    def update_timestamp(self, seconds: float):
        """
        Update timestamp display.

        Args:
            seconds: Time in seconds
        """
        if not self.root or not self.canvas:
            return

        # Format time
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            time_str = f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            time_str = f"{minutes:02d}:{secs:02d}"

        self.canvas.itemconfig(self.text_id, text=time_str)

    def move_to(self, x: int, y: int):
        """
        Move window to position.

        Args:
            x: Screen X coordinate (center of window)
            y: Screen Y coordinate (bottom of window)
        """
        if not self.root:
            return

        # Calculate top-left position (centered on X, above Y)
        win_x = x - self.window_width // 2
        win_y = y - self.window_height - 10  # 10px gap above the seekbar

        # Get virtual screen bounds (spans ALL monitors)
        if platform.system() == "Windows":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = left, top of virtual screen
                # SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = width, height of virtual screen
                vscreen_left = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
                vscreen_top = user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
                vscreen_width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
                vscreen_height = user32.GetSystemMetrics(79) # SM_CYVIRTUALSCREEN

                # Clamp to virtual screen bounds (all monitors)
                win_x = max(vscreen_left, min(win_x, vscreen_left + vscreen_width - self.window_width))
                win_y = max(vscreen_top, min(win_y, vscreen_top + vscreen_height - self.window_height))
            except:
                pass  # Fall through without clamping if ctypes fails
        else:
            # For other platforms, use basic screen size (may not work perfectly on multi-monitor)
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            win_x = max(0, min(win_x, screen_width - self.window_width))
            win_y = max(0, min(win_y, screen_height - self.window_height))

        self.root.geometry(f"+{win_x}+{win_y}")

    def show(self):
        """Show the preview window"""
        if self.root and not self._visible:
            self.root.deiconify()
            self._visible = True

    def hide(self):
        """Hide the preview window"""
        if self.root:
            self.root.withdraw()
            self._visible = False
            self._current_thumb_path = None

    def is_visible(self) -> bool:
        """Check if window is visible"""
        return self._visible

    def update(self):
        """Process pending window events"""
        if self.root:
            self.root.update_idletasks()
            self.root.update()

    def destroy(self):
        """Destroy the preview window"""
        if self.root:
            self.root.destroy()
            self.root = None


class PreviewWindowManager:
    """
    Manages the preview window lifecycle and updates.
    Handles smooth movement and thumbnail transitions.
    """

    def __init__(self, thumb_width: int = 240, thumb_height: int = 135):
        """
        Initialize preview window manager.

        Args:
            thumb_width: Thumbnail width
            thumb_height: Thumbnail height
        """
        self.preview = PreviewWindow(thumb_width, thumb_height)
        self._last_x = 0
        self._last_y = 0
        self._smoothing = 0.5  # Position smoothing factor (higher = more responsive)

    def initialize(self):
        """Initialize the preview window"""
        self.preview.create()

    def show_preview(self, x: int, y: int, thumb_path: str, timestamp: float):
        """
        Show or update preview at position.

        Args:
            x: Screen X coordinate
            y: Screen Y coordinate (bottom of preview)
            thumb_path: Path to thumbnail
            timestamp: Time in seconds
        """
        # Smooth position
        if self.preview.is_visible():
            self._last_x = self._last_x + (x - self._last_x) * self._smoothing
            self._last_y = self._last_y + (y - self._last_y) * self._smoothing
        else:
            self._last_x = x
            self._last_y = y

        # Update preview
        self.preview.update_thumbnail(thumb_path)
        self.preview.update_timestamp(timestamp)
        self.preview.move_to(int(self._last_x), int(self._last_y))
        self.preview.show()

    def hide_preview(self):
        """Hide the preview"""
        self.preview.hide()

    def update(self):
        """Process window events"""
        self.preview.update()

    def is_visible(self) -> bool:
        """Check if preview is visible"""
        return self.preview.is_visible()

    def destroy(self):
        """Destroy the preview window"""
        self.preview.destroy()


if __name__ == "__main__":
    import time
    import sys

    print("Preview Window Test")
    print("Move your mouse around. Press Ctrl+C to exit.")
    print()

    # Create preview window
    manager = PreviewWindowManager()
    manager.initialize()

    # Use a test image if provided
    test_image = sys.argv[1] if len(sys.argv) > 1 else None

    if not test_image:
        # Create a simple test image
        from PIL import Image
        test_img = Image.new('RGB', (240, 135), color='#3498db')
        test_path = Path(__file__).parent / "test_thumb.jpg"
        test_img.save(test_path, quality=90)
        test_image = str(test_path)
        print(f"Created test image: {test_image}")

    try:
        timestamp = 0
        while True:
            # Get mouse position (platform-specific)
            if platform.system() == "Windows":
                import ctypes
                class POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
                pt = POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                x, y = pt.x, pt.y
            else:
                x, y = 500, 500  # Default for non-Windows

            # Show preview at mouse position
            manager.show_preview(x, y - 50, test_image, timestamp)
            timestamp += 1

            manager.update()
            time.sleep(0.016)  # ~60 FPS

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        manager.destroy()

        # Cleanup test image
        test_path = Path(__file__).parent / "test_thumb.jpg"
        if test_path.exists():
            test_path.unlink()
