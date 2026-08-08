## Verdict — round 2 (2026-08-07, runs `20260807-194955` and `20260807-201114`)

**Ship `terse-v4`.** It reads at 0.75–0.76x the default across two independent
runs, holds retention and critical retention at or above the unstyled control in
both, and carries 44.9 decision-relevant points per 1k tokens against v2's 36.6 —
the highest of anything measured here.

The change over v2 is one rule: split prompts into *determinate* (lookup, yes/no,
status roll-up, summarise) and *analysis* (diagnose, review, plan, compare,
decide, risk), and let only analysis answers run the "check for anything you did
not say" sweep. v2's four dead classes were dead because that sweep appended a
risk list to answers that had no risks: `summarize` measured 1.20x and
`underspecified` 1.25x — *longer* than no style at all. Both are now at or under
1.0x, and `quickfact` roughly halved.

**`terse-v5` was rejected, and the reason matters more than the result.** v5 moved
`explain` to the analysis side to repair what looked like a 15-point critical
retention regression in v4 (94% → 79%). Re-running v4 unchanged scored the same
class at 92%. The regression was noise; v5 was built on it, cost 16% more tokens
(0.82x vs 0.76x), and did not change `explain`'s length at all (711 vs 710
tokens). Widening "analysis" instead leaked into six other classes — `runbook`
0.75x → 1.02x, `diagnose` 0.71x → 0.96x, `underspecified` 0.86x → 1.02x.

**Per-class numbers at n=3 are not decision-grade. Arm-level ones are.** Between
two runs of the *identical* v4 style on the *identical* prompts: `explain`
0.56x → 0.76x, `review-diff` 0.91x → 0.64x, `quickfact` 0.41x → 0.94x, and
arm-level retention 80.2% → 75.7%. Meanwhile the unstyled control reproduced at
73.5% both times and arm-level token ratio moved 0.75x → 0.76x. Treat any
single-run per-class gap under ~5 points as unresolved, and re-run before
designing a fix around one — the v5 detour is what that mistake costs.

**Carried over unchanged:** every compressed arm still shows more judge-flagged
distortions than the control (default 8–12; v4 16–18), mostly checkable claims
asserted without a hedge rather than factual errors about the input.

**Not measured:** the shipped `terse-lazy` sets `keep-coding-instructions: true`,
which re-adds Claude Code's built-in software-engineering prompt. No bench arm
carries that flag, so live `terse-lazy` output will run somewhat longer than the
0.75x measured here. `terse` has no such gap.

## Verdict — round 1

**Ship `terse-v2`.** It reads at 0.78x the default's tokens while holding content
essentially level with it — 74.5% vs 75.0% rubric retention, 84.2% vs 85.7% on the
points the judge marked critical — and carries 26% more decision-relevant content
per token read than any other arm that keeps its content intact.

**The style in use until now (`caveman-ultra`) was buying almost nothing: 0.92x.**
It is *worse* than the original caveman plugin's ultra ruleset (0.80x) it replaced,
and on three prompt classes — quick fact, risk, summarise — it produced answers
*longer* than the unstyled control while holding the same content. The earlier
n=1 byte-count A/B that justified the switch measured one long answer and
generalised from it.

**`terse-v1` is the cautionary result.** It compresses hardest (0.61x) and has the
highest raw density, but it hits those numbers by dropping items: retention falls
to 65.7% and critical retention to 76.6%, worst on `diagnose` (-29 points vs
default) and `review-diff` (-21). Those are exactly the prompts where a real answer
is a list of findings and a length cap prunes the tail. Its 131 dropped caveats
against the default's 98 is the same failure counted another way. Compression that
throws away the fifth finding is not compression.

The fix that produced v2 was one rule — *cut words, never items*, plus an explicit
"targets are for words, not items" clause and a final sweep for unstated risks.
That recovered the content at a cost of 0.17x in tokens.

**`terse-v3` was rejected.** It added epistemic labelling (`Unverified:` on
anything not checkable from the prompt) to attack the one axis where every
compressed arm is worse than the control: unhedged assertion of checkable claims.
It cost 11% more tokens than v2 (0.86x vs 0.78x), lost retention rather than
gaining it, and moved distortions from 21 to 16 — a difference well inside the
noise at n=30 per arm, where per-task counts swing by more than that. It did not
earn its tokens.

**Known weakness, stated rather than smoothed over.** Every compressed arm shows
more judge-flagged distortions than the unstyled control (default 9; caveman-ultra
10; terse-v3 16; terse-v1 18; caveman-plugin 19; terse-v2 21). Reading the flags,
most are not factual errors about the input but *checkable claims asserted without
a hedge* — a direct consequence of the no-hedging rule. v3 shows that simply
telling the model to label uncertainty does not fix it cheaply. Treat confident
claims about vendor behaviour and version-specific flags as unverified regardless
of the style.

**Caveats on the numbers.** n=3 per (prompt, arm): the arm-level ratios are stable
across 10 prompts, the per-prompt numbers are not. Retention is scored by an LLM
judge against a rubric it also wrote — validated to separate a correct answer from
a plausible wrong one, but it is not a human. Absolute retention hovering at ~75%
for every arm including the control reflects a deliberately demanding union
rubric, not four broken styles; only the differences between arms are meaningful.
