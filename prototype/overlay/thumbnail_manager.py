"""
Thumbnail Manager

Generates and caches video thumbnails using FFmpeg.
Handles thumbnail generation, caching, and retrieval.
"""

import os
import subprocess
import hashlib
import json
import time
import platform
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
import threading


@dataclass
class ThumbnailConfig:
    """Thumbnail generation configuration"""
    width: int = 240
    height: int = 135
    quality: str = "medium"  # low, medium, high, best
    interval_mode: str = "percentage"  # seconds or percentage
    interval_seconds: int = 10
    interval_percentage: float = 2.0

    @property
    def ffmpeg_quality(self) -> int:
        """Convert quality setting to FFmpeg -q:v value"""
        quality_map = {"low": 8, "medium": 5, "high": 3, "best": 1}
        return quality_map.get(self.quality, 5)


@dataclass
class CacheMetadata:
    """Metadata for cached thumbnails"""
    video_path: str
    video_size: int
    video_duration: float
    thumbnail_count: int
    interval_seconds: float
    config: ThumbnailConfig
    created_at: float


class ThumbnailManager:
    """Manages thumbnail generation and caching"""

    def __init__(self, ffmpeg_path: str, cache_dir: Optional[str] = None):
        """
        Initialize thumbnail manager.

        Args:
            ffmpeg_path: Path to FFmpeg executable
            cache_dir: Directory for thumbnail cache
        """
        self.ffmpeg_path = ffmpeg_path

        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            # Default cache location
            if platform.system() == "Windows":
                base = Path(os.environ.get("LOCALAPPDATA", ""))
            elif platform.system() == "Darwin":
                base = Path.home() / "Library" / "Caches"
            else:
                base = Path.home() / ".cache"
            self.cache_dir = base / "TickPlayer" / "thumbnails"

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._thumbnail_cache: Dict[str, List[Path]] = {}
        self._generation_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=2)

    def get_cache_key(self, video_path: str, duration: float) -> str:
        """
        Generate unique cache key for a video.

        Args:
            video_path: Path to video file
            duration: Video duration in seconds

        Returns:
            Cache key string (hash)
        """
        try:
            file_size = os.path.getsize(video_path)
        except OSError:
            file_size = 0

        key_string = f"{video_path}|{file_size}|{duration}"
        return hashlib.sha256(key_string.encode()).hexdigest()[:16]

    def get_cache_path(self, cache_key: str) -> Path:
        """Get cache directory for a specific video"""
        return self.cache_dir / cache_key

    def is_cached(self, video_path: str, duration: float, config: ThumbnailConfig) -> bool:
        """
        Check if thumbnails are already cached for this video.

        Args:
            video_path: Path to video file
            duration: Video duration
            config: Thumbnail configuration

        Returns:
            True if valid cache exists
        """
        cache_key = self.get_cache_key(video_path, duration)
        cache_path = self.get_cache_path(cache_key)

        if not cache_path.exists():
            return False

        metadata_path = cache_path / "metadata.json"
        if not metadata_path.exists():
            return False

        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)

            # Check if config matches
            if metadata.get("config", {}).get("width") != config.width:
                return False
            if metadata.get("config", {}).get("height") != config.height:
                return False

            # Check if thumbnails exist
            thumbnail_count = metadata.get("thumbnail_count", 0)
            for i in range(thumbnail_count):
                thumb_path = cache_path / f"thumb_{i:04d}.jpg"
                if not thumb_path.exists():
                    return False

            return True

        except (json.JSONDecodeError, KeyError):
            return False

    def get_thumbnails(self, video_path: str, duration: float) -> Optional[List[Path]]:
        """
        Get list of thumbnail paths for a video.

        Args:
            video_path: Path to video file
            duration: Video duration

        Returns:
            List of thumbnail paths, or None if not cached
        """
        cache_key = self.get_cache_key(video_path, duration)
        cache_path = self.get_cache_path(cache_key)

        if not cache_path.exists():
            return None

        thumbnails = sorted(cache_path.glob("thumb_*.jpg"))
        return thumbnails if thumbnails else None

    def get_thumbnail_for_time(self, video_path: str, duration: float,
                                target_time: float) -> Optional[Path]:
        """
        Get thumbnail closest to a specific time.

        Args:
            video_path: Path to video file
            duration: Video duration
            target_time: Target time in seconds

        Returns:
            Path to closest thumbnail, or None
        """
        thumbnails = self.get_thumbnails(video_path, duration)
        if not thumbnails:
            return None

        cache_key = self.get_cache_key(video_path, duration)
        cache_path = self.get_cache_path(cache_key)
        metadata_path = cache_path / "metadata.json"

        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            interval = metadata.get("interval_seconds", 10)
        except:
            interval = duration / len(thumbnails) if thumbnails else 10

        # Find closest thumbnail index
        index = int(target_time / interval)
        index = max(0, min(index, len(thumbnails) - 1))

        return thumbnails[index]

    def generate_thumbnails(self, video_path: str, duration: float,
                           config: ThumbnailConfig,
                           progress_callback=None) -> Optional[List[Path]]:
        """
        Generate thumbnails for a video.

        Args:
            video_path: Path to video file
            duration: Video duration in seconds
            config: Thumbnail configuration
            progress_callback: Optional callback(current, total) for progress

        Returns:
            List of thumbnail paths, or None on error
        """
        with self._generation_lock:
            # Check cache first
            if self.is_cached(video_path, duration, config):
                return self.get_thumbnails(video_path, duration)

            cache_key = self.get_cache_key(video_path, duration)
            cache_path = self.get_cache_path(cache_key)

            # Create cache directory
            cache_path.mkdir(parents=True, exist_ok=True)

            # Calculate interval and thumbnail count
            MAX_THUMBNAILS = 500  # Increased cap

            if config.interval_mode == "percentage":
                interval = duration * (config.interval_percentage / 100)
            else:
                interval = config.interval_seconds

            interval = max(1, interval)  # Minimum 1 second
            thumbnail_count = int(duration / interval) + 1

            # If we'd exceed the cap, adjust the interval to cover the full video
            if thumbnail_count > MAX_THUMBNAILS:
                thumbnail_count = MAX_THUMBNAILS
                interval = duration / thumbnail_count  # Recalculate interval to cover full video

            thumbnails = []

            for i in range(thumbnail_count):
                timestamp = i * interval
                if timestamp >= duration:
                    break

                output_path = cache_path / f"thumb_{i:04d}.jpg"

                success = self._generate_single_thumbnail(
                    video_path, timestamp, output_path, config
                )

                if success:
                    thumbnails.append(output_path)

                if progress_callback:
                    progress_callback(i + 1, thumbnail_count)

            if not thumbnails:
                return None

            # Save metadata
            metadata = CacheMetadata(
                video_path=video_path,
                video_size=os.path.getsize(video_path) if os.path.exists(video_path) else 0,
                video_duration=duration,
                thumbnail_count=len(thumbnails),
                interval_seconds=interval,
                config=config,
                created_at=time.time()
            )

            metadata_path = cache_path / "metadata.json"
            with open(metadata_path, 'w') as f:
                json.dump(asdict(metadata), f, indent=2)

            return thumbnails

    def _generate_single_thumbnail(self, video_path: str, timestamp: float,
                                   output_path: Path, config: ThumbnailConfig) -> bool:
        """
        Generate a single thumbnail at a specific timestamp.

        Args:
            video_path: Path to video file
            timestamp: Timestamp in seconds
            output_path: Output file path
            config: Thumbnail configuration

        Returns:
            True if successful
        """
        # Build FFmpeg command
        # Using -ss before -i for fast seeking
        cmd = [
            self.ffmpeg_path,
            "-ss", str(timestamp),
            "-i", video_path,
            "-vframes", "1",
            "-vf", f"scale={config.width}:{config.height}:force_original_aspect_ratio=decrease,pad={config.width}:{config.height}:(ow-iw)/2:(oh-ih)/2",
            "-q:v", str(config.ffmpeg_quality),
            "-y",
            str(output_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            )
            return result.returncode == 0 and output_path.exists()
        except subprocess.TimeoutExpired:
            return False
        except Exception as e:
            return False

    def generate_thumbnails_async(self, video_path: str, duration: float,
                                  config: ThumbnailConfig,
                                  callback=None):
        """
        Generate thumbnails asynchronously.

        Args:
            video_path: Path to video file
            duration: Video duration
            config: Thumbnail configuration
            callback: Optional callback(thumbnails_or_none) when complete
        """
        def task():
            result = self.generate_thumbnails(video_path, duration, config)
            if callback:
                callback(result)

        self._executor.submit(task)

    def clear_cache(self, max_age_days: Optional[int] = None,
                   max_size_mb: Optional[int] = None):
        """
        Clear thumbnail cache.

        Args:
            max_age_days: Remove entries older than this many days
            max_size_mb: Remove oldest entries until cache is under this size
        """
        if not self.cache_dir.exists():
            return

        entries = []
        for entry in self.cache_dir.iterdir():
            if entry.is_dir():
                metadata_path = entry / "metadata.json"
                try:
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)
                    created_at = metadata.get("created_at", 0)
                except:
                    created_at = entry.stat().st_mtime

                size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                entries.append((entry, created_at, size))

        # Sort by creation time (oldest first)
        entries.sort(key=lambda x: x[1])

        now = time.time()

        # Remove by age
        if max_age_days is not None:
            max_age_seconds = max_age_days * 24 * 60 * 60
            for entry, created_at, size in entries:
                if now - created_at > max_age_seconds:
                    shutil.rmtree(entry, ignore_errors=True)

        # Remove by size
        if max_size_mb is not None:
            max_size_bytes = max_size_mb * 1024 * 1024
            total_size = sum(e[2] for e in entries)

            for entry, created_at, size in entries:
                if total_size <= max_size_bytes:
                    break
                if entry.exists():
                    shutil.rmtree(entry, ignore_errors=True)
                    total_size -= size

    def get_cache_size_mb(self) -> float:
        """Get total cache size in MB"""
        if not self.cache_dir.exists():
            return 0

        total = sum(f.stat().st_size for f in self.cache_dir.rglob("*") if f.is_file())
        return total / (1024 * 1024)


