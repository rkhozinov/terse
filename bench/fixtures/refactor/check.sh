#!/usr/bin/env bash
set -uo pipefail
uv run --with pytest pytest -q >/dev/null 2>&1 || { echo "FAIL: tests red"; exit 1; }
n=$(grep -c 'pct = (r\["cost"\] / total \* 100)' report.py)
[ "$n" -le 1 ] || { echo "FAIL: still duplicated ($n copies)"; exit 1; }
echo PASS
