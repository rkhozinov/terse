# terse

Ultra-terse output styles for Claude Code, plus the benchmark that picked them.

An output style sits in the system prompt, so it costs nothing per turn once
cached and outranks anything a plugin appends later. Claude Code will not load
one from a plugin directory though — it only reads
`$CLAUDE_CONFIG_DIR/output-styles/`. So this plugin carries the styles as payload
and installs them.

## Install

```sh
claude /plugin marketplace add github:rkhozinov/claude-marketplace
claude /plugin install terse@rkhozinov
```

Then, in a session:

```
/terse-install                 # installs terse-lazy and activates it
```

or directly:

```sh
bash ~/.claude/plugins/cache/rkhozinov/terse/*/skills/terse-install/install.sh --list
```

The style applies from the **next** session onward.

## Styles

| Style | Contents |
|---|---|
| `terse` | Compression only: answer first, no narration, tables over prose, no hedging, identifiers never blurred — and completeness protected (cut words, never items). |
| `terse-lazy` | `terse` + a "build lazy" block (YAGNI, stdlib before deps, shortest working diff). Default. |

## Results

180 cells: 10 self-contained prompts x 6 arms x 3 repeats on `opus`, judged by
`sonnet` against a rubric built from the union of all arms' answers.

| arm | read tok | vs default | retention | critical retention | points / 1k read tok |
|---|---|---|---|---|---|
| default (no style) | 664 | 1.00x | 75.0% | 85.7% | 25.1 |
| caveman plugin, ultra | 530 | 0.80x | 74.6% | 80.9% | 30.2 |
| caveman-ultra | 578 | 0.92x | 75.3% | 84.8% | 24.3 |
| terse-v1 | 378 | 0.61x | 65.7% | 76.6% | 32.7 |
| **terse (v2, shipped)** | **492** | **0.78x** | **74.5%** | **84.2%** | **31.5** |
| terse-v3 | 545 | 0.86x | 73.2% | 81.2% | 26.4 |

`terse` reads at 0.78x the default for the same content. `terse-v1` compresses
harder but drops items — 65.7% retention is content loss, not brevity, and it is
why the shipped style says *cut words, never items*.

The full report — per-prompt numbers, every judge-flagged quality issue, and the
verdict with its caveats — is generated locally and not tracked here, because it
quotes the answers verbatim:

```sh
cd bench && uv run --with tiktoken python report.py runs/<stamp>
```

## Benchmark

```sh
cd bench
uv run --with tiktoken python run.py --canary        # prove style selection reaches the model
uv run --with tiktoken python run.py --all --runs 3  # the matrix (spends API)
uv run --with tiktoken python judge.py --run runs/<stamp>
uv run --with tiktoken python run.py --rescore runs/<stamp>   # re-aggregate, no API
```

Design notes, because the easy version of this benchmark is wrong:

- **Tokens alone cannot pick a winner** — an empty answer wins on tokens. Every
  answer is scored against a rubric of decision-relevant claims, and the rubric
  is the union of what *all* arms said, not what the verbose control said.
- **Two token columns.** `read_tok` counts the visible answer (what a human pays
  attention for); `billed_tok` is the API's `output_tokens`, which also counts
  thinking the reader never sees.
- **Arm isolation** via `--setting-sources project` and a throwaway sandbox cwd,
  so the machine's own global style, plugins and CLAUDE.md stay out of it.
- **The canary gate runs first.** A style that silently fails to load produces a
  clean-looking benchmark of nothing. Positive control per arm (marker rule must
  appear) and a negative control (no style → no marker).
- Styles are selected by the frontmatter `name:`, not the filename. Two files
  declaring the same name shadow each other — that bug ate the first canary run.
- `terse-lazy` sets `keep-coding-instructions: true`. Without it an output style
  *replaces* Claude Code's built-in software-engineering prompt, which is where
  the standing "always track work in the task list" directive lives — so the
  session-scoped task list stops being maintained unless you ask for it. Plain
  `terse` leaves the default (`false`) and drops those instructions.
