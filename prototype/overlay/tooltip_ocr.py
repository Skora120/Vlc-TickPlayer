"""
Tooltip OCR Module - Cross-Platform

Captures VLC's tooltip window and uses OCR to read the time displayed.
This provides bulletproof time detection regardless of VLC configuration.

Supports:
- Windows: Windows.Media.Ocr (native) or pytesseract
- Linux: pytesseract with X11 window capture
- macOS: Vision framework (native) or pytesseract
"""

import re
import logging
import platform
import asyncio
from typing import Optional, Tuple, Callable
from pathlib import Path
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# Import PIL - required for all platforms
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("PIL not available - OCR disabled")


# =============================================================================
# TIME PARSING (Common)
# =============================================================================

def parse_time_string(text: str) -> Optional[float]:
    """
    Parse a time string into seconds.

    Handles formats:
    - "1:23" (M:SS)
    - "12:34" (MM:SS)
    - "1:23:45" (H:MM:SS)
    - "01:23:45" (HH:MM:SS)

    Args:
        text: Text containing a time string

    Returns:
        Time in seconds, or None if no valid time found
    """
    if not text:
        return None

    # Clean up the text - remove non-digit/colon characters but keep structure
    text = text.strip()
    logger.debug(f"Parsing time from raw text: '{text}'")

    # First, try to extract just the digits and colons
    # This helps with OCR errors like "O" instead of "0"
    cleaned = text.replace('O', '0').replace('o', '0').replace('l', '1').replace('I', '1')

    # Pattern for time - try H:MM:SS first (greedy), then M:SS
    # Use flexible patterns that allow 1-2 digits for each component
    patterns = [
        # H:MM:SS or HH:MM:SS - most specific first
        (r'(\d{1,2})\s*[:\.]\s*(\d{1,2})\s*[:\.]\s*(\d{1,2})', 'H:M:S'),
        # M:SS or MM:SS
        (r'(\d{1,2})\s*[:\.]\s*(\d{1,2})', 'M:S'),
    ]

    for pattern, fmt in patterns:
        # Use findall to get ALL matches, then pick the longest/best one
        matches = re.findall(pattern, cleaned)
        if matches:
            # For H:M:S pattern, prefer matches where hours < 24, minutes < 60, seconds < 60
            best_match = None
            for groups in matches:
                if len(groups) == 3:
                    h, m, s = int(groups[0]), int(groups[1]), int(groups[2])
                    if h < 24 and m < 60 and s < 60:
                        best_match = groups
                        break
                elif len(groups) == 2:
                    m, s = int(groups[0]), int(groups[1])
                    if s < 60:  # Minutes can be > 60 for long videos
                        best_match = groups
                        break

            if best_match:
                if len(best_match) == 3:
                    hours = int(best_match[0])
                    minutes = int(best_match[1])
                    seconds = int(best_match[2])
                    result = hours * 3600 + minutes * 60 + seconds
                    logger.debug(f"Parsed H:M:S {best_match} -> {result}s")
                    return result
                elif len(best_match) == 2:
                    minutes = int(best_match[0])
                    seconds = int(best_match[1])
                    result = minutes * 60 + seconds
                    logger.debug(f"Parsed M:S {best_match} -> {result}s")
                    return result

    logger.debug(f"No time pattern matched in: '{text}'")
    return None


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class TooltipOCRBase(ABC):
    """Abstract base class for platform-specific tooltip OCR"""

    def __init__(self):
        self._last_ocr_time = 0
        self._last_result: Optional[float] = None
        self._ocr_interval = 0.05  # Minimum time between OCR attempts (50ms)
        self._cache_duration = 0.1  # Cache result for 100ms
        self._debug_save_images = False
        self._debug_dir = Path.home() / ".cache" / "tickplayer" / "debug"
        self._ocr_available = False
        self._capture_available = False

    def enable_debug(self, enabled: bool = True):
        """Enable saving debug images"""
        self._debug_save_images = enabled
        if enabled:
            self._debug_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def _init_ocr(self) -> bool:
        """Initialize OCR engine. Returns True if successful."""
        pass

    @abstractmethod
    def _find_tooltip_window(self, vlc_pid: Optional[int] = None) -> Optional[any]:
        """Find VLC's tooltip window. Returns window identifier or None."""
        pass

    @abstractmethod
    def _capture_tooltip(self, window_id: any) -> Optional[Image.Image]:
        """Capture tooltip window as PIL Image."""
        pass

    @abstractmethod
    def _ocr_image(self, image: Image.Image) -> Optional[str]:
        """Perform OCR on image. Returns text or None."""
        pass

    def is_available(self) -> bool:
        """Check if OCR is available"""
        return self._ocr_available and self._capture_available

    def get_tooltip_time(self, vlc_pid: Optional[int] = None) -> Optional[float]:
        """
        Get the time displayed in VLC's tooltip.

        Args:
            vlc_pid: VLC process ID

        Returns:
            Time in seconds, or None if tooltip not found/readable
        """
        import time
        current_time = time.time()

        # Rate limiting
        if current_time - self._last_ocr_time < self._ocr_interval:
            # Return cached result if still valid
            if current_time - self._last_ocr_time < self._cache_duration:
                return self._last_result
            return None

        self._last_ocr_time = current_time

        # Find tooltip window
        tooltip_window = self._find_tooltip_window(vlc_pid)
        if tooltip_window is None:
            self._last_result = None
            return None

        # Capture tooltip
        image = self._capture_tooltip(tooltip_window)
        if not image:
            logger.debug("Capture returned None")
            self._last_result = None
            return None

        logger.debug(f"Captured image: {image.size}, mode={image.mode}")

        # Debug: save captured image
        if self._debug_save_images:
            try:
                debug_path = self._debug_dir / f"tooltip_{int(current_time * 1000)}.png"
                image.save(debug_path)
            except:
                pass

        # Perform OCR
        text = self._ocr_image(image)

        if text:
            # Parse time from OCR result
            time_seconds = parse_time_string(text)
            self._last_result = time_seconds

            if time_seconds is not None:
                logger.debug(f"OCR result: '{text}' -> {time_seconds}s")

            return time_seconds

        self._last_result = None
        return None


