"""
Window Tracker Module

Finds and tracks VLC window position, size, and provides methods
to detect the seekbar area. Cross-platform support for Windows, Linux, and macOS.
"""

import platform
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List, Callable
from abc import ABC, abstractmethod


@dataclass
class WindowRect:
    """Window rectangle coordinates"""
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_x(self) -> int:
        return (self.left + self.right) // 2

    @property
    def center_y(self) -> int:
        return (self.top + self.bottom) // 2


@dataclass
class SeekbarBounds:
    """Seekbar position and dimensions"""
    left: int
    top: int
    right: int
    bottom: int
    window_rect: WindowRect

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def contains_point(self, x: int, y: int) -> bool:
        """Check if a point is within the seekbar bounds"""
        return self.left <= x <= self.right and self.top <= y <= self.bottom

    def get_position_at_x(self, x: int) -> float:
        """
        Get the video position (0.0-1.0) for a given X coordinate.

        Args:
            x: X coordinate on screen

        Returns:
            Position as float 0.0-1.0, clamped to valid range
        """
        if self.width <= 0:
            return 0.0
        position = (x - self.left) / self.width
        return max(0.0, min(1.0, position))


class WindowTrackerBase(ABC):
    """Abstract base class for window tracking"""

    @abstractmethod
    def find_vlc_window(self, pid: Optional[int] = None) -> Optional[int]:
        """
        Find VLC window handle.

        Args:
            pid: Optional process ID to match specific VLC instance

        Returns:
            Window handle/ID, or None if not found
        """
        pass

    @abstractmethod
    def get_window_rect(self, hwnd: int) -> Optional[WindowRect]:
        """
        Get window rectangle.

        Args:
            hwnd: Window handle

        Returns:
            WindowRect with window bounds, or None
        """
        pass

    @abstractmethod
    def get_cursor_position(self) -> Tuple[int, int]:
        """
        Get current cursor/mouse position.

        Returns:
            Tuple of (x, y) screen coordinates
        """
        pass

    @abstractmethod
    def is_window_valid(self, hwnd: int) -> bool:
        """
        Check if window handle is still valid.

        Args:
            hwnd: Window handle

        Returns:
            True if window exists
        """
        pass

    def get_seekbar_bounds(self, hwnd: int) -> Optional[SeekbarBounds]:
        """
        Estimate seekbar bounds based on VLC's typical layout.

        The seekbar is usually at the bottom of the window, above the control buttons.
        This is an approximation that works for most VLC themes.

        Args:
            hwnd: Window handle

        Returns:
            SeekbarBounds object, or None if window not found
        """
        rect = self.get_window_rect(hwnd)
        if not rect:
            return None

        window_width = rect.width

        # VLC's seekbar layout varies based on configuration:
        # - Default: Time display on left (~80px), controls on right (~180px)
        # - Minimal: Time displays can be hidden, reducing margins
        # - Different skins may have different layouts
        #
        # Strategy: Use conservative margins to ensure we capture the full seekbar
        # The tooltip sync will provide exact time when available
        #
        # For bulletproof coverage, we use smaller margins and rely on tooltip
        # correction when user hovers at the edges

        # Base margins - conservative to catch seekbar even with modified UI
        # These are the minimum possible margins (seekbar can't extend past controls)
        LEFT_MARGIN_BASE = 60     # Minimum space for any left content
        RIGHT_MARGIN_BASE = 140   # Minimum space for volume/fullscreen controls

        # Scale margins slightly with window width for larger windows
        LEFT_MARGIN_SCALE = 0.02   # ~2% of width
        RIGHT_MARGIN_SCALE = 0.06  # ~6% of width

        # Calculate margins (base + scaled)
        left_margin = LEFT_MARGIN_BASE + int(window_width * LEFT_MARGIN_SCALE)
        right_margin = RIGHT_MARGIN_BASE + int(window_width * RIGHT_MARGIN_SCALE)

        # Cap margins to reasonable maximums
        left_margin = min(left_margin, 120)
        right_margin = min(right_margin, 250)

        # Vertical bounds - generous to catch hover in control area
        SEEKBAR_TOP_OFFSET = 100   # Distance from bottom - generous top
        SEEKBAR_BOTTOM_OFFSET = 0   # All the way to bottom edge

        seekbar_left = rect.left + left_margin
        seekbar_right = rect.right - right_margin
        seekbar_top = rect.bottom - SEEKBAR_TOP_OFFSET
        seekbar_bottom = rect.bottom - SEEKBAR_BOTTOM_OFFSET

        return SeekbarBounds(
            left=seekbar_left,
            top=seekbar_top,
            right=seekbar_right,
            bottom=seekbar_bottom,
            window_rect=rect
        )

    def is_cursor_over_seekbar(self, hwnd: int) -> Tuple[bool, Optional[float]]:
        """
        Check if cursor is over the seekbar and return position.

        Args:
            hwnd: Window handle

        Returns:
            Tuple of (is_over_seekbar, position_if_over)
            position is 0.0-1.0 representing position in video
        """
        bounds = self.get_seekbar_bounds(hwnd)
        if not bounds:
            return False, None

        x, y = self.get_cursor_position()

        if bounds.contains_point(x, y):
            position = bounds.get_position_at_x(x)
            return True, position

        return False, None


