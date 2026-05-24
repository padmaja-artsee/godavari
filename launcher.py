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
FINANCE_PORT = 8001


def _find_free_port(preferred: int) -> int:
    """Return preferred port if available, otherwise any free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, preferred))
            return preferred
        except OSError:
            s.bind((HOST, 0))
            return s.getsockname()[1]


def _kill_port(port: int) -> None:
    """Kill any process currently listening on port (our own stale instance)."""
    try:
        import subprocess
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True, text=True
        )
        for pid_str in result.stdout.strip().splitlines():
            pid = int(pid_str.strip())
            if pid != os.getpid():
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        time.sleep(0.5)
    except Exception:
        pass


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


def _user_data_dir(app_name: str) -> str:
    """
    Return a writable, persistent user data directory for the app.
    - macOS:   ~/Library/Application Support/<app_name>
    - Windows: %APPDATA%/<app_name>
    - Linux:   ~/.local/share/<app_name>
    """
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    data_dir = os.path.join(base, app_name)
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def _setup_logging(log_dir: str) -> None:
    """Route Python logging + uvicorn output to a rotating log file."""
    import logging
    from logging.handlers import RotatingFileHandler
    log_path = os.path.join(log_dir, "leads.log")
    handler = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(handler)
    # Also redirect stdout/stderr so any print() or raw exceptions go to file.
    try:
        sys.stdout = open(log_path, "a", buffering=1)
        sys.stderr = sys.stdout
    except Exception:
        pass


def main() -> None:
    # When frozen by PyInstaller sys._MEIPASS is set; resolve the app root.
    if getattr(sys, "frozen", False):
        import shutil
        app_root = sys._MEIPASS  # type: ignore[attr-defined]
        sys.path.insert(0, app_root)

        # Expose the bundle root so app/main.py can locate templates/static.
        os.environ.setdefault("LEADS_BUNDLE_BASE", app_root)

        # Store user data (DB, uploads, exports) in a writable OS location,
        # NOT inside the app bundle which may be read-only.
        user_dir = _user_data_dir("GodavariLeads")
        user_db = os.path.join(user_dir, "leads.db")
        bundled_db = os.path.join(app_root, "data", "leads.db")

        # First-run: copy the pre-seeded DB from the bundle so seed loading is instant.
        if not os.path.exists(user_db) and os.path.exists(bundled_db):
            shutil.copy2(bundled_db, user_db)

        os.environ.setdefault("LEADS_DB_PATH", user_db)
        os.environ.setdefault("LEADS_DATA_DIR", user_dir)
        # Seed data (product_catalogue.json, etc.) come from the read-only bundle.
        os.environ.setdefault("LEADS_SEED_DIR", os.path.join(app_root, "data"))

        # Write errors to a log file so they're visible without a console.
        _setup_logging(user_dir)

        # Kill any stale instance of ourselves on PORT before binding.
        _kill_port(PORT)
        _kill_port(FINANCE_PORT)
    else:
        # Running from source — project root is this file's directory.
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, here)

    port = _find_free_port(PORT)

    # Start Finance mini-app in a background thread.
    def _start_finance() -> None:
        try:
            finance_port = _find_free_port(FINANCE_PORT)
            os.environ.setdefault("FINANCE_PORT", str(finance_port))
            import uvicorn as _uv
            _uv.run(
                "finance.app.main:app",
                host=HOST,
                port=finance_port,
                reload=False,
                log_level="warning",
            )
        except Exception as exc:
            print(f"[Finance] failed to start: {exc}")

    threading.Thread(target=_start_finance, daemon=True).start()

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
