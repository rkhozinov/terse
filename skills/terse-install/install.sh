#!/usr/bin/env bash
# Install and activate a terse output style.
#
# Output styles are not loadable from a plugin directory, so this copies the
# style into the config dir Claude Code actually reads and sets the settings key.
#
#   install.sh                 # install + activate the default style (terse-lazy)
#   install.sh terse           # compression rules only, no engineering-discipline block
#   install.sh --list          # show what this plugin ships
#   install.sh --no-activate X # copy it, leave the active style alone
set -euo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SRC_DIR="$ROOT/output-styles"
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
DEST_DIR="$CFG/output-styles"
ACTIVATE=1

command -v jq >/dev/null || { echo "jq is required (brew install jq)"; exit 1; }

case "${1:-}" in
  --list)
    echo "styles in $SRC_DIR:"
    for f in "$SRC_DIR"/*.md; do
      printf '  %-14s %s\n' "$(basename "$f" .md)" "$(sed -n 's/^description: //p' "$f" | head -1)"
    done
    exit 0
    ;;
  --no-activate) ACTIVATE=0; shift ;;
esac

STYLE="${1:-terse-lazy}"
SRC="$SRC_DIR/$STYLE.md"
[ -f "$SRC" ] || { echo "no such style: $STYLE (try --list)"; exit 1; }

mkdir -p "$DEST_DIR"
cp "$SRC" "$DEST_DIR/$STYLE.md"
echo "installed $DEST_DIR/$STYLE.md"

if [ "$ACTIVATE" = 1 ]; then
  SETTINGS="$CFG/settings.json"
  [ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
  tmp="$(mktemp)"
  jq --arg s "$STYLE" '.outputStyle = $s' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
  echo "activated: outputStyle=$STYLE in $SETTINGS"
fi

# Project-local settings outrank user settings. A stale key here silently defeats
# the style for that repo, which is the failure mode people spend a session chasing.
for f in .claude/settings.json .claude/settings.local.json; do
  if [ -f "$f" ] && jq -e 'has("outputStyle")' "$f" >/dev/null 2>&1; then
    echo "WARNING: $f pins outputStyle=$(jq -r .outputStyle "$f") and outranks the user setting."
    echo "         Remove it there:  jq 'del(.outputStyle)' $f > tmp && mv tmp $f"
  fi
done

echo "verify: start a new session and run /output-style — $STYLE should be selected."