# =============================================================================
# WINDOWS IMPLEMENTATION
# =============================================================================

class TooltipOCRWindows(TooltipOCRBase):
    """Windows implementation using Windows.Media.Ocr"""

    def __init__(self):
        super().__init__()
        self._win32gui = None
        self._win32ui = None
        self._win32con = None
        self._win32process = None
        self._ocr_engine = None
        self._use_pytesseract = False

        # Initialize
        self._init_capture()
        self._init_ocr()

    def _init_capture(self) -> bool:
        """Initialize Windows capture APIs"""
        try:
            import win32gui
            import win32ui
            import win32con
            import win32process
            self._win32gui = win32gui
            self._win32ui = win32ui
            self._win32con = win32con
            self._win32process = win32process
            self._capture_available = True
            return True
        except ImportError:
            logger.warning("pywin32 not available for window capture")
            self._capture_available = False
            return False

    def _init_ocr(self) -> bool:
        """Initialize Windows OCR engine"""
        # Try Windows native OCR first
        try:
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.globalization import Language

            # Try user profile languages
            self._ocr_engine = OcrEngine.try_create_from_user_profile_languages()

            if not self._ocr_engine:
                # Try English specifically
                try:
                    lang = Language("en-US")
                    self._ocr_engine = OcrEngine.try_create_from_language(lang)
                except:
                    pass

            if self._ocr_engine:
                self._ocr_available = True
                self._use_pytesseract = False
                logger.info("Windows OCR (WinRT) initialized")
                return True

        except ImportError:
            logger.debug("winrt not available, trying pytesseract")

        # Fallback to pytesseract
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            self._ocr_available = True
            self._use_pytesseract = True
            logger.info("Windows OCR (pytesseract) initialized")
            return True
        except:
            pass

        logger.warning("No OCR engine available on Windows")
        self._ocr_available = False
        return False

    def _find_tooltip_window(self, vlc_pid: Optional[int] = None) -> Optional[int]:
        """Find VLC's tooltip window on Windows"""
        if not self._capture_available:
            return None

        tooltip_hwnd = None
        candidates = []

        def enum_callback(hwnd, _):
            nonlocal tooltip_hwnd
            try:
                if not self._win32gui.IsWindowVisible(hwnd):
                    return True

                class_name = self._win32gui.GetClassName(hwnd)

                # VLC uses Qt tooltips - check various patterns
                is_tooltip = False
                if "Qt5QWindowToolTip" in class_name or "Qt6QWindowToolTip" in class_name:
                    is_tooltip = True
                elif "ToolTip" in class_name:
                    is_tooltip = True
                elif class_name.startswith("Qt") and "Tip" in class_name:
                    is_tooltip = True

                # Also check for small Qt windows that might be tooltips
                if class_name.startswith("Qt") and not is_tooltip:
                    rect = self._win32gui.GetWindowRect(hwnd)
                    w = rect[2] - rect[0]
                    h = rect[3] - rect[1]
                    # Tooltips are typically small (time display ~60x25 pixels)
                    if 30 < w < 150 and 15 < h < 50:
                        is_tooltip = True
                        candidates.append((hwnd, class_name, w, h))

                if is_tooltip:
                    # Verify it belongs to VLC if PID specified
                    if vlc_pid is not None:
                        _, window_pid = self._win32process.GetWindowThreadProcessId(hwnd)
                        if window_pid != vlc_pid:
                            return True

                    tooltip_hwnd = hwnd
                    return False  # Stop enumeration

            except:
                pass
            return True

        try:
            self._win32gui.EnumWindows(enum_callback, None)
        except:
            pass

        # Log candidates for debugging
        if candidates and not tooltip_hwnd:
            logger.debug(f"Tooltip candidates: {candidates}")

        return tooltip_hwnd

    def _capture_tooltip(self, hwnd: int) -> Optional[Image.Image]:
        """Capture tooltip window on Windows"""
        if not self._capture_available:
            return None

        try:
            # Get window dimensions
            left, top, right, bottom = self._win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top

            if width <= 0 or height <= 0:
                return None

            # Create device contexts
            hwnd_dc = self._win32gui.GetWindowDC(hwnd)
            mfc_dc = self._win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            # Create bitmap
            bitmap = self._win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            # Copy window content
            try:
                import ctypes
                ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
            except:
                save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), self._win32con.SRCCOPY)

            # Convert to PIL Image
            bmpinfo = bitmap.GetInfo()
            bmpstr = bitmap.GetBitmapBits(True)
            img = Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1
            )

            # Cleanup
            self._win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            self._win32gui.ReleaseDC(hwnd, hwnd_dc)

            return img

        except Exception as e:
            logger.debug(f"Failed to capture window: {e}")
            return None

    def _ocr_image(self, image: Image.Image) -> Optional[str]:
        """Perform OCR on Windows"""
        if not self._ocr_available:
            return None

        if self._use_pytesseract:
            return self._ocr_with_pytesseract(image)
        else:
            # Try WinRT first, fall back to pytesseract if available
            result = self._ocr_with_winrt(image)
            if result:
                return result

            # Try pytesseract as fallback
            try:
                import pytesseract
                logger.debug("WinRT OCR failed, trying pytesseract fallback")
                return self._ocr_with_pytesseract(image)
            except ImportError:
                pass

            return None

    def _ocr_with_winrt(self, image: Image.Image) -> Optional[str]:
        """OCR using Windows Runtime"""
        try:
            from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode

            orig_size = image.size
            logger.debug(f"OCR input size: {orig_size}")

            # Scale up significantly for better OCR - WinRT works better with larger images
            scale = 4
            new_size = (orig_size[0] * scale, orig_size[1] * scale)
            image = image.resize(new_size, Image.Resampling.BILINEAR)

            if image.mode != 'RGBA':
                image = image.convert('RGBA')

            width, height = image.size
            pixels = image.tobytes()

            # Convert RGBA to BGRA
            bgra_pixels = bytearray(len(pixels))
            for i in range(0, len(pixels), 4):
                bgra_pixels[i] = pixels[i + 2]      # B
                bgra_pixels[i + 1] = pixels[i + 1]  # G
                bgra_pixels[i + 2] = pixels[i]      # R
                bgra_pixels[i + 3] = pixels[i + 3]  # A

            # Create SoftwareBitmap
            bitmap = SoftwareBitmap(BitmapPixelFormat.BGRA8, width, height, BitmapAlphaMode.PREMULTIPLIED)
            bitmap.copy_from_buffer(bytes(bgra_pixels))

            # Perform OCR - use simple asyncio.run
            async def do_ocr():
                return await self._ocr_engine.recognize_async(bitmap)

            # Create new event loop for this call to avoid conflicts
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(do_ocr())
                loop.close()
            except Exception as e:
                logger.debug(f"Async OCR error: {e}")
                result = None

            if result:
                raw_text = result.text if result.text else ""
                logger.debug(f"OCR raw text: '{raw_text}' (len={len(raw_text)})")
                if raw_text.strip():
                    return raw_text.strip()
                else:
                    logger.debug("OCR returned empty text")
            else:
                logger.debug("OCR result object is None")

            return None

        except Exception as e:
            logger.debug(f"WinRT OCR failed: {e}")
            return None

    def _ocr_with_pytesseract(self, image: Image.Image) -> Optional[str]:
        """OCR using pytesseract"""
        try:
            import pytesseract
            gray = image.convert('L')
            text = pytesseract.image_to_string(
                gray,
                config='--psm 7 -c tessedit_char_whitelist=0123456789:'
            )
            return text.strip() if text else None
        except Exception as e:
            logger.debug(f"pytesseract OCR failed: {e}")
            return None


