#!/usr/bin/env bash
# Domain Monitor — cloud VM bootstrap (Ubuntu 22.04+)
#
# === 0) Complete in the cloud console before running this script===
# - Create a VM: Ubuntu 22.04/24.04 LTS; recommended 2 vCPU / 4 GB RAM / 40 GB+ disk
# - Allow inbound TCP 22 (SSH) and TCP 3000 (frontend)
# - Keep port 8000 private; the frontend proxies /api to the backend container
# - Connect over SSH, then run this script from the repository root
#
# === 1) Clone the private repository before running this script===
# Recommended: add a read-only SSH public key in GitHub Settings → Deploy keys, then:
#   git clone git@github.com:<owner>/Domain_Monitor.git && cd Domain_Monitor
# Or use HTTPS with a PAT (keep tokens private):
#   git clone https://github.com/<owner>/Domain_Monitor.git && cd Domain_Monitor
#
# === 2) Run ===
#   chmod +x scripts/cloud-vm-bootstrap.sh
#   ./scripts/cloud-vm-bootstrap.sh
#
# If Docker reports permission errors after installation, reconnect over SSH and run the script again.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f compose.yaml ]]; then
  echo "error: compose.yaml not found (run from repo root: $ROOT)" >&2
  exit 1
fi

run_apt() {
  if [[ "${EUID}" -eq 0 ]]; then
    DEBIAN_FRONTEND=noninteractive apt-get "$@"
  else
    sudo DEBIAN_FRONTEND=noninteractive apt-get "$@"
  fi
}

echo "[1/5] apt base packages (curl, git, ca-certificates)..."
run_apt update -y
run_apt install -y ca-certificates curl git

if ! command -v docker >/dev/null 2>&1; then
  echo "[2/5] installing Docker (get.docker.com)..."
  curl -fsSL https://get.docker.com | sh
else
  echo "[2/5] Docker already installed, skipping."
fi

if [[ "${EUID}" -ne 0 ]] && ! id -nG | tr ' ' '\n' | grep -qx docker; then
  echo "adding user to docker group (re-login SSH if docker permission denied later)..."
  sudo usermod -aG docker "$USER" || true
fi

docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
  elif sudo docker info >/dev/null 2>&1; then
    sudo docker "$@"
  else
    echo "error: cannot run docker (try logging out and SSH back in, then re-run this script)" >&2
    exit 1
  fi
}

compose() {
  if docker info >/dev/null 2>&1; then
    docker compose "$@"
  elif sudo docker info >/dev/null 2>&1; then
    sudo docker compose "$@"
  else
    echo "error: cannot run docker compose" >&2
    exit 1
  fi
}

echo "[3/5] docker / compose:"
docker_cmd --version
compose version

if [[ ! -f backend/.env ]]; then
  echo "[4/5] backend/.env missing — copying from backend/.env.example"
  cp backend/.env.example backend/.env
  echo "IMPORTANT: edit backend/.env with real API keys before relying on production traffic."
else
  echo "[4/5] backend/.env already present, not overwriting."
fi

echo "[5/5] building and starting stack..."
compose up -d --build

compose ps

echo "Smoke (localhost):"
if curl -fsS -o /dev/null -w "frontend HTTP %{http_code}\n" http://127.0.0.1:3000/; then
  :
else
  echo "warning: curl to :3000 failed (containers may still be starting); check: compose logs -f frontend" >&2
fi

if compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()" >/dev/null 2>&1; then
  echo "backend /health OK (inside backend container)"
else
  echo "note: backend health check skipped or failed (optional; check: compose logs -f backend)" >&2
fi

echo ""
echo "Done. Open http://<YOUR_PUBLIC_IP>:3000 in a browser (security group must allow TCP 3000)."
