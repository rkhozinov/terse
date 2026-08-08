#!/usr/bin/env python3
"""Output-style A/B: how many tokens does an answer cost, per arm.

Each cell is one headless `claude -p` call in an isolated sandbox whose only
difference from the other arms is the selected output style. Raw responses are
kept so scoring changes never re-spend on the API (`--rescore`, and judge.py).

  python run.py --canary        # prove style selection reaches the model. No corpus spend.
  python run.py --all --runs 3  # the real matrix (spends API)
  python run.py --rescore runs/<stamp>

Two things this harness is careful about, both learned the hard way elsewhere:

* `claude` in this user's shell is a zsh function that injects --remote-control
  and --permission-mode plan. We call the binary directly.
* `--setting-sources project` drops user scope, so the globally pinned
  outputStyle and every globally enabled plugin stay out of the comparison.
  The style files live in the sandbox's own .claude/output-styles/.
"""
import argparse, concurrent.futures, datetime, json, os, shutil, statistics, subprocess, sys
from collections import defaultdict
from pathlib import Path

from tasks import TASKS

HERE = Path(__file__).resolve().parent
STYLES = HERE / "styles"
SANDBOX = HERE / "sandbox"
RUNS_DIR = HERE / "runs"

# Arm -> style name (None = no outputStyle key at all, the control).
ARMS = {
    "default": None,
    "caveman-plugin": "caveman-plugin",
    "caveman-ultra": "caveman-ultra",
    "terse-v1": "terse-v1",
    "terse-v2": "terse-v2",
    "terse-v3": "terse-v3",
    "terse-v4": "terse-v4",
    "terse-v5": "terse-v5",
}

MODEL = "opus"
CELL_TIMEOUT = 240
CANARY_MARK = "ZZQ9"


def claude_bin():
    """The real binary, never the shell function (which injects flags of its own)."""
    env = os.environ.get("CLAUDE_BIN")
    if env:
        return env
    for p in (Path.home() / ".local/bin/claude", Path("/opt/homebrew/bin/claude")):
        if p.exists():
            return str(p)
    return shutil.which("claude") or sys.exit("claude CLI not found")


def setup_sandbox(extra_styles=()):
    """A cwd with its own project-scope .claude/ and nothing else: no CLAUDE.md,
    no hooks, no plugins. Rebuilt every run so a stale style can't leak in."""
    sd = SANDBOX / ".claude" / "output-styles"
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    sd.mkdir(parents=True)
    for f in STYLES.glob("*.md"):
        shutil.copy(f, sd / f.name)
    for name, text in extra_styles:
        (sd / f"{name}.md").write_text(text, encoding="utf-8")
    (SANDBOX / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    return SANDBOX


def call(prompt, style, out_path, timeout=CELL_TIMEOUT):
    """One headless call. stdout goes to a file, never a PIPE -- a hung child can
    hold a pipe open past the timeout and freeze the worker."""
    cmd = [claude_bin(), "-p", prompt,
           "--model", MODEL,
           "--output-format", "json",
           "--setting-sources", "project",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--tools", "",                       # prose only: no tool-use nondeterminism
           "--permission-mode", "bypassPermissions",
           "--no-session-persistence"]
    if style:
        cmd += ["--settings", json.dumps({"outputStyle": style})]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    err_path = out_path.with_suffix(".stderr.txt")
    try:
        with open(out_path, "wb") as so, open(err_path, "wb") as se:
            proc = subprocess.Popen(cmd, cwd=str(SANDBOX), stdout=so, stderr=se,
                                    start_new_session=True, env=env)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), 9)   # this cell's tree only
                try:
                    proc.wait(timeout=10)
                except Exception:
                    pass
                se.write(f"\n[KILLED after {timeout}s]".encode())
    except Exception as e:
        out_path.write_text(json.dumps({"error": str(e)[:300]}), encoding="utf-8")
    return read_result(out_path)


def read_result(p: Path):
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"unparseable result: {str(e)[:120]}", "text": ""}
    u = j.get("usage") or {}
    return {"text": j.get("result", "") or "",
            "out_tokens": u.get("output_tokens"),
            "in_tokens": u.get("input_tokens"),
            "cost": j.get("total_cost_usd"),
            "duration_ms": j.get("duration_ms"),
            "error": j.get("error") or (j.get("subtype") if j.get("is_error") else None)}


