#!/usr/bin/env python3
"""
Launcher for the packaged desktop app.

When bundled with PyInstaller this is the entry point.
It starts the FastAPI/uvicorn server on localhost:8000 and
signals Tauri (or falls back to the default browser) to open the UI.

Environment variable LEADS_NO_BROWSER=1 suppresses the browser open
(used when Tauri is managing the window itself).
"""
import os
import sys
import signal
import socket
import threading
import time
import webbrowser

HOST = "127.0.0.1"
PORT = 8000
URL  = f"http://{HOST}:{PORT}"


def _find_free_port(preferred: int) -> int:
    """Return preferred port if available, otherwise any free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, preferred))
            return preferred
        except OSError:
            s.bind((HOST, 0))
            return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 15.0) -> bool:
    """Poll until the server accepts connections or timeout is reached."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _open_browser(port: int) -> None:
    if os.environ.get("LEADS_NO_BROWSER") == "1":
        return
    if _wait_for_server(port):
        webbrowser.open(f"http://{HOST}:{port}")


def main() -> None:
    # When frozen by PyInstaller sys._MEIPASS is set; resolve the app root.
    if getattr(sys, "frozen", False):
        app_root = sys._MEIPASS  # type: ignore[attr-defined]
        sys.path.insert(0, app_root)
        # Store the DB next to the actual executable, not the temp bundle dir.
        exe_dir = os.path.dirname(sys.executable)
        os.environ.setdefault("LEADS_DB_PATH", os.path.join(exe_dir, "leads.db"))
        os.environ.setdefault("LEADS_DATA_DIR", os.path.join(exe_dir, "data"))
    else:
        # Running from source — project root is this file's directory.
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, here)

    port = _find_free_port(PORT)

    # Open browser in a background thread so it waits for the server.
    threading.Thread(target=_open_browser, args=(port,), daemon=True).start()

    # Graceful shutdown on SIGTERM (Tauri sends this on window close).
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=port,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
