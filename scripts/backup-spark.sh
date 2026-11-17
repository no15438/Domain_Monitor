#!/usr/bin/env bash
# Quiesce the writer before copying SQLite WAL and Chroma HNSW files together.
set -euo pipefail
ROOT="${DOMAIN_MONITOR_ROOT:-/srv/domain-monitor}"
umask 077
mkdir -p "$ROOT/backups"
exec 9>"$ROOT/backup.lock"
flock -n 9 || exit 0
cd "$ROOT/app"
compose() { docker compose --env-file "$ROOT/config/deployment.env" -f compose.spark.yaml "$@"; }
was_running="$(compose ps --status running -q backend)"
[[ -n "$was_running" ]] || { echo 'Backend is not running; backup aborted.' >&2; exit 1; }
backup_name="domain-monitor-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
archive="$ROOT/backups/$backup_name"
resume() { compose start backend >/dev/null; }
trap resume EXIT
compose stop -t 120 backend
tar -C "$ROOT" -czf "$archive.partial" data
tar -tzf "$archive.partial" >/dev/null
mv "$archive.partial" "$archive"
(cd "$ROOT/backups" && sha256sum "$backup_name" > "$backup_name.sha256")
chmod 600 "$archive" "$archive.sha256"
# Keep two weeks. Only this script's timestamped archives are eligible.
find "$ROOT/backups" -maxdepth 1 -type f -name 'domain-monitor-????????T??????Z.tar.gz*' -mtime +14 -delete
echo "Backup created: $backup_name"
