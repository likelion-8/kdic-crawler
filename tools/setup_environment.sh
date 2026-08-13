#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_version="$(tr -d '[:space:]' < "$repo_root/.python-version")"
python_bin="python${python_version%.*}"

command -v "$python_bin" >/dev/null || { echo "Install $python_bin first." >&2; exit 1; }
test "$("$python_bin" --version 2>&1)" = "Python $python_version" || { echo "Python version mismatch." >&2; exit 1; }

venv_dir="$repo_root/.venv"
if [[ ! -x "$venv_dir/bin/python" ]]; then
  "$python_bin" -m venv "$venv_dir"
fi
test "$("$venv_dir/bin/python" --version 2>&1)" = "Python $python_version" || { echo "Virtualenv Python version mismatch." >&2; exit 1; }
"$venv_dir/bin/python" -m pip install -r "$repo_root/requirements.txt"

if [[ ! -f "$repo_root/.env" && -f "$repo_root/.env.example" ]]; then
  cp "$repo_root/.env.example" "$repo_root/.env"
  echo "Created .env from .env.example; fill in local credentials."
fi

node_target="$(tr -d '[:space:]' < "$repo_root/web/.nvmrc" | sed 's/^v//')"
node_actual="$(node --version | sed 's/^v//')"
test "$node_actual" = "$node_target" || { echo "Node.js $node_target is required; found $node_actual." >&2; exit 1; }

pnpm_target="$(node -p "require('$repo_root/web/package.json').packageManager.split('@').pop()")"
if ! command -v pnpm >/dev/null || [[ "$(pnpm --version)" != "$pnpm_target" ]]; then
  npm install --global "pnpm@$pnpm_target"
fi
test "$(pnpm --version)" = "$pnpm_target" || { echo "pnpm version mismatch." >&2; exit 1; }
(cd "$repo_root/web" && pnpm install --frozen-lockfile)
echo "Environment setup completed."
