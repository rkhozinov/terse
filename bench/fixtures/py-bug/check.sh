#!/usr/bin/env bash
set -uo pipefail
uv run --with pytest pytest -q >/dev/null 2>&1 || { echo "FAIL: tests red"; exit 1; }
echo PASS
