#!/usr/bin/env python3
"""Restore a complete backup into a NEW directory and verify all SQLite files."""
import argparse
import hashlib
import json
import sqlite3
import tarfile
from pathlib import Path, PurePosixPath

parser = argparse.ArgumentParser()
parser.add_argument("archive", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
checksum = Path(str(args.archive) + ".sha256").read_text().split()[0]
if hashlib.file_digest(args.archive.open("rb"), "sha256").hexdigest() != checksum:
    raise SystemExit("Backup checksum mismatch.")
if args.destination.exists():
    raise SystemExit("Destination already exists; refusing to overwrite data.")
with tarfile.open(args.archive) as archive:
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "data" or not (member.isfile() or member.isdir()):
            raise SystemExit("Unsafe backup member.")
    args.destination.mkdir(mode=0o700, parents=True)
    archive.extractall(args.destination, filter="data")
results = {}
for path in (args.destination / "data").rglob("*"):
    if path.is_file() and path.suffix in (".db", ".sqlite3", ".sqlite"):
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            status = conn.execute("PRAGMA integrity_check").fetchall()
        if status != [("ok",)]:
            raise SystemExit("SQLite integrity check failed: " + path.name)
        results[str(path.relative_to(args.destination))] = "ok"
if not results:
    raise SystemExit("No databases found in backup.")
print(json.dumps({"restored_to": str(args.destination), "databases": results, "checksum": "ok"}, indent=2))
