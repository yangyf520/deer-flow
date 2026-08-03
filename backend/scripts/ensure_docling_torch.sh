#!/usr/bin/env bash
# Ensure torch/torchvision are importable for Docling (macOS dev environments).
# Linux x86_64 resolves torch+cpu via uv lock; Darwin wheels come from PyPI.
set -euo pipefail
cd "$(dirname "$0")/.."

if uv run python -c "import torch" >/dev/null 2>&1; then
  echo "torch already available in backend/.venv"
  exit 0
fi

echo "Installing torch/torchvision from PyPI for Docling..."
uv pip install --index-url https://pypi.org/simple \
  "torch>=2.2.2,<2.3.0" \
  "torchvision>=0.17.2,<0.18.0"
uv run python -c "import torch; print('torch', torch.__version__)"
