#!/usr/bin/env bash
# Runs ON the AMD Developer Cloud droplet (MI300X). Idempotent: safe to re-run.
#  1. Gemma 4 on vLLM (ROCm), bound to 127.0.0.1:8000 — never exposed publicly
#  2. Foreman app (PatchCore on ROCm + agent + UI) on :8080
set -euo pipefail
cd /opt/foreman
[ -f .env ] || cp .env.example .env

echo "== GPU"
rocm-smi --showproductname || amd-smi list || true

if ! docker compose version >/dev/null 2>&1; then
  echo "== installing docker compose plugin"
  apt-get update -y && apt-get install -y docker-compose-plugin
fi

# The vLLM quick-start image ships a container that may already hold the GPU / port 8000.
if docker ps --format '{{.Names}}' | grep -qx rocm; then
  echo "== stopping the quick-start 'rocm' container (frees GPU memory + port 8000)"
  docker stop rocm || true
fi

echo "== starting Gemma 4 on vLLM (first start downloads ~60 GB of weights)"
docker compose up -d vllm
for i in $(seq 1 180); do
  if curl -sf http://127.0.0.1:8000/v1/models >/dev/null; then echo "vLLM ready"; break; fi
  sleep 10; [ $((i % 6)) -eq 0 ] && docker compose logs --tail 3 vllm
done
curl -sf http://127.0.0.1:8000/v1/models || { echo "vLLM did not come up — see: docker compose logs vllm"; exit 1; }

echo "== building + starting Foreman (trains PatchCore on the MI300X on first start)"
docker compose up -d --build foreman
for i in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8080/api/health >/dev/null; then break; fi
  sleep 5
done
curl -s http://127.0.0.1:8080/api/health | head -c 600; echo

if command -v ufw >/dev/null; then ufw allow 8080/tcp || true; fi
echo "== done. Smoke test: docker compose exec foreman python -m scripts.smoke_live"