# =============================================================================
# LINUX IMPLEMENTATION
# =============================================================================

class TooltipOCRLinux(TooltipOCRBase):
    """Linux implementation using X11 and pytesseract"""

    def __init__(self):
        super().__init__()
        self._display = None
        self._root = None
        self._Xlib = None

        # Initialize
        self._init_capture()
        self._init_ocr()

    def _init_capture(self) -> bool:
        """Initialize X11 capture"""
        try:
            from Xlib import X, display, Xatom
            from Xlib.ext import composite
            self._display = display.Display()
            self._root = self._display.screen().root
            self._Xlib = {'X': X, 'Xatom': Xatom}
            self._capture_available = True
            logger.info("X11 capture initialized")
            return True
        except ImportError:
            logger.warning("python-xlib not available for window capture")
            self._capture_available = False
            return False
        except Exception as e:
            logger.warning(f"X11 initialization failed: {e}")
            self._capture_available = False
            return False

    def _init_ocr(self) -> bool:
        """Initialize OCR on Linux (pytesseract)"""
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            self._ocr_available = True
            logger.info("Linux OCR (pytesseract) initialized")
            return True
        except Exception as e:
            logger.warning(f"pytesseract not available: {e}")
            logger.warning("Install: sudo apt install tesseract-ocr && pip install pytesseract")
            self._ocr_available = False
            return False

    def _get_window_pid(self, window) -> Optional[int]:
        """Get PID of X11 window"""
        try:
            atom = self._display.intern_atom('_NET_WM_PID')
            pid_prop = window.get_full_property(atom, self._Xlib['Xatom'].CARDINAL)
            if pid_prop:
                return pid_prop.value[0]
        except:
            pass
        return None

    def _get_window_class(self, window) -> str:
        """Get window class name"""
        try:
            wm_class = window.get_wm_class()
            if wm_class:
                return wm_class[1] if len(wm_class) > 1 else wm_class[0]
        except:
            pass
        return ""

    def _get_window_name(self, window) -> str:
        """Get window name"""
        try:
            name = window.get_wm_name()
            return name if name else ""
        except:
            return ""

    def _find_tooltip_window(self, vlc_pid: Optional[int] = None) -> Optional[any]:
        """Find VLC's tooltip window on Linux"""
        if not self._capture_available:
            return None

        def search_windows(window):
            """Recursively search for tooltip window"""
            try:
                children = window.query_tree().children
            except:
                return None

            for child in children:
                try:
                    # Check window attributes
                    attrs = child.get_attributes()
                    if attrs.map_state != self._Xlib['X'].IsViewable:
                        continue

                    # Get window class and name
                    wm_class = self._get_window_class(child)
                    wm_name = self._get_window_name(child)

                    # VLC Qt tooltips - look for tooltip-like windows
                    is_tooltip = False
                    if 'tooltip' in wm_class.lower() or 'tooltip' in wm_name.lower():
                        is_tooltip = True
                    # Qt tooltips might have specific class patterns
                    if 'qtooltip' in wm_class.lower():
                        is_tooltip = True

                    if is_tooltip:
                        # Check PID if specified
                        if vlc_pid is not None:
                            window_pid = self._get_window_pid(child)
                            if window_pid != vlc_pid:
                                continue
                        return child

                    # Recurse into children
                    result = search_windows(child)
                    if result:
                        return result

                except:
                    continue

            return None

        return search_windows(self._root)

    def _capture_tooltip(self, window) -> Optional[Image.Image]:
        """Capture tooltip window on Linux using X11"""
        if not self._capture_available or not window:
            return None

        try:
            # Get window geometry
            geom = window.get_geometry()
            width = geom.width
            height = geom.height

            if width <= 0 or height <= 0:
                return None

            # Get the raw image data
            raw = window.get_image(0, 0, width, height, self._Xlib['X'].ZPixmap, 0xffffffff)

            # Convert to PIL Image
            # X11 typically uses BGRX format
            img = Image.frombytes('RGB', (width, height), raw.data, 'raw', 'BGRX')

            return img

        except Exception as e:
            logger.debug(f"X11 capture failed: {e}")

            # Fallback: try using ImageGrab (works on some Linux with proper setup)
            try:
                from PIL import ImageGrab

                # Get absolute position
                geom = window.get_geometry()
                coords = window.translate_coords(self._root, 0, 0)
                left = -coords.x
                top = -coords.y
                right = left + geom.width
                bottom = top + geom.height

                img = ImageGrab.grab(bbox=(left, top, right, bottom))
                return img
            except Exception as e2:
                logger.debug(f"ImageGrab fallback failed: {e2}")
                return None

    def _ocr_image(self, image: Image.Image) -> Optional[str]:
        """Perform OCR on Linux using pytesseract"""
        if not self._ocr_available:
            return None

        try:
            import pytesseract
            gray = image.convert('L')
            text = pytesseract.image_to_string(
                gray,
                config='--psm 7 -c tessedit_char_whitelist=0123456789:'
            )
            return text.strip() if text else None
        except Exception as e:
            logger.debug(f"pytesseract OCR failed: {e}")
            return None


