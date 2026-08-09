#!/usr/bin/env bash
set -uo pipefail
cp "$FIXTURE/hidden_test_tags.py" ./test_tags_hidden.py
uv run --with pytest pytest -q test_tags_hidden.py >/dev/null 2>&1 || { echo "FAIL: hidden tests red"; exit 1; }
echo PASS
