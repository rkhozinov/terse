#!/usr/bin/env python3
"""Render a judged run into RESULTS.md + report.html (self-contained, no JS deps).

  python report.py runs/<stamp> [--out ../bench/RESULTS.md]
"""
import argparse, json, re, statistics
from collections import defaultdict
from pathlib import Path

from run import ARMS, RUNS_DIR, collect, aggregate

HERE = Path(__file__).resolve().parent
from tasks import TASKS

ARM_ORDER = list(ARMS)


def gather(run_dir: Path):
    rows = aggregate(collect(run_dir))
    scores = {}
    sp = run_dir / "scores.json"
    if sp.exists():
        scores = json.loads(sp.read_text(encoding="utf-8"))
    return rows, scores


def arm_summary(rows, scores):
    base = {r["task"]: r["text_tokens_mean"] for r in rows if r["arm"] == "default"}
    by_arm_scores = defaultdict(list)
    for s in scores.values():
        by_arm_scores[s["arm"]].append(s)
    out = []
    for arm in ARM_ORDER:
        rs = [r for r in rows if r["arm"] == arm]
        if not rs:
            continue
        ratios = [r["text_tokens_mean"] / base[r["task"]] for r in rs if base.get(r["task"])]
        ss = by_arm_scores.get(arm, [])
        n = len(ss) or 1
        ret = sum(len(s["covered"]) / max(s["n_points"], 1) for s in ss) / n if ss else None
        cret = (sum((s["critical_covered"] / s["n_critical"]) if s["n_critical"] else 1.0 for s in ss) / n
                if ss else None)
        tok = [s.get("text_tokens") for s in ss if s.get("text_tokens")]
        dens = (sum(len(s["covered"]) / (s["text_tokens"] / 1000) for s in ss if s.get("text_tokens"))
                / len(tok)) if tok else None
        out.append({
            "arm": arm,
            "cells": sum(r["n"] for r in rs),
            "read_tok": round(statistics.mean([r["text_tokens_mean"] for r in rs]), 1),
            "billed_tok": round(statistics.mean([r["out_tokens_mean"] for r in rs]), 1),
            "ratio": round(statistics.geometric_mean(ratios), 3) if ratios else None,
            "cost": round(statistics.mean([r["cost_mean"] for r in rs if r["cost_mean"]]), 4),
            "retention": round(ret, 4) if ret is not None else None,
            "critical_retention": round(cret, 4) if cret is not None else None,
            "density": round(dens, 2) if dens is not None else None,
            "distortions": sum(len(s["distortions"]) for s in ss),
            "dropped_caveats": sum(len(s["dropped_caveats"]) for s in ss),
            "ambiguities": sum(len(s["ambiguities"]) for s in ss),
        })
    return out


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def build(run_dir: Path):
    rows, scores = gather(run_dir)
    summ = arm_summary(rows, scores)
    base = {r["task"]: r["text_tokens_mean"] for r in rows if r["arm"] == "default"}

    parts = [f"# Output-style benchmark — {run_dir.name}", ""]
    verdict = HERE / "VERDICT.md"
    if verdict.exists():                      # hand-written conclusion, kept out of the generator
        parts += [verdict.read_text(encoding="utf-8").strip(), ""]
    parts.append(f"{sum(s['cells'] for s in summ)} cells: {len(TASKS)} prompts x {len(ARM_ORDER)} arms x "
                 f"{max(r['n'] for r in rows)} repeats, model `opus`, judged by `sonnet` on a rubric built "
                 f"from the union of all arms' answers.")
    parts += ["", "## Per arm", ""]
    parts.append(md_table(
        ["arm", "read tok", "vs default", "billed tok", "$/answer", "retention", "critical retention",
         "points/1k read tok", "distortions", "dropped caveats", "ambiguities"],
        [[s["arm"], s["read_tok"], f"{s['ratio']:.2f}x" if s["ratio"] else "-", s["billed_tok"],
          f"${s['cost']:.4f}", f"{s['retention']:.1%}" if s["retention"] is not None else "-",
          f"{s['critical_retention']:.1%}" if s["critical_retention"] is not None else "-",
          s["density"], s["distortions"], s["dropped_caveats"], s["ambiguities"]] for s in summ]))

    parts += ["", "## Per prompt (read tokens, mean of repeats)", ""]
    tasks = sorted({r["task"] for r in rows})
    hdr = ["prompt", "class"] + ARM_ORDER
    trows = []
    for t in tasks:
        row = [t, TASKS[t]["class"]]
        for a in ARM_ORDER:
            m = next((r for r in rows if r["task"] == t and r["arm"] == a), None)
            if not m:
                row.append("-")
                continue
            ratio = f" ({m['text_tokens_mean'] / base[t]:.2f}x)" if base.get(t) and a != "default" else ""
            row.append(f"{m['text_tokens_mean']:.0f} ±{m['text_tokens_sd']:.0f}{ratio}")
        trows.append(row)
    parts.append(md_table(hdr, trows))

    flags = [(k, s) for k, s in scores.items()
             if s["distortions"] or s["dropped_caveats"] or s["ambiguities"]]
    parts += ["", f"## Quality flags ({len(flags)} of {len(scores)} answers)", ""]
    if flags:
        frows = []
        for k, s in sorted(flags, key=lambda kv: (kv[1]["arm"], kv[1]["task"])):
            for kind in ("distortions", "dropped_caveats", "ambiguities"):
                for item in s[kind]:
                    frows.append([s["arm"], s["task"], kind[:-1], str(item)[:160].replace("|", "/")])
        parts.append(md_table(["arm", "prompt", "kind", "what"], frows))
    else:
        parts.append("None.")
    return "\n".join(parts) + "\n"


