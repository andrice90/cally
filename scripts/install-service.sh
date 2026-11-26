#!/usr/bin/env bash
# Register Cinder as the Sprite's HTTP service on port 8080.
# Only one service can own the HTTP port: remove any other first (e.g. `sprite-env services delete mcp-demo`).
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync
sprite-env services create cinder \
  --cmd "$(pwd)/.venv/bin/python" \
  --args "-m,cinder,serve,--port,8080" \
  --dir "$(pwd)" \
  --http-port 8080
