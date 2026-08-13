#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_version="$(tr -d '[:space:]' < "$repo_root/.python-version")"
venv_python="$repo_root/.venv/bin/python"
test -x "$venv_python" || { echo "Run tools/setup_environment.sh first." >&2; exit 1; }
test "$("$venv_python" --version 2>&1)" = "Python $python_version" || exit 1
"$venv_python" -m pip check

node_target="$(tr -d '[:space:]' < "$repo_root/web/.nvmrc" | sed 's/^v//')"
node_actual="$(node --version | sed 's/^v//')"
test "$node_actual" = "$node_target" || { echo "Node.js version mismatch." >&2; exit 1; }
pnpm_target="$(node -p "require('$repo_root/web/package.json').packageManager.split('@').pop()")"
test "$(pnpm --version)" = "$pnpm_target" || { echo "pnpm version mismatch." >&2; exit 1; }
echo "Environment verification passed."
