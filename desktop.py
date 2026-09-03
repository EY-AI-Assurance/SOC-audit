"""Desktop entry point for the packaged SOC Audit application."""
from __future__ import annotations

import json
import logging
import os
import shutil
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
STARTUP_TIMEOUT_SECONDS = 20


class DesktopApi:
    """Native operations exposed to the React application by pywebview."""

    def __init__(self) -> None:
        self.window = None

    def save_output(self, job_id: str, report_id: str) -> dict[str, str]:
        """Show a native Save As dialog and copy a completed workbook there."""
        try:
            if self.window is None:
                raise RuntimeError("The desktop window is not ready.")

            job_path = (settings.jobs_dir / f"{job_id}.json").resolve()
            jobs_root = settings.jobs_dir.resolve()
            if not job_path.is_relative_to(jobs_root) or not job_path.is_file():
                raise FileNotFoundError("Job not found.")

            job = json.loads(job_path.read_text(encoding="utf-8"))
            report = next(
                (item for item in job.get("reports", []) if item.get("report_id") == report_id),
                None,
            )
            if report is None:
                raise FileNotFoundError("Report not found in this job.")
            if report.get("status") != "DONE":
                raise RuntimeError("The output workbook is not ready yet.")

            output_filename = report.get("output_filename", "")
            output_path = (settings.outputs_dir / output_filename).resolve()
            outputs_root = settings.outputs_dir.resolve()
            if (
                not output_filename
                or not output_path.is_relative_to(outputs_root)
                or not output_path.is_file()
            ):
                raise FileNotFoundError("The output workbook is missing.")

            downloads_dir = Path.home() / "Downloads"
            initial_dir = downloads_dir if downloads_dir.is_dir() else Path.home()
            dialog_type = (
                webview.FileDialog.SAVE
                if hasattr(webview, "FileDialog")
                else webview.SAVE_DIALOG
            )
            selected = self.window.create_file_dialog(
                dialog_type,
                directory=str(initial_dir),
                save_filename=output_filename,
                file_types=("Excel Workbook (*.xlsx)",),
            )
            if not selected:
                return {"status": "cancelled"}

            selected_path = selected[0] if isinstance(selected, (list, tuple)) else selected
            destination = Path(selected_path)
            if destination.suffix.lower() != ".xlsx":
                destination = Path(f"{destination}.xlsx")

            shutil.copy2(output_path, destination)
            logging.info("Saved output workbook to %s", destination)
            return {"status": "saved", "path": str(destination)}
        except Exception as exc:
            logging.exception("Could not save output workbook")
            return {"status": "error", "message": str(exc)}


def _create_listener() -> socket.socket:
    """Reserve a loopback port until Uvicorn has taken ownership of it.

    Asking the operating system for an available port and closing it before
    starting Uvicorn leaves a small but real race: another process can bind the
    port in between. Passing an already-bound listener to Uvicorn removes that
    launch-time failure mode.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((HOST, 0))
    listener.listen(socket.SOMAXCONN)
    return listener


def _wait_for_server(url: str, timeout_seconds: float = STARTUP_TIMEOUT_SECONDS) -> None:
    """Wait for FastAPI and retain the last failure for the startup log."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with opener.open(f"{url}/health", timeout=0.5) as response:
                if response.status == 200:
                    logging.info("Local API server is ready at %s", url)
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)

    raise RuntimeError(
        f"The local API server did not start within {timeout_seconds:.0f} seconds. "
        f"Last health-check error: {last_error}"
    )


def _start_webview(url: str, desktop_api: DesktopApi) -> None:
    """Start only the modern Edge WebView2 renderer on Windows.

    The React production bundle requires a current browser engine. Letting
    pywebview fall back to the legacy MSHTML/IE renderer produces blank or
    apparently frozen windows on machines without WebView2.
    """
    webview.settings["ALLOW_DOWNLOADS"] = True
    window = webview.create_window(
        "SOC Audit Automation",
        url,
        js_api=desktop_api,
        width=1280,
        height=850,
        min_size=(1000, 650),
    )
    desktop_api.window = window
    try:
        webview.start(
            gui="edgechromium" if sys.platform == "win32" else None,
            storage_path=str(settings.root_dir / "webview"),
            debug=os.environ.get("SOC_AUDIT_DEBUG") == "1",
        )
    except Exception as exc:
        if sys.platform == "win32":
            raise RuntimeError(
                "The Microsoft Edge WebView2 Runtime could not be initialized. "
                "Install or repair the Evergreen WebView2 Runtime, then try again."
            ) from exc
        raise


def main() -> None:
    log_path = settings.root_dir / "soc-audit.log"
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logging.info("Starting SOC Audit desktop application")
    listener = _create_listener()
    port = int(listener.getsockname()[1])
    url = f"http://{HOST}:{port}"
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=HOST,
            port=port,
            log_level="info",
            access_log=False,
        )
    )
    server_thread = threading.Thread(
        target=lambda: server.run(sockets=[listener]),
        name="soc-audit-api",
        daemon=True,
    )
    server_thread.start()

    try:
        _wait_for_server(url)
        desktop_api = DesktopApi()
        _start_webview(url, desktop_api)
    finally:
        logging.info("Stopping SOC Audit desktop application")
        server.should_exit = True
        server_thread.join(timeout=5)
        listener.close()


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
