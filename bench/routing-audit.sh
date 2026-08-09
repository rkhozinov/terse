#!/usr/bin/env bash
# Which agent types and models are actually being spawned?
#
# The routing policy lives in CLAUDE.md, which is advisory. This counts what
# really happened, so "did the policy change behaviour" is a measurement rather
# than a guess. Baseline taken 2026-08-09, before scout/builder/investigator
# existed: 49 spawns over 2 days — general-purpose 31, Explore 11, fork 7, with
# 22 omitting `model` entirely and therefore inheriting opus.
#
# Usage: ./routing-audit.sh [YYYY-MM-DD]   (default: 7 days ago)
set -uo pipefail

SINCE="${1:-$(date -v-7d +%Y-%m-%d 2>/dev/null || date -d '7 days ago' +%Y-%m-%d)}"
PROJECTS="$HOME/.claude/projects"

[ -d "$PROJECTS" ] || { echo "no transcripts at $PROJECTS"; exit 1; }

# Custom agents carry `model:` in their own frontmatter, so a spawn with no
# `model` on the call is NOT inheriting opus — it is using the pinned one.
# Counting those as inherited was the first version's bug and it flattered the
# result: every scout call looked like an opus call.
spawns() {
  find "$PROJECTS" -name "*.jsonl" -newermt "$SINCE" 2>/dev/null | while read -r f; do
    jq -r 'select(.message.content?) | .message.content[]?
           | select(.type=="tool_use" and .name=="Agent")
           | (.input.subagent_type // "(omitted)") as $t
           | {scout: "haiku", builder: "sonnet", investigator: "opus"}[$t] as $pinned
           | [$t, (.input.model // $pinned // "(inherit=opus)")]
           | @tsv' "$f" 2>/dev/null
  done
}

all=$(spawns)
total=$(printf '%s\n' "$all" | grep -c . || true)

echo "since $SINCE — $total spawns"
echo
echo "by agent type:"
printf '%s\n' "$all" | awk -F'\t' 'NF{print $1}' | sort | uniq -c | sort -rn | sed 's/^/  /'
echo
echo "by model:"
printf '%s\n' "$all" | awk -F'\t' 'NF{print $2}' | sort | uniq -c | sort -rn | sed 's/^/  /'
echo
# The single number worth watching: opus-by-default is the leak the agent
# definitions exist to close, since each cheap-shaped task run on opus costs
# roughly 6x what it should.
inherit=$(printf '%s\n' "$all" | grep -c '(inherit=opus)' || true)
[ "$total" -gt 0 ] && echo "inheriting opus: $inherit/$total ($((inherit * 100 / total))%) — was 22/49 (44%) at baseline"
