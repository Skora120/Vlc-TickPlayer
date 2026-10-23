"""
VLC HTTP API Client

Communicates with VLC's HTTP interface to get video information
such as current position, duration, and file path.
"""

import urllib.request
import urllib.parse
import urllib.error
import json
import base64
import logging
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VLCStatus:
    """Current VLC playback status"""
    state: str  # "playing", "paused", "stopped"
    position: float  # 0.0 to 1.0
    time: int  # Current time in seconds
    length: int  # Total duration in seconds
    volume: int  # Volume level (0-512, 256 = 100%)
    filename: str
    file_uri: str


class VLCHttpAPI:
    """Client for VLC's HTTP API"""

    def __init__(self, host: str = "localhost", port: int = 8080, password: str = ""):
        """
        Initialize VLC HTTP API client.

        Args:
            host: VLC HTTP interface host (usually localhost)
            port: VLC HTTP interface port
            password: HTTP interface password (set in VLC preferences)
        """
        self.host = host
        self.port = port
        self.password = password
        self.base_url = f"http://{host}:{port}"

        # Create auth header if password is set
        self.auth_header = None
        if password:
            credentials = f":{password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            self.auth_header = f"Basic {encoded}"

    def _make_request(self, endpoint: str, params: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Make HTTP request to VLC API.

        Args:
            endpoint: API endpoint (e.g., "/requests/status.json")
            params: Query parameters

        Returns:
            Response body as string, or None on error
        """
        url = f"{self.base_url}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        request = urllib.request.Request(url)
        if self.auth_header:
            request.add_header("Authorization", self.auth_header)

        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.read().decode("utf-8")
        except urllib.error.URLError as e:
            # Connection refused, timeout, etc.
            return None
        except Exception as e:
            return None

    def get_status(self) -> Optional[VLCStatus]:
        """
        Get current VLC playback status.

        Returns:
            VLCStatus object with current state, or None on error
        """
        response = self._make_request("/requests/status.json")
        if not response:
            logger.debug("No response from VLC status endpoint")
            return None

        try:
            data = json.loads(response)

            # Extract filename from information if available
            filename = ""
            file_uri = ""
            if "information" in data:
                info = data["information"]
                # VLC stores info in category.meta structure
                if "category" in info:
                    category = info["category"]
                    # Try meta first
                    if "meta" in category:
                        meta = category["meta"]
                        filename = meta.get("filename", "")
                        file_uri = meta.get("uri", "")
                    # Also check Stream 0 and other entries for URI
                    for key, value in category.items():
                        if isinstance(value, dict):
                            if "URI" in value:
                                file_uri = value["URI"]
                            if "uri" in value:
                                file_uri = value["uri"]
                            if "filename" in value:
                                filename = value["filename"]

            return VLCStatus(
                state=data.get("state", "stopped"),
                position=data.get("position", 0.0),
                time=data.get("time", 0),
                length=data.get("length", 0),
                volume=data.get("volume", 256),
                filename=filename,
                file_uri=file_uri
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.exception(f"Error parsing VLC status: {e}")
            return None

    def get_playlist(self) -> Optional[Dict[str, Any]]:
        """
        Get current playlist information.

        Returns:
            Playlist data as dictionary, or None on error
        """
        response = self._make_request("/requests/playlist.json")
        if not response:
            return None

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return None

    def get_current_file_uri(self) -> Optional[str]:
        """
        Get URI of the currently playing file.

        Returns:
            File URI (e.g., "file:///C:/Videos/movie.mp4"), or None
        """
        status = self.get_status()
        if status and status.file_uri:
            return status.file_uri

        # Fallback: try to get from playlist
        playlist = self.get_playlist()
        if playlist:
            # Navigate to find current item
            try:
                children = playlist.get("children", [])
                for category in children:
                    if category.get("name") == "Playlist":
                        items = category.get("children", [])
                        for item in items:
                            if item.get("current") == "current":
                                return item.get("uri")
            except (KeyError, TypeError):
                pass

        return None

    def seek(self, position: float) -> bool:
        """
        Seek to a position in the current video.

        Args:
            position: Position as fraction (0.0 to 1.0)

        Returns:
            True if seek was successful
        """
        # Convert to percentage
        percentage = int(position * 100)
        response = self._make_request("/requests/status.json", {"command": "seek", "val": f"{percentage}%"})
        return response is not None

    def seek_to_time(self, seconds: int) -> bool:
        """
        Seek to a specific time in seconds.

        Args:
            seconds: Target time in seconds

        Returns:
            True if seek was successful
        """
        response = self._make_request("/requests/status.json", {"command": "seek", "val": str(seconds)})
        return response is not None

    def is_available(self) -> bool:
        """
        Check if VLC HTTP API is available.

        Returns:
            True if API is responding
        """
        response = self._make_request("/requests/status.json")
        return response is not None

    def get_duration(self) -> int:
        """
        Get duration of current video in seconds.

        Returns:
            Duration in seconds, or 0 if not available
        """
        status = self.get_status()
        return status.length if status else 0

    def get_current_time(self) -> int:
        """
        Get current playback time in seconds.

        Returns:
            Current time in seconds, or 0 if not available
        """
        status = self.get_status()
        return status.time if status else 0

    def get_position(self) -> float:
        """
        Get current playback position as fraction.

        Returns:
            Position as float 0.0-1.0, or 0.0 if not available
        """
        status = self.get_status()
        return status.position if status else 0.0


def uri_to_path(uri: str) -> Optional[str]:
    """
    Convert a file:// URI to a local file path.

    Args:
        uri: File URI (e.g., "file:///C:/Videos/movie.mp4")

    Returns:
        Local file path, or None if not a file URI
    """
    if not uri or not uri.startswith("file://"):
        return None

    # Remove file:// prefix
    path = uri[7:]

    # On Windows, remove leading slash if followed by drive letter
    # file:///C:/path -> C:/path
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]

    # URL decode
    path = urllib.parse.unquote(path)

    # Convert forward slashes to backslashes on Windows
    import platform
    if platform.system() == "Windows":
        path = path.replace("/", "\\")

    return path


# Simple test
if __name__ == "__main__":
    print("Testing VLC HTTP API client...")

    api = VLCHttpAPI(port=8080, password="")

    if api.is_available():
        print("VLC HTTP API is available!")

        status = api.get_status()
        if status:
            print(f"State: {status.state}")
            print(f"Position: {status.position:.2%}")
            print(f"Time: {status.time}s / {status.length}s")
            print(f"File: {status.filename}")
            print(f"URI: {status.file_uri}")

            if status.file_uri:
                path = uri_to_path(status.file_uri)
                print(f"Local path: {path}")
    else:
        print("VLC HTTP API is not available.")
        print("Make sure VLC is running with HTTP interface enabled:")
        print("  Tools > Preferences > All > Interface > Main interfaces > Web")