# =============================================================================
# MACOS IMPLEMENTATION
# =============================================================================

class TooltipOCRMacOS(TooltipOCRBase):
    """macOS implementation using Quartz and Vision framework"""

    def __init__(self):
        super().__init__()
        self._cg = None  # CoreGraphics
        self._vision_available = False
        self._use_pytesseract = False

        # Initialize
        self._init_capture()
        self._init_ocr()

    def _init_capture(self) -> bool:
        """Initialize macOS capture using Quartz"""
        try:
            from Quartz import (
                CGWindowListCopyWindowInfo,
                CGWindowListCreateImage,
                CGRectNull,
                kCGWindowListOptionIncludingWindow,
                kCGWindowImageBoundsIgnoreFraming,
                kCGNullWindowID,
                kCGWindowListOptionOnScreenOnly
            )
            import Quartz

            self._cg = {
                'CGWindowListCopyWindowInfo': CGWindowListCopyWindowInfo,
                'CGWindowListCreateImage': CGWindowListCreateImage,
                'CGRectNull': CGRectNull,
                'kCGWindowListOptionIncludingWindow': kCGWindowListOptionIncludingWindow,
                'kCGWindowImageBoundsIgnoreFraming': kCGWindowImageBoundsIgnoreFraming,
                'kCGNullWindowID': kCGNullWindowID,
                'kCGWindowListOptionOnScreenOnly': kCGWindowListOptionOnScreenOnly,
                'Quartz': Quartz
            }
            self._capture_available = True
            logger.info("macOS Quartz capture initialized")
            return True
        except ImportError:
            logger.warning("pyobjc-framework-Quartz not available")
            self._capture_available = False
            return False

    def _init_ocr(self) -> bool:
        """Initialize OCR on macOS (Vision framework or pytesseract)"""
        # Try Vision framework first (native macOS)
        try:
            import Vision
            import Quartz
            self._vision_available = True
            self._ocr_available = True
            self._use_pytesseract = False
            logger.info("macOS OCR (Vision framework) initialized")
            return True
        except ImportError:
            logger.debug("Vision framework not available, trying pytesseract")

        # Fallback to pytesseract
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            self._ocr_available = True
            self._use_pytesseract = True
            logger.info("macOS OCR (pytesseract) initialized")
            return True
        except:
            pass

        logger.warning("No OCR engine available on macOS")
        logger.warning("Install: brew install tesseract && pip install pytesseract")
        self._ocr_available = False
        return False

    def _find_tooltip_window(self, vlc_pid: Optional[int] = None) -> Optional[int]:
        """Find VLC's tooltip window on macOS"""
        if not self._capture_available:
            return None

        try:
            window_list = self._cg['CGWindowListCopyWindowInfo'](
                self._cg['kCGWindowListOptionOnScreenOnly'],
                self._cg['kCGNullWindowID']
            )

            for window in window_list:
                owner_name = window.get('kCGWindowOwnerName', '')
                window_name = window.get('kCGWindowName', '')

                # Check if it's a VLC tooltip
                # Qt tooltips on macOS might have specific patterns
                is_vlc = 'VLC' in owner_name or 'vlc' in owner_name.lower()

                if not is_vlc:
                    continue

                # Check if it looks like a tooltip (small window, no title)
                bounds = window.get('kCGWindowBounds', {})
                width = bounds.get('Width', 0)
                height = bounds.get('Height', 0)

                # Tooltips are typically small
                if 20 < width < 200 and 10 < height < 50:
                    # Check PID if specified
                    if vlc_pid is not None:
                        window_pid = window.get('kCGWindowOwnerPID')
                        if window_pid != vlc_pid:
                            continue

                    return window.get('kCGWindowNumber')

        except Exception as e:
            logger.debug(f"Failed to find tooltip: {e}")

        return None

    def _capture_tooltip(self, window_id: int) -> Optional[Image.Image]:
        """Capture tooltip window on macOS"""
        if not self._capture_available or window_id is None:
            return None

        try:
            # Capture the specific window
            cg_image = self._cg['CGWindowListCreateImage'](
                self._cg['CGRectNull'],
                self._cg['kCGWindowListOptionIncludingWindow'],
                window_id,
                self._cg['kCGWindowImageBoundsIgnoreFraming']
            )

            if not cg_image:
                return None

            # Convert CGImage to PIL Image
            width = self._cg['Quartz'].CGImageGetWidth(cg_image)
            height = self._cg['Quartz'].CGImageGetHeight(cg_image)

            # Get pixel data
            data_provider = self._cg['Quartz'].CGImageGetDataProvider(cg_image)
            data = self._cg['Quartz'].CGDataProviderCopyData(data_provider)

            # Create PIL image (CGImage is typically BGRA)
            img = Image.frombytes('RGBA', (width, height), bytes(data), 'raw', 'BGRA')

            return img.convert('RGB')

        except Exception as e:
            logger.debug(f"macOS capture failed: {e}")
            return None

    def _ocr_image(self, image: Image.Image) -> Optional[str]:
        """Perform OCR on macOS"""
        if not self._ocr_available:
            return None

        if self._use_pytesseract:
            return self._ocr_with_pytesseract(image)
        else:
            return self._ocr_with_vision(image)

    def _ocr_with_vision(self, image: Image.Image) -> Optional[str]:
        """OCR using macOS Vision framework"""
        try:
            import Vision
            import Quartz
            from Foundation import NSData

            # Convert PIL image to CGImage
            # Save to bytes and load as CGImage
            import io
            buffer = io.BytesIO()
            image.save(buffer, format='PNG')
            data = buffer.getvalue()

            ns_data = NSData.dataWithBytes_length_(data, len(data))
            cg_source = Quartz.CGImageSourceCreateWithData(ns_data, None)
            cg_image = Quartz.CGImageSourceCreateImageAtIndex(cg_source, 0, None)

            if not cg_image:
                return None

            # Create Vision request
            request = Vision.VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)

            # Create handler and perform
            handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
            success = handler.performRequests_error_([request], None)

            if not success:
                return None

            # Get results
            results = request.results()
            if not results:
                return None

            # Combine all recognized text
            text_parts = []
            for observation in results:
                if observation.confidence() > 0.5:
                    text_parts.append(observation.topCandidates_(1)[0].string())

            return ' '.join(text_parts) if text_parts else None

        except Exception as e:
            logger.debug(f"Vision OCR failed: {e}")
            return None

    def _ocr_with_pytesseract(self, image: Image.Image) -> Optional[str]:
        """OCR using pytesseract"""
        try:
            import pytesseract
            gray = image.convert('L')
            text = pytesseract.image_to_string(
                gray,
                config='--psm 7 -c tessedit_char_whitelist=0123456789:'
            )
            return text.strip() if text else None
        except Exception as e:
            logger.debug(f"pytesseract OCR failed: {e}")
            return None


