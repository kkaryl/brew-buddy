"""Single-command local development launcher for Brew backend (FastAPI) and frontend (Vite)."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO

from app.config import REPO_ROOT, get_settings


def _stream_prefixed_lines(stream: IO[str] | None, prefix: str) -> None:
    if stream is None:
        return
    for line in iter(stream.readline, ""):
        sys.stdout.write(f"[{prefix}] {line}")
        sys.stdout.flush()


def _resolve_npm_binary() -> str:
    found = shutil.which("npm")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "npm"
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return str(fallback)
    msg = "npm executable not found on PATH. Install Node.js LTS to run the web dev server."
    raise RuntimeError(msg)


def _terminate_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


def main() -> int:
    """Launch FastAPI backend and Vite frontend concurrently and supervise both."""
    settings = get_settings()
    backend_host = "127.0.0.1"
    backend_port = settings.port
    frontend_port = int(os.environ.get("WEB_PORT", "5173"))

    npm_bin = _resolve_npm_binary()
    npm_dir = str(Path(npm_bin).parent)
    child_env = os.environ.copy()
    if npm_dir not in child_env.get("PATH", "").split(":"):
        child_env["PATH"] = f"{npm_dir}:{child_env.get('PATH', '')}"
    child_env["BACKEND_ORIGIN"] = f"http://{backend_host}:{backend_port}"

    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.fast_api_app:app",
        "--reload",
        "--host",
        backend_host,
        "--port",
        str(backend_port),
    ]
    frontend_cmd = [
        npm_bin,
        "--prefix",
        str(REPO_ROOT / "web"),
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        str(frontend_port),
    ]

    processes: list[subprocess.Popen[str]] = []
    stop_requested = False

    def _handle_signal(signum: int, _frame: object) -> None:
        nonlocal stop_requested
        del signum
        stop_requested = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        for prefix, cmd in (("api", backend_cmd), ("web", frontend_cmd)):
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            processes.append(proc)
            threading.Thread(
                target=_stream_prefixed_lines,
                args=(proc.stdout, prefix),
                daemon=True,
            ).start()

        while not stop_requested:
            for proc in processes:
                exit_code = proc.poll()
                if exit_code is not None:
                    return exit_code
            time.sleep(0.2)
        return 0
    finally:
        for proc in reversed(processes):
            _terminate_process(proc)


if __name__ == "__main__":
    raise SystemExit(main())
