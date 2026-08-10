"""Desktop entry point for the packaged SOC Audit application."""
from __future__ import annotations

import logging
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path


# Keep `python desktop.py` working from a source checkout. PyInstaller uses the
# matching --paths option when it analyzes this entry point.
if not getattr(sys, "frozen", False):
    backend_dir = Path(__file__).resolve().parent / "backend"
    sys.path.insert(0, str(backend_dir))

import uvicorn
import webview

from app.config import settings
from app.main import app


HOST = "127.0.0.1"


def _find_available_port() -> int:
    """Ask the OS for an unused local port to avoid launch-time conflicts."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _wait_for_server(url: str, attempts: int = 100) -> None:
    # Do not let a corporate HTTP proxy intercept loopback health checks.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(attempts):
        try:
            with opener.open(f"{url}/health", timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)

    raise RuntimeError("The local API server did not start in time.")


def main() -> None:
    log_path = settings.root_dir / "soc-audit.log"
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    port = _find_available_port()
    url = f"http://{HOST}:{port}"
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=HOST,
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    try:
        _wait_for_server(url)
        webview.create_window(
            "SOC Audit Automation",
            url,
            width=1280,
            height=850,
            min_size=(1000, 650),
        )
        webview.start(storage_path=str(settings.root_dir / "webview"))
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)


def _report_fatal_error(error: Exception) -> None:
    logging.exception("Desktop application failed to start")
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            0,
            f"SOC Audit could not start.\n\n{error}\n\n"
            f"See the log under: {settings.root_dir}",
            "SOC Audit - Startup Error",
            0x10,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _report_fatal_error(exc)
        if sys.platform != "win32":
            raise
