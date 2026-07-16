#!/bin/bash
set -euo pipefail

UV_BIN="${HOME}/.local/bin/uv"

if command -v uv &>/dev/null; then
  echo "uv already installed at $(command -v uv), skipping."
  exit 0
fi

if [[ -x "${UV_BIN}" ]]; then
  echo "uv already installed at ${UV_BIN}, skipping."
  exit 0
fi

echo "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh

# shellcheck source=/dev/null
source "${HOME}/.local/bin/env"
