#!/usr/bin/env python3
"""Start the complete local stack, with readiness checks and owned-process cleanup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path.home() / ".cache" / "domain-monitor"


def ready(url):
    try:
        with urlopen(url, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="install locked frontend and backend dependencies before starting")
    parser.add_argument("--frontend-port", type=int, default=3870)
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--env-file", type=Path, help="explicit configuration file; never copied or printed")
    parser.add_argument("--enable-external", action="store_true", help="enable configured external model/search/collector services")
    parser.add_argument("--schedule", action="store_true", help="enable recurring jobs (also requires --enable-external)")
    parser.add_argument("--check", action="store_true", help="check an already running stack and exit")
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.backend_port}"
    front = f"http://127.0.0.1:{args.frontend_port}"
    if args.check:
        checks = {"backend": ready(base + "/health"), "homepage": ready(front),
                  "event_memory": ready(front + "/api/event-memory/health"),
                  "topics_proxy": ready(front + "/api/topics")}
        print(json.dumps(checks, ensure_ascii=False))
        return 0 if all(checks.values()) else 1
    if args.env_file and not args.env_file.is_file():
        parser.error("The specified configuration file does not exist")
    if args.frontend_port == args.backend_port:
        parser.error("Frontend and backend need different ports")
    for port in (args.backend_port, args.frontend_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"Port {port} is already in use. Stop that service or select another port.")
    python = CACHE / "venv" / "bin" / "python"
    lock = (ROOT / "frontend/package-lock.json").read_bytes()
    deps = CACHE / ("frontend-" + hashlib.sha256(lock).hexdigest()[:12])
    modules = ROOT / "frontend/node_modules"
    if args.install:
        CACHE.mkdir(parents=True, exist_ok=True)
        if not python.exists():
            subprocess.run([sys.executable, "-m", "venv", str(CACHE / "venv")], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(ROOT / "backend/requirements.txt")], check=True)
        deps.mkdir(parents=True, exist_ok=True)
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(ROOT / "frontend" / name, deps / name)
        if not (deps / "node_modules/next/package.json").exists():
            subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=deps, check=True)
        # Keep a user's real dependency directory. Repoint only a symlink.
        if modules.is_symlink():
            modules.unlink()
        if not modules.exists():
            modules.symlink_to(deps / "node_modules", target_is_directory=True)
    if not python.exists() or not (modules / "next/dist/bin/next").exists():
        parser.error("Dependencies are missing. Run again with --install.")
    data = args.data_dir.expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(DATABASE_PATH=str(data / "monitor.db"), CHROMA_PERSIST_DIR=str(data / "chroma"),
               EVENT_MEMORY_DATABASE_PATH=str(data / "eventkb.sqlite3"), EVENT_MEMORY_ENABLED="true",
               EXTERNAL_CALLS_ENABLED=str(args.enable_external).lower(),
               SCHEDULER_ENABLED=str(args.enable_external and args.schedule).lower(),
               CORS_ORIGINS=front, INTERNAL_API_BASE=base, EVENT_MEMORY_API_BASE=base,
               NEXT_PUBLIC_API_BASE="", ANONYMIZED_TELEMETRY="False")
    if args.env_file:
        env["DOMAIN_MONITOR_ENV_FILE"] = str(args.env_file.resolve())
    processes = []
    logs = []
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        for name, command, cwd, url in (
            ("backend", [str(python), "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(args.backend_port)], ROOT, base + "/health"),
            ("frontend", ["node", str(modules / "next/dist/bin/next"), "dev", "--webpack", "--hostname", "127.0.0.1", "--port", str(args.frontend_port)], ROOT / "frontend", front),
        ):
            logfile = data / f"{name}.log"
            handle = logfile.open("a")
            logs.append(handle)
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            processes.append(process)
            deadline = time.monotonic() + 60
            while not ready(url):
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f"{name} did not become ready. See {logfile}")
                time.sleep(.25)
        print(f"Domain Monitor ready: {front}\nEvent memory: {front}/event-memory\nExternal services: {'enabled' if args.enable_external else 'disabled (local mode)'}", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(.5)
        raise RuntimeError("A service exited. Check the backend/frontend logs in the data directory.")
    except KeyboardInterrupt:
        return 0
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        for handle in logs:
            handle.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