# ============================================================================
# WINDOWS IMPLEMENTATION
# ============================================================================

class WindowTrackerWindows(WindowTrackerBase):
    """Windows implementation using win32gui"""

    def __init__(self):
        try:
            import win32gui
            import win32process
            import win32api
            import win32con
            import ctypes
            self.win32gui = win32gui
            self.win32process = win32process
            self.win32api = win32api
            self.win32con = win32con
            self.ctypes = ctypes
            self._available = True
            self._last_tooltip_time = None  # Cache last valid tooltip time
            self._last_tooltip_check = 0
            self._last_tooltip_log = 0

            # Try to import UI Automation for seekbar detection
            self._uia_available = False
            self._uia = None
            self._cached_seekbar_bounds = None
            self._cached_seekbar_hwnd = None
            self._seekbar_cache_time = 0
            try:
                import comtypes.client
                self._uia = comtypes.client.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}")  # CUIAutomation
                self._uia_available = True
            except:
                pass  # UI Automation not available, will use fallback methods

            # Visual seekbar detection cache
            self._visual_seekbar_bounds = None  # (left, right) pixel positions
            self._visual_seekbar_hwnd = None    # Window handle for cached bounds
            self._visual_seekbar_width = None   # Window width when cached

        except ImportError:
            self._available = False
            print("Warning: pywin32 not installed. Run: pip install pywin32")

    def is_available(self) -> bool:
        return self._available

    def find_vlc_window(self, pid: Optional[int] = None) -> Optional[int]:
        if not self._available:
            return None

        vlc_windows = []
        # VLC uses Qt - support both Qt5 and Qt6 class names
        valid_classes = ["Qt5QWindowIcon", "Qt6QWindowIcon", "Qt5152QWindowIcon", "Qt651QWindowIcon"]

        def enum_callback(hwnd, _):
            if not self.win32gui.IsWindowVisible(hwnd):
                return True

            # Get window title
            title = self.win32gui.GetWindowText(hwnd)
            if "VLC" not in title:
                return True

            # Get window class - accept various Qt versions
            class_name = self.win32gui.GetClassName(hwnd)

            # Check if it's a Qt window (VLC uses Qt)
            is_vlc_window = False
            for valid_class in valid_classes:
                if valid_class in class_name or class_name.startswith("Qt"):
                    is_vlc_window = True
                    break

            if not is_vlc_window:
                return True

            # If PID specified, check it matches
            if pid is not None:
                _, window_pid = self.win32process.GetWindowThreadProcessId(hwnd)
                if window_pid != pid:
                    return True

            vlc_windows.append(hwnd)
            return True

        self.win32gui.EnumWindows(enum_callback, None)

        # Return first VLC window found
        return vlc_windows[0] if vlc_windows else None

    def find_all_vlc_windows(self) -> List[Tuple[int, int]]:
        """
        Find all VLC windows.

        Returns:
            List of (hwnd, pid) tuples
        """
        if not self._available:
            return []

        vlc_windows = []

        def enum_callback(hwnd, _):
            if not self.win32gui.IsWindowVisible(hwnd):
                return True

            title = self.win32gui.GetWindowText(hwnd)
            if "VLC" not in title:
                return True

            class_name = self.win32gui.GetClassName(hwnd)
            if class_name != "Qt5QWindowIcon":
                return True

            _, window_pid = self.win32process.GetWindowThreadProcessId(hwnd)
            vlc_windows.append((hwnd, window_pid))
            return True

        self.win32gui.EnumWindows(enum_callback, None)
        return vlc_windows

    def get_window_rect(self, hwnd: int) -> Optional[WindowRect]:
        if not self._available:
            return None

        try:
            left, top, right, bottom = self.win32gui.GetWindowRect(hwnd)
            return WindowRect(left=left, top=top, right=right, bottom=bottom)
        except Exception:
            return None

    def get_cursor_position(self) -> Tuple[int, int]:
        if not self._available:
            return (0, 0)

        try:
            return self.win32api.GetCursorPos()
        except Exception:
            return (0, 0)

    def is_window_valid(self, hwnd: int) -> bool:
        if not self._available:
            return False

        try:
            return self.win32gui.IsWindow(hwnd)
        except Exception:
            return False

    def get_seekbar_bounds(self, hwnd: int) -> Optional[SeekbarBounds]:
        """
        Get seekbar bounds using multiple strategies:
        1. Visual detection (most accurate - analyzes actual pixels)
        2. UI Automation (if available)
        3. Fixed estimation based on VLC's typical layout (fallback)
        """
        rect = self.get_window_rect(hwnd)
        if not rect:
            return None

        # Vertical bounds - generous to catch hover in control area
        SEEKBAR_TOP_OFFSET = 100
        SEEKBAR_BOTTOM_OFFSET = 0
        seekbar_top = rect.bottom - SEEKBAR_TOP_OFFSET
        seekbar_bottom = rect.bottom - SEEKBAR_BOTTOM_OFFSET

        # Strategy 1: Visual detection (most accurate)
        visual_bounds = self.detect_seekbar_bounds_visually(hwnd)
        if visual_bounds:
            seekbar_left, seekbar_right = visual_bounds
            return SeekbarBounds(
                left=seekbar_left,
                top=seekbar_top,
                right=seekbar_right,
                bottom=seekbar_bottom,
                window_rect=rect
            )

        # Strategy 2: Try UI Automation
        uia_bounds = self.get_seekbar_bounds_via_uia(hwnd)
        if uia_bounds:
            left, top, right, bottom = uia_bounds
            return SeekbarBounds(
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                window_rect=rect
            )

        # Strategy 3: Fall back to estimation (less accurate)
        # VLC layout: _00:32___[---seekbar---]___1:20:00_
        # The time labels on left (~60-80px) and right (~80-100px) plus padding
        # Use fixed pixel margins for the time displays, as they don't scale with window
        window_width = rect.width

        # Fixed margins for time labels (don't scale with window size)
        # Left: time display ~60px + padding ~20px = ~80px
        # Right: longer time ~80px + padding ~20px = ~100px
        LEFT_MARGIN = 85
        RIGHT_MARGIN = 105

        left_margin = LEFT_MARGIN
        right_margin = RIGHT_MARGIN

        seekbar_left = rect.left + left_margin
        seekbar_right = rect.right - right_margin

        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Using fallback seekbar bounds: margins {left_margin}px/{right_margin}px")

        return SeekbarBounds(
            left=seekbar_left,
            top=seekbar_top,
            right=seekbar_right,
            bottom=seekbar_bottom,
            window_rect=rect
        )

    def get_foreground_window(self) -> Optional[int]:
        """Get the currently focused window handle"""
        if not self._available:
            return None

        try:
            return self.win32gui.GetForegroundWindow()
        except Exception:
            return None

    def observe_tooltip_position(self, vlc_pid: Optional[int] = None) -> bool:
        """
        Check if VLC's tooltip is visible and update observed seekbar bounds.
        VLC only shows the time tooltip when hovering over the ACTUAL seekbar.
        By tracking where we see tooltips, we can auto-calibrate the seekbar bounds.

        Returns:
            True if a tooltip was observed
        """
        if not self._available:
            return False

        try:
            cursor_x, cursor_y = self.win32api.GetCursorPos()
        except:
            return False

        tooltip_found = False

        def enum_callback(hwnd, _):
            nonlocal tooltip_found
            try:
                if not self.win32gui.IsWindowVisible(hwnd):
                    return True

                class_name = self.win32gui.GetClassName(hwnd)

                # VLC's tooltip class
                if "Qt5QWindowToolTip" in class_name or "Qt6QWindowToolTip" in class_name:
                    # Check if it belongs to VLC
                    if vlc_pid is not None:
                        _, window_pid = self.win32process.GetWindowThreadProcessId(hwnd)
                        if window_pid != vlc_pid:
                            return True

                    # Tooltip found! Use cursor X as seekbar position
                    tooltip_found = True

                    # Update observed bounds (silently)
                    if self._observed_seekbar_left is None or cursor_x < self._observed_seekbar_left:
                        self._observed_seekbar_left = cursor_x

                    if self._observed_seekbar_right is None or cursor_x > self._observed_seekbar_right:
                        self._observed_seekbar_right = cursor_x

                    self._tooltip_observations += 1
                    return False  # Stop enumeration

            except:
                pass
            return True

        try:
            self.win32gui.EnumWindows(enum_callback, None)
        except:
            pass

        return tooltip_found

    def get_observed_seekbar_bounds(self, hwnd: int) -> Optional[Tuple[int, int]]:
        """
        Get seekbar bounds from tooltip observations.
        Returns (left, right) if we have enough observations, None otherwise.
        """
        # Need at least a few observations to be reliable
        if self._tooltip_observations < 3:
            return None

        if self._observed_seekbar_left is None or self._observed_seekbar_right is None:
            return None

        # Ensure we have reasonable span (at least 100px)
        if self._observed_seekbar_right - self._observed_seekbar_left < 100:
            return None

        return (self._observed_seekbar_left, self._observed_seekbar_right)

    def detect_seekbar_bounds_visually(self, hwnd: int) -> Optional[Tuple[int, int]]:
        """
        Detect seekbar horizontal bounds by analyzing pixel colors.

        This method captures a strip at the seekbar's vertical position and
        finds where the seekbar track starts and ends by color transitions.

        Returns:
            Tuple of (left_x, right_x) in screen coordinates, or None if detection fails
        """
        import win32ui
        from PIL import Image
        import logging
        logger = logging.getLogger(__name__)

        rect = self.get_window_rect(hwnd)
        if not rect:
            return None

        width = rect.width
        height = rect.height

        # Check if we have valid cached bounds for this window size
        if (self._visual_seekbar_bounds and
            self._visual_seekbar_hwnd == hwnd and
            self._visual_seekbar_width == width):
            return self._visual_seekbar_bounds

        logger.debug(f"Detecting seekbar bounds visually for window {width}x{height}")

        try:
            # VLC's control bar can be at different positions depending on:
            # - Whether controls are visible (they hide when not interacting)
            # - Window mode (normal vs minimal vs embedded)
            # - Whether status bar is shown
            #
            # Capture a larger area from the bottom and search for the seekbar
            capture_y = height - 120  # Start higher to catch various layouts
            strip_height = 100  # Capture 100 pixels to find the seekbar

            hwnd_dc = self.win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, strip_height)
            save_dc.SelectObject(bitmap)
            save_dc.BitBlt((0, 0), (width, strip_height), mfc_dc, (0, capture_y), self.win32con.SRCCOPY)

            bmpinfo = bitmap.GetInfo()
            bmpstr = bitmap.GetBitmapBits(True)
            img = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRX', 0, 1)

            self.win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            self.win32gui.ReleaseDC(hwnd, hwnd_dc)

            # Analyze rows to find the actual seekbar track
            # The track is a continuous colored band with VLC's orange progress color
            # We look for the row with the most orange pixels (played portion)

            best_row = None
            best_orange_count = 0
            best_left = None
            best_right = None

            for row in range(strip_height):
                row_left = None
                row_right = None
                orange_count = 0

                for x in range(width):
                    r, g, b = img.getpixel((x, row))

                    # VLC's orange progress color - this is the key identifier
                    # The orange is typically RGB(255, 128, 0) or similar
                    is_orange = r > 200 and 80 < g < 200 and b < 100

                    if is_orange:
                        if row_left is None:
                            row_left = x
                        row_right = x
                        orange_count += 1

                # Track the row with the most orange (this is the seekbar)
                if orange_count > best_orange_count and orange_count > 20:
                    best_orange_count = orange_count
                    best_row = row
                    best_left = row_left
                    best_right = row_right

            # If we found orange, extend bounds to find the full track (including gray unplayed portion)
            if best_row is not None and best_left is not None:
                seekbar_left = best_left
                seekbar_right = best_right

                # Look for gray track extending beyond the orange
                # Check pixels to the left of orange
                for x in range(best_left - 1, -1, -1):
                    r, g, b = img.getpixel((x, best_row))
                    # Track gray or slightly different shade
                    is_track = 120 < r < 230 and 120 < g < 230 and 120 < b < 230 and abs(r - g) < 30
                    # Stop at bright background or dark border
                    is_background = (r > 235 and g > 235 and b > 235) or (r < 50 and g < 50 and b < 50)
                    if is_background:
                        break
                    if is_track:
                        seekbar_left = x

                # Check pixels to the right of orange
                for x in range(best_right + 1, width):
                    r, g, b = img.getpixel((x, best_row))
                    is_track = 120 < r < 230 and 120 < g < 230 and 120 < b < 230 and abs(r - g) < 30
                    is_background = (r > 235 and g > 235 and b > 235) or (r < 50 and g < 50 and b < 50)
                    if is_background:
                        break
                    if is_track:
                        seekbar_right = x

                logger.debug(f"Found seekbar at row {best_row}: orange={best_orange_count}, bounds={seekbar_left}-{seekbar_right}")
            else:
                seekbar_left = None
                seekbar_right = None
                logger.debug("No orange progress bar found")

            if seekbar_left is not None and seekbar_right is not None:
                # Validate: seekbar should be at least 50% of window width
                seekbar_width = seekbar_right - seekbar_left
                if seekbar_width > width * 0.5:
                    # Convert to screen coordinates
                    screen_left = rect.left + seekbar_left
                    screen_right = rect.left + seekbar_right

                    # Cache the result
                    self._visual_seekbar_bounds = (screen_left, screen_right)
                    self._visual_seekbar_hwnd = hwnd
                    self._visual_seekbar_width = width

                    left_pct = 100.0 * seekbar_left / width
                    right_pct = 100.0 * (width - seekbar_right) / width
                    logger.info(f"Visual seekbar detection: left={seekbar_left}px ({left_pct:.1f}%), right={seekbar_right}px ({right_pct:.1f}% margin)")

                    return (screen_left, screen_right)

            logger.debug("Visual seekbar detection failed - seekbar not found or too small")
            return None

        except Exception as e:
            logger.debug(f"Visual seekbar detection error: {e}")
            return None

    def get_seekbar_bounds_via_uia(self, hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        """
        Find VLC's seekbar slider using UI Automation.
        Returns (left, top, right, bottom) of the seekbar, or None if not found.
        """
        if not self._uia_available or not self._uia:
            return None

        import time as time_module

        # Use cached result if recent (seekbar position doesn't change often)
        current_time = time_module.time()
        if (self._cached_seekbar_bounds and
            self._cached_seekbar_hwnd == hwnd and
            current_time - self._seekbar_cache_time < 2.0):  # Cache for 2 seconds
            return self._cached_seekbar_bounds

        try:
            # Get the root element for the VLC window
            element = self._uia.ElementFromHandle(hwnd)
            if not element:
                return None

            # Define control types we're looking for
            # UIA_SliderControlTypeId = 50015
            # UIA_ProgressBarControlTypeId = 50014
            SLIDER_CONTROL_TYPE = 50015
            PROGRESSBAR_CONTROL_TYPE = 50014

            # Create condition to find slider controls
            # We need to use the IUIAutomation interface properly
            try:
                # Try to find slider elements
                condition = self._uia.CreatePropertyCondition(30003, SLIDER_CONTROL_TYPE)  # UIA_ControlTypePropertyId = 30003
                slider = element.FindFirst(4, condition)  # TreeScope_Descendants = 4

                if slider:
                    # Get bounding rectangle
                    rect = slider.CurrentBoundingRectangle
                    bounds = (rect.left, rect.top, rect.right, rect.bottom)
                    self._cached_seekbar_bounds = bounds
                    self._cached_seekbar_hwnd = hwnd
                    self._seekbar_cache_time = current_time
                    return bounds

                # Try progress bar as fallback
                condition = self._uia.CreatePropertyCondition(30003, PROGRESSBAR_CONTROL_TYPE)
                progress = element.FindFirst(4, condition)

                if progress:
                    rect = progress.CurrentBoundingRectangle
                    bounds = (rect.left, rect.top, rect.right, rect.bottom)
                    self._cached_seekbar_bounds = bounds
                    self._cached_seekbar_hwnd = hwnd
                    self._seekbar_cache_time = current_time
                    return bounds

            except Exception:
                pass  # UIA slider search failed

            # Alternative: search all descendants for something that looks like a seekbar
            try:
                # Find all elements and look for one that spans most of the window width
                # in the bottom area (where seekbar typically is)
                window_rect = self.get_window_rect(hwnd)
                if window_rect:
                    # Create a true condition to get all elements
                    true_condition = self._uia.CreateTrueCondition()
                    all_elements = element.FindAll(4, true_condition)  # TreeScope_Descendants

                    best_candidate = None
                    best_score = 0

                    for i in range(all_elements.Length):
                        try:
                            el = all_elements.GetElement(i)
                            rect = el.CurrentBoundingRectangle

                            # Check if element is in the bottom 150px of window
                            if rect.top < window_rect.bottom - 150:
                                continue

                            width = rect.right - rect.left
                            height = rect.bottom - rect.top

                            # Seekbar characteristics:
                            # - Wide (at least 60% of window width)
                            # - Thin (height < 50px)
                            # - Near bottom of window
                            if width > window_rect.width * 0.5 and 5 < height < 60:
                                score = width  # Prefer wider elements
                                if score > best_score:
                                    best_score = score
                                    best_candidate = (rect.left, rect.top, rect.right, rect.bottom)
                        except:
                            continue

                    if best_candidate:
                        self._cached_seekbar_bounds = best_candidate
                        self._cached_seekbar_hwnd = hwnd
                        self._seekbar_cache_time = current_time
                        return best_candidate

            except Exception:
                pass  # UIA element scan failed

        except Exception:
            pass  # UIA seekbar detection failed

        return None

    def get_vlc_tooltip_time(self, vlc_pid: Optional[int] = None) -> Optional[float]:
        """
        Read the time from VLC's tooltip when hovering over the seekbar.
        Uses multiple detection strategies for bulletproof tooltip reading.

        Returns:
            Time in seconds, or None if tooltip not found/readable
        """
        if not self._available:
            return None

        import time as time_module
        import re

        # Rate limit tooltip checks to avoid overhead
        current_time = time_module.time()
        if current_time - self._last_tooltip_check < 0.016:  # 16ms minimum between checks (~60fps)
            return self._last_tooltip_time
        self._last_tooltip_check = current_time

        # Get cursor position to find nearby tooltip windows
        try:
            cursor_x, cursor_y = self.win32api.GetCursorPos()
        except:
            cursor_x, cursor_y = 0, 0

        found_tooltips = []

        def enum_callback(hwnd, _):
            try:
                # Check if visible
                if not self.win32gui.IsWindowVisible(hwnd):
                    return True

                # Get class name
                class_name = self.win32gui.GetClassName(hwnd)

                # Check if it's likely a tooltip (multiple patterns for Qt/Windows)
                tooltip_patterns = [
                    "tooltip",
                    "Qt5QWindowToolTip",
                    "Qt6QWindowToolTip",
                    "QToolTip",
                    "Qt5QWindowOwnDC",  # Some Qt popups
                    "Qt6QWindowOwnDC",
                ]

                is_tooltip = any(p.lower() in class_name.lower() for p in tooltip_patterns)

                # Also check for small windows near cursor (tooltips are usually small)
                if not is_tooltip:
                    try:
                        rect = self.win32gui.GetWindowRect(hwnd)
                        width = rect[2] - rect[0]
                        height = rect[3] - rect[1]
                        # Tooltip-sized window (small, near cursor)
                        if 30 < width < 200 and 15 < height < 60:
                            # Check if near cursor (above cursor is typical for tooltips)
                            win_center_x = (rect[0] + rect[2]) // 2
                            win_center_y = (rect[1] + rect[3]) // 2
                            # Tooltip typically appears above and close to cursor
                            x_dist = abs(win_center_x - cursor_x)
                            y_dist = cursor_y - win_center_y  # Positive if tooltip is above
                            if x_dist < 150 and 0 < y_dist < 100:
                                is_tooltip = True
                    except:
                        pass

                if not is_tooltip:
                    return True

                # If VLC PID specified, check if window belongs to VLC
                if vlc_pid is not None:
                    _, window_pid = self.win32process.GetWindowThreadProcessId(hwnd)
                    if window_pid != vlc_pid:
                        return True

                # Try to get window text using multiple methods
                text = None

                # Method 1: GetWindowText
                try:
                    text = self.win32gui.GetWindowText(hwnd)
                except:
                    pass

                # Method 2: WM_GETTEXT
                if not text:
                    try:
                        length = self.ctypes.windll.user32.SendMessageW(hwnd, 0x000E, 0, 0)  # WM_GETTEXTLENGTH
                        if length > 0:
                            buffer = self.ctypes.create_unicode_buffer(length + 1)
                            self.ctypes.windll.user32.SendMessageW(hwnd, 0x000D, length + 1, buffer)
                            text = buffer.value
                    except:
                        pass

                # Method 3: Try getting text from child windows
                if not text:
                    try:
                        def child_callback(child_hwnd, texts):
                            try:
                                child_text = self.win32gui.GetWindowText(child_hwnd)
                                if child_text:
                                    texts.append(child_text)
                            except:
                                pass
                            return True
                        child_texts = []
                        self.win32gui.EnumChildWindows(hwnd, child_callback, child_texts)
                        if child_texts:
                            text = " ".join(child_texts)
                    except:
                        pass

                # Store info about found tooltip-like window
                rect = self.win32gui.GetWindowRect(hwnd)
                found_tooltips.append((hwnd, text or "", class_name, rect))

            except:
                pass
            return True

        try:
            self.win32gui.EnumWindows(enum_callback, None)
        except:
            pass

        # Parse time from any found tooltip text
        time_pattern = r'(\d{1,2}):(\d{2})(?::(\d{2}))?'

        for hwnd, tooltip_text, class_name, rect in found_tooltips:
            if tooltip_text:
                match = re.search(time_pattern, tooltip_text)
                if match:
                    hours_or_mins = int(match.group(1))
                    mins_or_secs = int(match.group(2))
                    secs = int(match.group(3)) if match.group(3) else None

                    if secs is not None:
                        # Format was H:MM:SS or HH:MM:SS
                        total_seconds = hours_or_mins * 3600 + mins_or_secs * 60 + secs
                    else:
                        # Format was M:SS or MM:SS
                        total_seconds = hours_or_mins * 60 + mins_or_secs

                    self._last_tooltip_time = total_seconds
                    return total_seconds

        # Try UI Automation if available and we found tooltip windows but couldn't read text
        if self._uia_available and found_tooltips:
            try:
                for hwnd, text, class_name, rect in found_tooltips:
                    if not text:  # No text from standard methods, try UIA
                        element = self._uia.ElementFromHandle(hwnd)
                        if element:
                            # Try to get Name property
                            name = element.CurrentName
                            if name:
                                match = re.search(time_pattern, name)
                                if match:
                                    hours_or_mins = int(match.group(1))
                                    mins_or_secs = int(match.group(2))
                                    secs = int(match.group(3)) if match.group(3) else None
                                    if secs is not None:
                                        total_seconds = hours_or_mins * 3600 + mins_or_secs * 60 + secs
                                    else:
                                        total_seconds = hours_or_mins * 60 + mins_or_secs
                                    self._last_tooltip_time = total_seconds
                                    return total_seconds
            except Exception:
                pass  # UIA tooltip read failed

        # No valid tooltip found
        self._last_tooltip_time = None
        return None


# ============================================================================
# LINUX IMPLEMENTATION
# ============================================================================

class WindowTrackerLinux(WindowTrackerBase):
    """Linux implementation using python-xlib"""

    def __init__(self):
        try:
            from Xlib import X, display
            from Xlib.ext import randr
            self.display = display.Display()
            self.root = self.display.screen().root
            self.X = X
            self._available = True
        except ImportError:
            self._available = False
            print("Warning: python-xlib not installed. Run: pip install python-xlib")
        except Exception as e:
            self._available = False
            print(f"Warning: Could not connect to X display: {e}")

    def is_available(self) -> bool:
        return self._available

    def _get_window_pid(self, window) -> Optional[int]:
        """Get PID of window from _NET_WM_PID property"""
        try:
            from Xlib import Xatom
            atom = self.display.intern_atom('_NET_WM_PID')
            pid_prop = window.get_full_property(atom, Xatom.CARDINAL)
            if pid_prop:
                return pid_prop.value[0]
        except Exception:
            pass
        return None

    def _get_window_name(self, window) -> str:
        """Get window name/title"""
        try:
            name = window.get_wm_name()
            if name:
                return name
        except Exception:
            pass
        return ""

    def find_vlc_window(self, pid: Optional[int] = None) -> Optional[int]:
        if not self._available:
            return None

        def search_children(window):
            try:
                children = window.query_tree().children
            except Exception:
                return None

            for child in children:
                name = self._get_window_name(child)
                if "VLC" in name:
                    if pid is not None:
                        window_pid = self._get_window_pid(child)
                        if window_pid != pid:
                            continue
                    return child.id

                # Recurse into children
                result = search_children(child)
                if result:
                    return result

            return None

        return search_children(self.root)

    def get_window_rect(self, hwnd: int) -> Optional[WindowRect]:
        if not self._available:
            return None

        try:
            window = self.display.create_resource_object('window', hwnd)
            geom = window.get_geometry()

            # Get absolute position
            coords = window.translate_coords(self.root, 0, 0)

            return WindowRect(
                left=-coords.x,
                top=-coords.y,
                right=-coords.x + geom.width,
                bottom=-coords.y + geom.height
            )
        except Exception:
            return None

    def get_cursor_position(self) -> Tuple[int, int]:
        if not self._available:
            return (0, 0)

        try:
            pointer = self.root.query_pointer()
            return (pointer.root_x, pointer.root_y)
        except Exception:
            return (0, 0)

    def is_window_valid(self, hwnd: int) -> bool:
        if not self._available:
            return False

        try:
            window = self.display.create_resource_object('window', hwnd)
            window.get_geometry()
            return True
        except Exception:
            return False


# ============================================================================
# MACOS IMPLEMENTATION
# ============================================================================

class WindowTrackerMacOS(WindowTrackerBase):
    """macOS implementation using AppKit/Quartz"""

    def __init__(self):
        try:
            from AppKit import NSWorkspace, NSScreen
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                CGEventGetLocation,
                CGEventCreate
            )
            self.NSWorkspace = NSWorkspace
            self.NSScreen = NSScreen
            self.CGWindowListCopyWindowInfo = CGWindowListCopyWindowInfo
            self.kCGWindowListOptionOnScreenOnly = kCGWindowListOptionOnScreenOnly
            self.kCGNullWindowID = kCGNullWindowID
            self.CGEventGetLocation = CGEventGetLocation
            self.CGEventCreate = CGEventCreate
            self._available = True
        except ImportError:
            self._available = False
            print("Warning: pyobjc not installed. Run: pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz")

    def is_available(self) -> bool:
        return self._available

    def find_vlc_window(self, pid: Optional[int] = None) -> Optional[int]:
        if not self._available:
            return None

        try:
            window_list = self.CGWindowListCopyWindowInfo(
                self.kCGWindowListOptionOnScreenOnly,
                self.kCGNullWindowID
            )

            for window in window_list:
                owner_name = window.get('kCGWindowOwnerName', '')
                if 'VLC' not in owner_name:
                    continue

                if pid is not None:
                    window_pid = window.get('kCGWindowOwnerPID')
                    if window_pid != pid:
                        continue

                return window.get('kCGWindowNumber')

        except Exception:
            pass

        return None

    def get_window_rect(self, hwnd: int) -> Optional[WindowRect]:
        if not self._available:
            return None

        try:
            window_list = self.CGWindowListCopyWindowInfo(
                self.kCGWindowListOptionOnScreenOnly,
                self.kCGNullWindowID
            )

            for window in window_list:
                if window.get('kCGWindowNumber') == hwnd:
                    bounds = window.get('kCGWindowBounds', {})
                    x = int(bounds.get('X', 0))
                    y = int(bounds.get('Y', 0))
                    width = int(bounds.get('Width', 0))
                    height = int(bounds.get('Height', 0))

                    return WindowRect(
                        left=x,
                        top=y,
                        right=x + width,
                        bottom=y + height
                    )

        except Exception:
            pass

        return None

    def get_cursor_position(self) -> Tuple[int, int]:
        if not self._available:
            return (0, 0)

        try:
            event = self.CGEventCreate(None)
            location = self.CGEventGetLocation(event)
            return (int(location.x), int(location.y))
        except Exception:
            return (0, 0)

    def is_window_valid(self, hwnd: int) -> bool:
        if not self._available:
            return False

        try:
            window_list = self.CGWindowListCopyWindowInfo(
                self.kCGWindowListOptionOnScreenOnly,
                self.kCGNullWindowID
            )

            for window in window_list:
                if window.get('kCGWindowNumber') == hwnd:
                    return True

        except Exception:
            pass

        return False


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_window_tracker() -> WindowTrackerBase:
    """
    Create appropriate window tracker for current platform.

    Returns:
        Platform-specific WindowTracker instance
    """
    system = platform.system()

    if system == "Windows":
        return WindowTrackerWindows()
    elif system == "Linux":
        return WindowTrackerLinux()
    elif system == "Darwin":
        return WindowTrackerMacOS()
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


