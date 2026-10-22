"""
TickPlayer Auto-Setup Script

Handles automatic installation of dependencies and VLC configuration.
"""

import subprocess
import sys
import os
import platform
import re
from pathlib import Path


def get_vlc_config_path() -> Path:
    """Get path to VLC configuration file (vlcrc)"""
    system = platform.system()

    if system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "vlc" / "vlcrc"
    elif system == "Darwin":
        return Path.home() / "Library" / "Preferences" / "org.videolan.vlc" / "vlcrc"
    else:  # Linux
        return Path.home() / ".config" / "vlc" / "vlcrc"


def install_python_dependencies() -> tuple:
    """
    Install required Python packages.

    Returns:
        Tuple of (success: bool, message: str)
    """
    system = platform.system()

    # Determine packages based on platform
    packages = ["Pillow"]

    if system == "Windows":
        packages.append("pywin32")
    elif system == "Linux":
        packages.append("python-xlib")
    elif system == "Darwin":
        packages.extend(["pyobjc-framework-Cocoa", "pyobjc-framework-Quartz"])

    print(f"Installing packages: {', '.join(packages)}")

    try:
        # Use pip to install packages
        cmd = [sys.executable, "-m", "pip", "install", "--user"] + packages
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        if result.returncode == 0:
            return True, f"Successfully installed: {', '.join(packages)}"
        else:
            return False, f"pip error: {result.stderr}"

    except subprocess.TimeoutExpired:
        return False, "Installation timed out"
    except Exception as e:
        return False, f"Error: {str(e)}"


def check_dependencies() -> dict:
    """
    Check which dependencies are installed.

    Returns:
        Dict with package names and their status
    """
    status = {}

    # Check Pillow
    try:
        from PIL import Image
        status["Pillow"] = True
    except ImportError:
        status["Pillow"] = False

    # Check platform-specific packages
    system = platform.system()

    if system == "Windows":
        try:
            import win32gui
            status["pywin32"] = True
        except ImportError:
            status["pywin32"] = False
    elif system == "Linux":
        try:
            from Xlib import display
            status["python-xlib"] = True
        except ImportError:
            status["python-xlib"] = False
    elif system == "Darwin":
        try:
            from AppKit import NSWorkspace
            from Quartz import CGWindowListCopyWindowInfo
            status["pyobjc"] = True
        except ImportError:
            status["pyobjc"] = False

    return status


def enable_vlc_http_interface(port: int = 8080, password: str = "tickplayer") -> tuple:
    """
    Enable VLC's HTTP interface by modifying vlcrc.

    Args:
        port: HTTP port to use
        password: HTTP password

    Returns:
        Tuple of (success: bool, message: str, needs_restart: bool)
    """
    config_path = get_vlc_config_path()

    # Create config directory if needed
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing config or create empty
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        original_content = content
    else:
        content = ""
        original_content = ""

    changes_made = False

    # Settings to add/modify
    settings = {
        "extraintf": "http",
        "http-host": "localhost",
        "http-port": str(port),
        "http-password": password,
    }

    for key, value in settings.items():
        # Pattern to find existing setting (commented or not)
        pattern = rf'^#?{re.escape(key)}=.*$'
        replacement = f'{key}={value}'

        if re.search(pattern, content, re.MULTILINE):
            # Replace existing setting
            new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            if new_content != content:
                content = new_content
                changes_made = True
        else:
            # Add new setting
            content += f"\n{replacement}"
            changes_made = True

    if changes_made:
        # Backup original config
        if config_path.exists():
            backup_path = config_path.with_suffix('.vlcrc.backup')
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(original_content)

        # Write new config
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return True, f"VLC HTTP interface enabled on port {port}", True
    else:
        return True, "VLC HTTP interface already configured", False


def check_vlc_http_configured() -> tuple:
    """
    Check if VLC HTTP interface is configured.

    Returns:
        Tuple of (configured: bool, port: int or None, has_password: bool)
    """
    config_path = get_vlc_config_path()

    if not config_path.exists():
        return False, None, False

    with open(config_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # Check for http in extraintf
    extraintf_match = re.search(r'^extraintf=(.*)$', content, re.MULTILINE)
    has_http = extraintf_match and 'http' in extraintf_match.group(1)

    # Get port
    port_match = re.search(r'^http-port=(\d+)$', content, re.MULTILINE)
    port = int(port_match.group(1)) if port_match else 8080

    # Check password
    password_match = re.search(r'^http-password=(.+)$', content, re.MULTILINE)
    has_password = bool(password_match and password_match.group(1))

    return has_http, port, has_password


def run_full_setup(port: int = 8080, password: str = "tickplayer") -> dict:
    """
    Run complete setup process.

    Returns:
        Dict with setup results
    """
    results = {
        "success": True,
        "messages": [],
        "needs_restart": False
    }

    # Check and install dependencies
    print("Checking Python dependencies...")
    deps = check_dependencies()
    missing = [pkg for pkg, installed in deps.items() if not installed]

    if missing:
        print(f"Installing missing packages: {', '.join(missing)}")
        success, message = install_python_dependencies()
        results["messages"].append(f"Dependencies: {message}")
        if not success:
            results["success"] = False
    else:
        results["messages"].append("Dependencies: All packages already installed")

    # Configure VLC HTTP interface
    print("Configuring VLC HTTP interface...")
    http_configured, current_port, has_password = check_vlc_http_configured()

    if not http_configured or not has_password:
        success, message, needs_restart = enable_vlc_http_interface(port, password)
        results["messages"].append(f"VLC Config: {message}")
        results["needs_restart"] = needs_restart
        if not success:
            results["success"] = False
    else:
        results["messages"].append(f"VLC Config: Already configured on port {current_port}")

    return results


def main():
    """Main entry point for setup script"""
    import argparse

    parser = argparse.ArgumentParser(description="TickPlayer Setup")
    parser.add_argument("--check", action="store_true", help="Check status only")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    parser.add_argument("--password", type=str, default="tickplayer", help="HTTP password")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.check:
        # Check status
        deps = check_dependencies()
        http_ok, port, has_pw = check_vlc_http_configured()

        if args.json:
            import json
            print(json.dumps({
                "dependencies": deps,
                "all_deps_ok": all(deps.values()),
                "vlc_http_configured": http_ok,
                "vlc_http_port": port,
                "vlc_http_password_set": has_pw
            }))
        else:
            print("=== TickPlayer Status ===")
            print("\nDependencies:")
            for pkg, ok in deps.items():
                status = "OK" if ok else "MISSING"
                print(f"  {pkg}: {status}")

            print("\nVLC HTTP Interface:")
            print(f"  Configured: {'Yes' if http_ok else 'No'}")
            if http_ok:
                print(f"  Port: {port}")
                print(f"  Password set: {'Yes' if has_pw else 'No'}")
    else:
        # Run setup
        print("=== TickPlayer Auto-Setup ===\n")
        results = run_full_setup(args.port, args.password)

        if args.json:
            import json
            print(json.dumps(results))
        else:
            print("\nResults:")
            for msg in results["messages"]:
                print(f"  {msg}")

            if results["needs_restart"]:
                print("\n*** Please restart VLC for changes to take effect ***")

            if results["success"]:
                print("\nSetup completed successfully!")
            else:
                print("\nSetup completed with errors. Please check messages above.")

    return 0 if (args.check or results.get("success", False)) else 1


if __name__ == "__main__":
    sys.exit(main())