# =============================================================================
# FACTORY AND SINGLETON
# =============================================================================

def create_tooltip_ocr() -> TooltipOCRBase:
    """Create platform-specific TooltipOCR instance"""
    system = platform.system()

    if system == "Windows":
        return TooltipOCRWindows()
    elif system == "Linux":
        return TooltipOCRLinux()
    elif system == "Darwin":
        return TooltipOCRMacOS()
    else:
        logger.warning(f"Unsupported platform: {system}")
        # Return a dummy implementation that always returns None
        class TooltipOCRDummy(TooltipOCRBase):
            def _init_ocr(self): return False
            def _find_tooltip_window(self, vlc_pid): return None
            def _capture_tooltip(self, window_id): return None
            def _ocr_image(self, image): return None
        return TooltipOCRDummy()


# Singleton instance
_tooltip_ocr: Optional[TooltipOCRBase] = None

def get_tooltip_ocr() -> TooltipOCRBase:
    """Get the singleton TooltipOCR instance"""
    global _tooltip_ocr
    if _tooltip_ocr is None:
        _tooltip_ocr = create_tooltip_ocr()
    return _tooltip_ocr


def is_ocr_available() -> bool:
    """Check if OCR functionality is available"""
    return get_tooltip_ocr().is_available()


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    import time

    print("Tooltip OCR Test")
    print(f"Platform: {platform.system()}")
    print(f"OCR Available: {is_ocr_available()}")
    print()

    # Test time parsing
    test_cases = ['1:23', '12:34', '1:23:45', '01:02:03']
    print("Time parsing tests:")
    for test in test_cases:
        result = parse_time_string(test)
        print(f"  '{test}' -> {result}s")
    print()

    if not is_ocr_available():
        print("OCR not available.")
        if platform.system() == "Windows":
            print("Install: pip install winrt-runtime winrt-Windows.Media.Ocr winrt-Windows.Graphics.Imaging winrt-Windows.Globalization")
        elif platform.system() == "Linux":
            print("Install: sudo apt install tesseract-ocr && pip install pytesseract python-xlib")
        elif platform.system() == "Darwin":
            print("Install: pip install pyobjc-framework-Vision pyobjc-framework-Quartz")
            print("   or: brew install tesseract && pip install pytesseract")
        exit(1)

    ocr = get_tooltip_ocr()
    ocr.enable_debug(True)

    print("Monitoring for VLC tooltips... (hover over VLC seekbar)")
    print("Press Ctrl+C to stop")
    print()

    try:
        while True:
            tooltip_time = ocr.get_tooltip_time()
            if tooltip_time is not None:
                mins = int(tooltip_time // 60)
                secs = int(tooltip_time % 60)
                print(f"\rTooltip time: {mins:02d}:{secs:02d} ({tooltip_time}s)    ", end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nDone.")
