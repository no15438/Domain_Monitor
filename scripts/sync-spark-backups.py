#!/usr/bin/env python3
"""Keep a second, SSH-encrypted-in-transit copy on the user's Mac."""
import hashlib
import os
from pathlib import Path
import re
import subprocess

destination = Path.home() / ".local/share/domain-monitor/backups"
destination.mkdir(parents=True, mode=0o700, exist_ok=True)
os.chmod(destination, 0o700)
remote = "/srv/domain-monitor/backups/"
command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "spark-lan"]
names = subprocess.check_output(command + ["find " + remote + " -maxdepth 1 -type f -name '*.tar.gz' -printf '%f\\n'"], timeout=20).decode().splitlines()
copied = 0
for name in names:
    if not re.fullmatch(r"domain-monitor-\d{8}T\d{6}Z\.tar\.gz", name):
        continue
    target = destination / name
    if target.exists() and Path(str(target) + ".sha256").exists():
        continue
    partial = Path(str(target) + ".partial")
    for source, local in [(name, partial), (name + ".sha256", Path(str(target) + ".sha256"))]:
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "spark-lan:" + remote + source, str(local)], check=True, timeout=300)
        os.chmod(local, 0o600)
    expected = Path(str(target) + ".sha256").read_text().split()[0]
    if hashlib.file_digest(partial.open("rb"), "sha256").hexdigest() != expected:
        raise SystemExit("Backup transfer checksum mismatch.")
    partial.replace(target)
    copied += 1
print(f"Verified {copied} new backup(s); {len(names)} archive(s) available on Spark.")
