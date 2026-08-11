"""Desktop entry point for the packaged SOC Audit application."""
from __future__ import annotations

import json
import logging
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
        # Downloads are disabled by default in pywebview. Keep them enabled for
        # browser-style fallback downloads in addition to the native Save As API.
        webview.settings["ALLOW_DOWNLOADS"] = True
        desktop_api = DesktopApi()
        window = webview.create_window(
            "SOC Audit Automation",
            url,
            js_api=desktop_api,
            width=1280,
            height=850,
            min_size=(1000, 650),
        )
        desktop_api.window = window
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
