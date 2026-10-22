"""
FFmpeg Auto-Downloader

Downloads FFmpeg automatically on first run if not already installed.
Uses LGPL builds for license compliance.
"""

import os
import sys
import platform
import urllib.request
import zipfile
import tarfile
import shutil
import hashlib
import json
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass


@dataclass
class DownloadProgress:
    """Download progress information"""
    downloaded: int
    total: int
    percentage: float
    speed_mbps: float


# FFmpeg download URLs for different platforms
FFMPEG_URLS = {
    "Windows": {
        "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip",
        "archive_type": "zip",
        "binary_path": "ffmpeg-master-latest-win64-lgpl/bin/ffmpeg.exe"
    },
    "Linux": {
        "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-lgpl.tar.xz",
        "archive_type": "tar.xz",
        "binary_path": "ffmpeg-master-latest-linux64-lgpl/bin/ffmpeg"
    },
    "Darwin": {  # macOS
        "url": "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
        "archive_type": "zip",
        "binary_path": "ffmpeg"
    }
}

# Fallback URLs in case primary fails
FFMPEG_FALLBACK_URLS = {
    "Windows": [
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    ],
    "Linux": [],
    "Darwin": []
}


class FFmpegDownloader:
    """Handles FFmpeg download and installation"""

    def __init__(self, install_dir: Optional[str] = None):
        """
        Initialize FFmpeg downloader.

        Args:
            install_dir: Directory to install FFmpeg to. Defaults to extension's ffmpeg folder.
        """
        if install_dir:
            self.install_dir = Path(install_dir)
        else:
            # Default to TickPlayer/ffmpeg directory
            self.install_dir = Path(__file__).parent.parent / "ffmpeg"

        self.system = platform.system()
        self.ffmpeg_path: Optional[Path] = None
        self._progress_callback: Optional[Callable[[DownloadProgress], None]] = None

    def set_progress_callback(self, callback: Callable[[DownloadProgress], None]):
        """Set callback function for download progress updates"""
        self._progress_callback = callback

    def get_ffmpeg_path(self) -> Optional[str]:
        """
        Get path to FFmpeg executable.

        Returns:
            Path to ffmpeg executable, or None if not found
        """
        # Check if already found
        if self.ffmpeg_path and self.ffmpeg_path.exists():
            return str(self.ffmpeg_path)

        # Check installed location
        if self.system == "Windows":
            installed_path = self.install_dir / "ffmpeg.exe"
        else:
            installed_path = self.install_dir / "ffmpeg"

        if installed_path.exists():
            self.ffmpeg_path = installed_path
            return str(self.ffmpeg_path)

        # Check system PATH
        system_path = shutil.which("ffmpeg")
        if system_path:
            self.ffmpeg_path = Path(system_path)
            return str(self.ffmpeg_path)

        # Check common installation locations
        common_paths = self._get_common_paths()
        for path in common_paths:
            if path.exists():
                self.ffmpeg_path = path
                return str(self.ffmpeg_path)

        return None

    def _get_common_paths(self) -> list:
        """Get common FFmpeg installation paths for current platform"""
        paths = []

        if self.system == "Windows":
            paths = [
                Path("C:/ffmpeg/bin/ffmpeg.exe"),
                Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
                Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg/bin/ffmpeg.exe",
            ]
        elif self.system == "Linux":
            paths = [
                Path("/usr/bin/ffmpeg"),
                Path("/usr/local/bin/ffmpeg"),
                Path.home() / ".local/bin/ffmpeg",
            ]
        elif self.system == "Darwin":
            paths = [
                Path("/usr/local/bin/ffmpeg"),
                Path("/opt/homebrew/bin/ffmpeg"),
                Path.home() / "bin/ffmpeg",
            ]

        return paths

    def is_installed(self) -> bool:
        """Check if FFmpeg is available"""
        return self.get_ffmpeg_path() is not None

    def download_and_install(self) -> bool:
        """
        Download and install FFmpeg.

        Returns:
            True if successful, False otherwise
        """
        if self.system not in FFMPEG_URLS:
            print(f"Unsupported platform: {self.system}")
            return False

        config = FFMPEG_URLS[self.system]
        url = config["url"]
        archive_type = config["archive_type"]
        binary_path = config["binary_path"]

        # Create install directory
        self.install_dir.mkdir(parents=True, exist_ok=True)

        # Download archive
        archive_path = self.install_dir / f"ffmpeg_download.{archive_type.replace('.', '_')}"

        print(f"Downloading FFmpeg from {url}...")
        success = self._download_file(url, archive_path)

        if not success:
            # Try fallback URLs
            for fallback_url in FFMPEG_FALLBACK_URLS.get(self.system, []):
                print(f"Trying fallback URL: {fallback_url}")
                success = self._download_file(fallback_url, archive_path)
                if success:
                    break

        if not success:
            print("Failed to download FFmpeg")
            return False

        # Extract archive
        print("Extracting FFmpeg...")
        extract_dir = self.install_dir / "extract_temp"
        extract_dir.mkdir(exist_ok=True)

        try:
            if archive_type == "zip":
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    zf.extractall(extract_dir)
            elif archive_type in ("tar.xz", "tar.gz"):
                with tarfile.open(archive_path, 'r:*') as tf:
                    tf.extractall(extract_dir)

            # Find and move ffmpeg binary
            extracted_ffmpeg = extract_dir / binary_path
            if not extracted_ffmpeg.exists():
                # Search for ffmpeg in extracted files
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        if file in ("ffmpeg", "ffmpeg.exe"):
                            extracted_ffmpeg = Path(root) / file
                            break

            if not extracted_ffmpeg.exists():
                print("Could not find ffmpeg binary in archive")
                return False

            # Move to final location
            if self.system == "Windows":
                final_path = self.install_dir / "ffmpeg.exe"
            else:
                final_path = self.install_dir / "ffmpeg"

            shutil.move(str(extracted_ffmpeg), str(final_path))

            # Make executable on Unix
            if self.system != "Windows":
                os.chmod(final_path, 0o755)

            self.ffmpeg_path = final_path
            print(f"FFmpeg installed to {final_path}")

            # Create license file
            self._create_license_file()

            return True

        except Exception as e:
            print(f"Error extracting FFmpeg: {e}")
            return False

        finally:
            # Cleanup
            if archive_path.exists():
                archive_path.unlink()
            if extract_dir.exists():
                shutil.rmtree(extract_dir, ignore_errors=True)

    def _download_file(self, url: str, destination: Path) -> bool:
        """
        Download file with progress reporting.

        Args:
            url: URL to download from
            destination: Local path to save file

        Returns:
            True if successful
        """
        try:
            # Create request with user agent
            request = urllib.request.Request(
                url,
                headers={'User-Agent': 'TickPlayer/1.0'}
            )

            with urllib.request.urlopen(request, timeout=60) as response:
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                block_size = 8192
                start_time = __import__('time').time()

                with open(destination, 'wb') as f:
                    while True:
                        block = response.read(block_size)
                        if not block:
                            break

                        f.write(block)
                        downloaded += len(block)

                        # Report progress
                        if self._progress_callback and total_size > 0:
                            elapsed = __import__('time').time() - start_time
                            speed = (downloaded / elapsed / 1024 / 1024) if elapsed > 0 else 0
                            progress = DownloadProgress(
                                downloaded=downloaded,
                                total=total_size,
                                percentage=(downloaded / total_size) * 100,
                                speed_mbps=speed
                            )
                            self._progress_callback(progress)

            return True

        except Exception as e:
            print(f"Download error: {e}")
            if destination.exists():
                destination.unlink()
            return False

    def _create_license_file(self):
        """Create license attribution file"""
        license_path = self.install_dir / "LICENSE.txt"

        license_text = """FFmpeg LGPL Build
==================

This software uses libraries from the FFmpeg project under the LGPLv2.1.

FFmpeg is a trademark of Fabrice Bellard, originator of the FFmpeg project.

This is an unmodified LGPL build of FFmpeg.

Source code is available at:
- https://github.com/BtbN/FFmpeg-Builds (Windows/Linux)
- https://evermeet.cx/ffmpeg/ (macOS)

For the full LGPL license text, see:
https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
"""

        with open(license_path, 'w') as f:
            f.write(license_text)

    def verify_installation(self) -> bool:
        """
        Verify FFmpeg installation by running it.

        Returns:
            True if FFmpeg runs successfully
        """
        ffmpeg_path = self.get_ffmpeg_path()
        if not ffmpeg_path:
            return False

        try:
            import subprocess
            result = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False


