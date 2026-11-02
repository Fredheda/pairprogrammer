#!/usr/bin/env bash
# Runs every check .github/workflows/ci.yml runs. Keep the two in sync.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

step() { printf '\n== %s\n' "$*"; }

step "backend"
cd "$root/backend"
poetry install --no-interaction
poetry run ruff check .
poetry run ruff format --check .
poetry run pyright
poetry run pytest -v

step "frontend"
cd "$root/frontend"
npm ci
npm run lint
npm run typecheck
npm test
npm run build

printf '\n== all local CI checks passed\n'