# --- canary: does style selection actually reach the model? -------------------

def canary():
    """Positive control per arm (style + a marker rule -> marker must appear) and a
    negative control (no style -> marker must not appear). If this fails, every
    number the matrix would produce is meaningless, so it runs before any spend."""
    extra = []
    for arm, style in ARMS.items():
        if not style:
            continue
        body = (STYLES / f"{style}.md").read_text(encoding="utf-8")
        # The style is selected by the frontmatter `name`, not the filename: a copy that
        # keeps the original name silently shadows the real style instead of adding one.
        marked = body.replace(f"name: {style}\n", f"name: {style}-canary\n", 1).rstrip()
        marked += f"\n\nBegin every single reply with the literal token {CANARY_MARK} and nothing before it.\n"
        extra.append((f"{style}-canary", marked))
    setup_sandbox(extra)
    d = RUNS_DIR / "canary"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    ok = True
    checks = [(arm, f"{style}-canary", True) for arm, style in ARMS.items() if style]
    checks.append(("default", None, False))
    for arm, style, expect in checks:
        r = call("Say hello.", style, d / f"{arm}.json", timeout=120)
        got = CANARY_MARK in (r["text"] or "")
        good = got == expect
        ok &= good
        print(f"{'ok ' if good else 'XX '} {arm:15} style={style or '(none)':22} "
              f"marker={'present' if got else 'absent':7} expected={'present' if expect else 'absent'}"
              f"{'  ERR=' + str(r['error']) if r.get('error') else ''}")
    print(f"\ncanary: {'style selection verified' if ok else 'STYLE SELECTION BROKEN -- do not run the matrix'}")
    return 0 if ok else 1


# --- matrix ------------------------------------------------------------------

def text_tokens(text):
    """Tokens of the VISIBLE answer. `usage.output_tokens` also counts thinking, which
    the reader never sees -- billing cares about it, cognitive load does not. tiktoken's
    o200k_base is not Claude's tokenizer, so treat these as comparable, not absolute."""
    try:
        import tiktoken
        return len(tiktoken.get_encoding("o200k_base").encode(text or ""))
    except Exception:
        return round(len(text or "") / 4)