def ensure_ffmpeg(install_dir: Optional[str] = None,
                  progress_callback: Optional[Callable[[DownloadProgress], None]] = None) -> Optional[str]:
    """
    Ensure FFmpeg is available, downloading if necessary.

    Args:
        install_dir: Directory to install FFmpeg to
        progress_callback: Optional callback for download progress

    Returns:
        Path to FFmpeg executable, or None if unavailable
    """
    downloader = FFmpegDownloader(install_dir)

    if progress_callback:
        downloader.set_progress_callback(progress_callback)

    # Check if already installed
    ffmpeg_path = downloader.get_ffmpeg_path()
    if ffmpeg_path:
        print(f"FFmpeg found at: {ffmpeg_path}")
        return ffmpeg_path

    # Download and install
    print("FFmpeg not found. Downloading...")
    if downloader.download_and_install():
        if downloader.verify_installation():
            return downloader.get_ffmpeg_path()

    return None


if __name__ == "__main__":
    def show_progress(progress: DownloadProgress):
        bar_width = 40
        filled = int(bar_width * progress.percentage / 100)
        bar = '=' * filled + '-' * (bar_width - filled)
        print(f"\r[{bar}] {progress.percentage:.1f}% ({progress.speed_mbps:.1f} MB/s)", end="")

    print("FFmpeg Downloader Test")
    print(f"Platform: {platform.system()}")
    print()

    ffmpeg_path = ensure_ffmpeg(progress_callback=show_progress)
    print()

    if ffmpeg_path:
        print(f"FFmpeg is available at: {ffmpeg_path}")
    else:
        print("Failed to get FFmpeg")
