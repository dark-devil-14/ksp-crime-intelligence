#!/usr/bin/env python3
"""Minimal AppSail-compatible HTTP service for the KSP V8 demonstration.

The service uses only Python's standard library for HTTP serving. The model
runtime dependencies are included so the existing pipeline can be rerun through
an admin-only endpoint or directly from the shell.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = ROOT / "runtime"
RUNTIME_DIR.mkdir(exist_ok=True)
STATUS_PATH = RUNTIME_DIR / "pipeline_status.json"
LOG_PATH = RUNTIME_DIR / "pipeline_refresh.log"

PIPELINE_LOCK = threading.Lock()
PIPELINE_THREAD: threading.Thread | None = None

STATIC_PREFIXES = {
    "/assets/": ROOT / "assets",
    "/reports/": ROOT / "reports",
    "/data/": ROOT / "data",
    "/pipeline_outputs/": ROOT / "pipeline_outputs",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_status() -> dict:
    if STATUS_PATH.exists():
        try:
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"state": "idle", "updated_at": utc_now()}


def save_status(**values: object) -> None:
    current = load_status()
    current.update(values)
    current["updated_at"] = utc_now()
    temp = STATUS_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(current, indent=2), encoding="utf-8")
    os.replace(temp, STATUS_PATH)


def safe_child(base: Path, relative: str) -> Path | None:
    try:
        target = (base / unquote(relative)).resolve()
        target.relative_to(base.resolve())
        return target
    except Exception:
        return None


def content_sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def authorized(handler: BaseHTTPRequestHandler) -> bool:
    configured = os.getenv("ADMIN_TOKEN", "").strip()
    if not configured:
        return False
    supplied = handler.headers.get("X-Admin-Token", "")
    if not supplied:
        auth = handler.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
    return bool(supplied) and secrets.compare_digest(configured, supplied)


def run_command(command: list[str], log_handle) -> None:
    log_handle.write("\n$ " + " ".join(command) + "\n")
    log_handle.flush()
    result = subprocess.run(
        command,
        cwd=ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {' '.join(command)}")


def pipeline_refresh() -> None:
    """Run the forecasting pipeline and atomically replace public outputs."""
    global PIPELINE_THREAD
    with PIPELINE_LOCK:
        started = utc_now()
        save_status(state="running", started_at=started, message="Pipeline refresh started")
        refresh_root = RUNTIME_DIR / f"refresh_{int(time.time())}"
        refresh_outputs = refresh_root / "pipeline_outputs"
        refresh_data = refresh_root / "dashboard_data_v8.json"
        refresh_index = refresh_root / "index.html"
        refresh_outputs.mkdir(parents=True, exist_ok=True)

        dataset = ROOT / "data" / "karnataka_crime_dataset_grounded_v8_80k.csv.gz"
        try:
            with LOG_PATH.open("a", encoding="utf-8") as log_handle:
                log_handle.write(f"\n=== Refresh started {started} ===\n")
                run_command(
                    [
                        sys.executable,
                        "ksp_pipeline_v8_final.py",
                        "--csv",
                        str(dataset),
                        "--out-dir",
                        str(refresh_outputs),
                        "--skip-heatmap",
                    ],
                    log_handle,
                )
                run_command(
                    [
                        sys.executable,
                        "scripts/build_dashboard_profiles_v8.py",
                        "--csv",
                        str(dataset),
                        "--dashboard",
                        str(refresh_outputs / "dashboard_data.json"),
                        "--output",
                        str(refresh_data),
                    ],
                    log_handle,
                )
                run_command(
                    [
                        sys.executable,
                        "scripts/build_release_dashboard.py",
                        "--data",
                        str(refresh_data),
                        "--output",
                        str(refresh_index),
                    ],
                    log_handle,
                )

            # Atomically publish JSON outputs and rebuilt dashboard.
            public_outputs = ROOT / "pipeline_outputs"
            public_outputs.mkdir(exist_ok=True)
            for source in refresh_outputs.glob("*.json"):
                os.replace(source, public_outputs / source.name)
            os.replace(refresh_data, ROOT / "data" / "dashboard_data_v8.json")
            os.replace(refresh_index, ROOT / "index.html")

            finished = utc_now()
            save_status(
                state="succeeded",
                finished_at=finished,
                message="Pipeline refresh completed",
                dashboard_sha256=content_sha256(ROOT / "data" / "dashboard_data_v8.json"),
            )
        except Exception as exc:
            save_status(
                state="failed",
                finished_at=utc_now(),
                message=str(exc),
            )
        finally:
            PIPELINE_THREAD = None


class KSPHandler(BaseHTTPRequestHandler):
    server_version = "KSP-Catalyst/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stdout.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def _security_headers(self, *, cache: str = "no-store") -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        self.send_header("Cache-Control", cache)
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com; "
            "img-src 'self' data: blob: https://*.basemaps.cartocdn.com https://*.tile.openstreetmap.org; "
            "connect-src 'self'; font-src 'self' data:; worker-src 'self' blob:;",
        )

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path, *, cache: str = "public, max-age=3600") -> None:
        if not path.is_file():
            self._json({"error": "not_found", "path": self.path}, HTTPStatus.NOT_FOUND)
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            size = path.stat().st_size
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(size))
            self.send_header("ETag", f'"{int(path.stat().st_mtime)}-{size}"')
            self._security_headers(cache=cache)
            self.end_headers()
            with path.open("rb") as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path in {"/", "/index.html"}:
            self._serve_file(ROOT / "index.html", cache="no-cache")
            return
        if path in {"/healthz", "/api/health"}:
            dashboard = ROOT / "data" / "dashboard_data_v8.json"
            self._json(
                {
                    "status": "ok",
                    "service": "KSP Crime Intelligence V8",
                    "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").exists() else "V8",
                    "time_utc": utc_now(),
                    "dashboard_present": dashboard.exists(),
                    "dashboard_sha256": content_sha256(dashboard),
                    "pipeline": load_status(),
                    "pipeline_run_enabled": os.getenv("ENABLE_PIPELINE_RUN", "0") == "1",
                }
            )
            return
        if path == "/api/dashboard":
            self._serve_file(ROOT / "data" / "dashboard_data_v8.json", cache="no-cache")
            return
        if path == "/api/pipeline/status":
            self._json(load_status())
            return
        if path == "/api/pipeline/log":
            if not authorized(self):
                self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            query = parse_qs(parsed.query)
            try:
                lines = min(max(int(query.get("lines", ["200"])[0]), 1), 2000)
            except ValueError:
                lines = 200
            if not LOG_PATH.exists():
                self._text("No pipeline refresh log yet.\n")
                return
            content = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            self._text("\n".join(content[-lines:]) + "\n")
            return
        if path == "/api/outputs":
            outputs = []
            for file_path in sorted((ROOT / "pipeline_outputs").glob("*.json")):
                outputs.append(
                    {
                        "name": file_path.name,
                        "bytes": file_path.stat().st_size,
                        "sha256": content_sha256(file_path),
                        "url": f"/pipeline_outputs/{file_path.name}",
                    }
                )
            self._json({"outputs": outputs})
            return

        for prefix, base in STATIC_PREFIXES.items():
            if path.startswith(prefix):
                target = safe_child(base, path[len(prefix):])
                if target is None:
                    self._json({"error": "invalid_path"}, HTTPStatus.BAD_REQUEST)
                    return
                cache = "no-cache" if prefix in {"/data/", "/pipeline_outputs/"} else "public, max-age=86400"
                self._serve_file(target, cache=cache)
                return

        self._json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        global PIPELINE_THREAD
        parsed = urlparse(self.path)
        if parsed.path != "/api/pipeline/run":
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        if os.getenv("ENABLE_PIPELINE_RUN", "0") != "1":
            self._json(
                {
                    "error": "pipeline_run_disabled",
                    "message": "Set ENABLE_PIPELINE_RUN=1 and ADMIN_TOKEN in AppSail environment variables.",
                },
                HTTPStatus.FORBIDDEN,
            )
            return
        if not authorized(self):
            self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        if PIPELINE_THREAD is not None and PIPELINE_THREAD.is_alive():
            self._json({"error": "already_running", "status": load_status()}, HTTPStatus.CONFLICT)
            return
        PIPELINE_THREAD = threading.Thread(target=pipeline_refresh, name="pipeline-refresh", daemon=True)
        PIPELINE_THREAD.start()
        self._json({"accepted": True, "status_url": "/api/pipeline/status"}, HTTPStatus.ACCEPTED)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self._security_headers()
        self.end_headers()


def main() -> None:
    port = int(os.getenv("X_ZOHO_CATALYST_LISTEN_PORT", os.getenv("PORT", "9000")))
    host = os.getenv("HOST", "0.0.0.0")
    save_status(state=load_status().get("state", "idle"))
    httpd = ThreadingHTTPServer((host, port), KSPHandler)
    print(f"KSP Catalyst service listening on http://{host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