HTML_HEAD = """<!doctype html><meta charset="utf-8"><title>Output-style benchmark</title>
<style>
 body{font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:1100px;
      margin:2rem auto;padding:0 1rem;color:#111}
 h1{font-size:1.5rem} h2{font-size:1.1rem;margin-top:2rem;border-bottom:1px solid #ddd;padding-bottom:.2rem}
 table{border-collapse:collapse;width:100%;margin:.6rem 0;font-size:13px}
 th,td{border:1px solid #ddd;padding:.35rem .5rem;text-align:left;vertical-align:top}
 th{background:#f6f6f6} tr:nth-child(even) td{background:#fbfbfb}
 code{background:#f2f2f2;padding:0 .2rem;border-radius:3px}
</style>
"""


def md_to_html(md):
    """Minimal renderer: headings, pipe tables, paragraphs, inline code. No dependencies."""
    html, in_tbl = [], False
    for line in md.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            tag = "th" if not in_tbl else "td"
            if not in_tbl:
                html.append("<table>")
                in_tbl = True
            html.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_tbl:
            html.append("</table>")
            in_tbl = False
        if line.startswith("## "):
            html.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            html.append(f"<h1>{line[2:]}</h1>")
        elif line.strip():
            html.append(f"<p>{line}</p>")
    if in_tbl:
        html.append("</table>")
    body = re.sub(r"`([^`]+)`", r"<code>\1</code>", "\n".join(html))
    return HTML_HEAD + body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--out", default=None, help="markdown path (default <run_dir>/RESULTS.md)")
    args = ap.parse_args()
    d = Path(args.run_dir)
    if not d.exists():
        d = RUNS_DIR / d.name
    md = build(d)
    out_md = Path(args.out) if args.out else d / "RESULTS.md"
    out_md.write_text(md, encoding="utf-8")
    out_html = out_md.with_suffix(".html")
    out_html.write_text(md_to_html(md), encoding="utf-8")
    print(f"wrote {out_md}\nwrote {out_html}")


if __name__ == "__main__":
    main()