# ============================================================================
# TEST
# ============================================================================

if __name__ == "__main__":
    print(f"Platform: {platform.system()}")
    print("Creating window tracker...")

    tracker = create_window_tracker()
    print(f"Tracker type: {type(tracker).__name__}")

    if hasattr(tracker, 'is_available') and not tracker.is_available():
        print("Tracker is not available (missing dependencies)")
    else:
        print("\nSearching for VLC window...")
        hwnd = tracker.find_vlc_window()

        if hwnd:
            print(f"Found VLC window: {hwnd}")

            rect = tracker.get_window_rect(hwnd)
            if rect:
                print(f"Window rect: {rect.left}, {rect.top}, {rect.right}, {rect.bottom}")
                print(f"Window size: {rect.width}x{rect.height}")

            seekbar = tracker.get_seekbar_bounds(hwnd)
            if seekbar:
                print(f"Seekbar bounds: {seekbar.left}, {seekbar.top}, {seekbar.right}, {seekbar.bottom}")

            print("\nMonitoring cursor position (Ctrl+C to stop)...")
            try:
                while True:
                    x, y = tracker.get_cursor_position()
                    is_over, position = tracker.is_cursor_over_seekbar(hwnd)

                    if is_over:
                        print(f"\rCursor: ({x}, {y}) - OVER SEEKBAR - Position: {position:.1%}  ", end="")
                    else:
                        print(f"\rCursor: ({x}, {y})                                          ", end="")

                    time.sleep(0.05)
            except KeyboardInterrupt:
                print("\nDone.")
        else:
            print("No VLC window found. Is VLC running?")