def cell_dir(out_dir, tid, arm, rep):
    d = out_dir / f"{tid}__{arm}__{rep}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_cell(tid, arm, rep, out_dir):
    d = cell_dir(out_dir, tid, arm, rep)
    r = call(TASKS[tid]["prompt"], ARMS[arm], d / "_claude.json")
    rec = {"task": tid, "class": TASKS[tid]["class"], "arm": arm, "rep": rep,
           "chars": len(r["text"]), "text_tokens": text_tokens(r["text"]),
           "lines": len([l for l in r["text"].splitlines() if l.strip()]),
           **{k: v for k, v in r.items() if k != "text"}}
    (d / "answer.md").write_text(r["text"], encoding="utf-8")
    (d / "metrics.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def collect(run_dir: Path):
    """Read kept cells, backfilling visible-answer token counts (added after the first run)."""
    out = []
    for d in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        f, a = d / "metrics.json", d / "answer.md"
        if not f.exists():
            continue
        rec = json.loads(f.read_text(encoding="utf-8"))
        if "text_tokens" not in rec and a.exists():
            rec["text_tokens"] = text_tokens(a.read_text(encoding="utf-8"))
            f.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        out.append(rec)
    return out


def aggregate(results):
    by = defaultdict(list)
    for r in results:
        if r.get("out_tokens"):
            by[(r["task"], r["arm"])].append(r)
    rows = []
    for (t, a), cells in sorted(by.items()):
        tok = [c["out_tokens"] for c in cells]
        vis = [c.get("text_tokens") or text_tokens("") for c in cells]
        rows.append({"task": t, "arm": a, "n": len(cells),
                     "text_tokens_mean": round(statistics.mean(vis), 1),
                     "text_tokens_sd": round(statistics.stdev(vis), 1) if len(vis) > 1 else 0.0,
                     "out_tokens_mean": round(statistics.mean(tok), 1),
                     "out_tokens_sd": round(statistics.stdev(tok), 1) if len(tok) > 1 else 0.0,
                     "chars_mean": round(statistics.mean([c["chars"] for c in cells]), 1),
                     "lines_mean": round(statistics.mean([c["lines"] for c in cells]), 1),
                     "cost_mean": round(statistics.mean([c["cost"] for c in cells if c.get("cost")]), 4)
                                   if any(c.get("cost") for c in cells) else None,
                     "time_s_mean": round(statistics.mean([c["duration_ms"] / 1000 for c in cells
                                                           if c.get("duration_ms")]), 1)
                                     if any(c.get("duration_ms") for c in cells) else None})
    return rows


def print_table(rows):
    """Two token columns on purpose: `read` is what the human pays attention for,
    `billed` also carries thinking tokens the reader never sees."""
    base = {r["task"]: r["text_tokens_mean"] for r in rows if r["arm"] == "default"}
    by_task = defaultdict(list)
    for r in rows:
        by_task[r["task"]].append(r)
    print(f"\n{'task':15} {'arm':15} {'n':>2} {'read_tok':>9} {'±sd':>7} {'vs default':>11} "
          f"{'billed_tok':>11} {'lines':>6} {'$/run':>8}")
    for t, rs in sorted(by_task.items()):
        for r in sorted(rs, key=lambda x: list(ARMS).index(x["arm"])):
            b = base.get(t)
            ratio = f"{r['text_tokens_mean'] / b:.2f}x" if b else "-"
            cost = f"${r['cost_mean']:.4f}" if r["cost_mean"] is not None else "-"
            print(f"{t:15} {r['arm']:15} {r['n']:>2} {r['text_tokens_mean']:>9} {r['text_tokens_sd']:>7} "
                  f"{ratio:>11} {r['out_tokens_mean']:>11} {r['lines_mean']:>6} {cost:>8}")
    print(f"\n{'OVERALL':15} {'arm':15} {'cells':>5} {'read_tok mean':>14} {'geo ratio vs default':>21}")
    for arm in ARMS:
        rs = [r for r in rows if r["arm"] == arm]
        if not rs:
            continue
        ratios = [r["text_tokens_mean"] / base[r["task"]] for r in rs if base.get(r["task"])]
        geo = (statistics.geometric_mean(ratios) if ratios else 0)
        print(f"{'':15} {arm:15} {sum(r['n'] for r in rs):>5} "
              f"{round(statistics.mean([r['text_tokens_mean'] for r in rs]), 1):>14} {geo:>20.2f}x")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--canary", action="store_true")
    ap.add_argument("--rescore", help="re-aggregate a kept run dir (no API)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--task", help="comma list of task ids")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    if args.canary:
        sys.exit(canary())
    if args.rescore:
        d = Path(args.rescore)
        if not d.exists():
            d = RUNS_DIR / d.name
        rows = aggregate(collect(d))
        (d / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print_table(rows)
        return

    tids = list(TASKS) if args.all else [t.strip() for t in (args.task or "").split(",") if t.strip()]
    if not tids:
        sys.exit("give --all, --task <ids>, --canary or --rescore <dir>")
    arms = [a.strip() for a in args.arms.split(",")]
    setup_sandbox()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = RUNS_DIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    cells = [(t, a, r) for t in tids for a in arms for r in range(args.runs)]
    print(f"{len(cells)} cells, {args.workers} at a time -> {out_dir}", flush=True)
    results, done = [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_cell, t, a, r, out_dir): (t, a, r) for t, a, r in cells}
        for fut in concurrent.futures.as_completed(futs):
            t, a, r = futs[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = {"task": t, "arm": a, "rep": r, "error": str(e)[:200]}
            results.append(rec)
            done += 1
            print(f"  [{done}/{len(cells)}] {t:15} {a:15} #{r} tok={rec.get('out_tokens')} "
                  f"chars={rec.get('chars')} ${rec.get('cost')}"
                  f"{'  ERR=' + str(rec['error']) if rec.get('error') else ''}", flush=True)
            (out_dir / "results.json").write_text(json.dumps(
                {"date": stamp, "model": MODEL, "arms": ARMS, "results": results}, indent=2), encoding="utf-8")

    rows = aggregate(results)
    (out_dir / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print_table(rows)
    print(f"\nwrote {out_dir}")


if __name__ == "__main__":
    main()