if __name__ == "__main__":
    from ffmpeg_downloader import ensure_ffmpeg

    print("Thumbnail Manager Test")
    print()

    # Ensure FFmpeg is available
    ffmpeg_path = ensure_ffmpeg()
    if not ffmpeg_path:
        print("FFmpeg not available")
        exit(1)

    print(f"Using FFmpeg: {ffmpeg_path}")

    # Create manager
    manager = ThumbnailManager(ffmpeg_path)
    print(f"Cache directory: {manager.cache_dir}")
    print(f"Cache size: {manager.get_cache_size_mb():.2f} MB")

    # Test with a video file (if provided as argument)
    import sys
    if len(sys.argv) > 1:
        video_path = sys.argv[1]
        duration = 60  # Assume 60 seconds for test

        config = ThumbnailConfig(
            width=240,
            height=135,
            quality="medium",
            interval_seconds=10
        )

        print(f"\nGenerating thumbnails for: {video_path}")

        def progress(current, total):
            print(f"\rProgress: {current}/{total}", end="")

        thumbnails = manager.generate_thumbnails(
            video_path, duration, config, progress_callback=progress
        )

        print()
        if thumbnails:
            print(f"Generated {len(thumbnails)} thumbnails")
            for thumb in thumbnails[:5]:
                print(f"  {thumb}")
            if len(thumbnails) > 5:
                print(f"  ... and {len(thumbnails) - 5} more")
        else:
            print("Failed to generate thumbnails")
    else:
        print("\nUsage: python thumbnail_manager.py <video_file>")
