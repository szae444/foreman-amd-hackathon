#!/usr/bin/env bash
# Publish this project as a PUBLIC GitHub repo (required by the lablab submission).
#   bash deploy/publish_github.sh [repo-name]
# Uses the GitHub CLI account you are logged in with (gh auth status). Run only when you mean to publish.
set -euo pipefail
NAME="${1:-foreman-amd-hackathon}"
cd "$(dirname "$0")/.."

[ -d .git ] || git init -q -b main
git add -A
echo "Files to publish:"; git diff --cached --stat | tail -1
git commit -q -m "Foreman: shop-floor inspection agent on AMD Instinct (AMD Developer Hackathon ACT III)" || true
gh repo create "$NAME" --public --source . --remote origin --push \
  --description "PatchCore finds the defect, Gemma 4 explains it, the manual says how to fix it. Both models run on one AMD Instinct MI300X."
gh repo view "$NAME" --json url --jq .url
