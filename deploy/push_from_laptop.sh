#!/usr/bin/env bash
# Copy the project to an AMD Developer Cloud droplet and run the setup there.
#   bash deploy/push_from_laptop.sh <droplet-ip> [ssh-key]
set -euo pipefail
IP="${1:?usage: push_from_laptop.sh <droplet-ip> [ssh-key]}"
KEY="${2:-$HOME/.ssh/id_ed25519}"
cd "$(dirname "$0")/.."

tar czf /tmp/foreman.tgz \
  --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
  --exclude='data/mvtec' --exclude='data/*.db' --exclude='data/models/*.pt' \
  .
scp -i "$KEY" /tmp/foreman.tgz "root@$IP:/tmp/foreman.tgz"
ssh -i "$KEY" "root@$IP" 'mkdir -p /opt/foreman && tar xzf /tmp/foreman.tgz -C /opt/foreman && bash /opt/foreman/deploy/setup_droplet.sh'
echo "Open http://$IP:8080"
