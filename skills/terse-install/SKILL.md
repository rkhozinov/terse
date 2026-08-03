---
name: terse-install
description: Install and activate a terse output style (terse, terse-lazy) into this machine's Claude Code config, or switch between them. Use when the user wants shorter, denser answers everywhere, asks to install/activate/switch the terse or caveman style, or asks why an installed output style is not taking effect.
---

# terse-install

Output styles cannot be loaded straight from a plugin directory — Claude Code
only reads `$CLAUDE_CONFIG_DIR/output-styles/` (default `~/.claude/output-styles/`).
This skill copies the style there and sets the `outputStyle` settings key.

## Install

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/terse-install/install.sh"            # terse-lazy (default)
bash "${CLAUDE_PLUGIN_ROOT}/skills/terse-install/install.sh" terse      # compression rules only
bash "${CLAUDE_PLUGIN_ROOT}/skills/terse-install/install.sh" --list     # what ships here
```

The change takes effect in the **next** session — the style is part of the
system prompt, so the current one keeps whatever it started with.

## Which style

| Style | Contents |
|---|---|
| `terse` | Compression rules only: answer first, no narration, length caps, tables over prose, no hedging. |
| `terse-lazy` | `terse` plus a "build lazy" block (YAGNI, stdlib before deps, shortest working diff). Default. |

Pick `terse` if the engineering-discipline rules are already covered elsewhere
(a CLAUDE.md, a skill); it is the smaller system prompt.

## When it appears not to work

Check in this order — the first one is the usual culprit:

1. **Project settings outrank user settings.** `./.claude/settings.json` or
   `./.claude/settings.local.json` carrying its own `outputStyle` wins over
   `~/.claude/settings.json`. `install.sh` warns when it sees one.
2. Wrong config dir: `CLAUDE_CONFIG_DIR` set in the shell that started Claude.
3. The style's frontmatter `name:` must match the value in `outputStyle` —
   selection is by that name, not by filename. Two files declaring the same
   name shadow each other.
4. Still in the session that predates the install. Start a new one.

## Uninstall

```bash
jq 'del(.outputStyle)' ~/.claude/settings.json > /tmp/s && mv /tmp/s ~/.claude/settings.json
```
