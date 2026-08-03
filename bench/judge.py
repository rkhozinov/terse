#!/usr/bin/env python3
"""Did the compression drop anything that mattered?

Tokens alone can't pick a winner -- an empty answer wins on tokens. So every
answer is scored against a rubric of decision-relevant claims, and the rubric is
built from the UNION of what all arms said for that task, never from the verbose
control alone (that would score verbosity as correctness).

  python judge.py --selftest            # the judge must separate a good answer from a bad one
  python judge.py --run runs/<stamp>    # rubric + score every kept answer

The judge sees answers stripped of any arm label, one at a time, in random-ish
order of iteration -- it cannot tell which style produced what.
"""
import argparse, concurrent.futures, json, os, random, re, subprocess, sys
from collections import defaultdict
from pathlib import Path

from tasks import TASKS
from run import claude_bin, RUNS_DIR, collect

HERE = Path(__file__).resolve().parent
JUDGE_DIR = HERE / "judge-sandbox"
JUDGE_MODEL = "sonnet"
WORKERS = 10

RUBRIC_SCHEMA = {
    "type": "object",
    "properties": {
        "points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "claim": {"type": "string"},
                    "critical": {"type": "boolean"},
                },
                "required": ["id", "claim", "critical"],
            },
        }
    },
    "required": ["points"],
}

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "covered": {"type": "array", "items": {"type": "integer"}},
        "distortions": {"type": "array", "items": {"type": "string"}},
        "dropped_caveats": {"type": "array", "items": {"type": "string"}},
        "ambiguities": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["covered", "distortions", "dropped_caveats", "ambiguities"],
}

RUBRIC_PROMPT = """You are building a scoring rubric for answers to one question.

QUESTION:
{question}

Here are {n} independent answers to it, from different assistants:

{answers}

Extract the DECISION-RELEVANT claims: the things a reader must be told for the answer to be
useful and safe to act on. One atomic claim per point, in your own words, phrased so it can be
checked as present/absent in an answer. Merge duplicates across answers. Ignore differences of
tone, ordering, formatting and verbosity -- rubric points are about content only. Ignore filler,
restatements of the question, and offers of further help.

Mark a point critical=true only if omitting it would lead the reader to a wrong or unsafe action
(a data-loss risk, a security exposure, an ordering constraint, a blocking dependency, a required
clarifying question). Everything else is critical=false.

Produce at most 14 points. Reply with JSON only."""

SCORE_PROMPT = """Score one answer against a fixed rubric.

QUESTION:
{question}

RUBRIC POINTS:
{points}

ANSWER:
---
{answer}
---

Report:
- covered: ids of rubric points the answer actually conveys. Terse phrasing, fragments,
  abbreviations, arrows and tables all count as conveying the point -- judge content, not style.
  A point is covered only if a reader would come away knowing it, not merely if a related word appears.
- distortions: statements in the answer that are wrong, or that misstate an identifier, number,
  path, flag or error string. Quote each briefly.
- dropped_caveats: risks or conditions the answer needed to state and did not, such that acting on
  the answer could cause harm or rework.
- ambiguities: places where compression made the answer genuinely misreadable (an ordering that
  could be reversed, a pronoun with no referent, a fragment with two readings). Not mere brevity.

Empty arrays where nothing applies. Reply with JSON only."""


def ask(prompt, schema, timeout=180):
    """One judge call: fixed model, structured output, no styles, no tools."""
    JUDGE_DIR.mkdir(exist_ok=True)
    (JUDGE_DIR / ".claude").mkdir(exist_ok=True)
    (JUDGE_DIR / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    cmd = [claude_bin(), "-p", prompt, "--model", JUDGE_MODEL,
           "--output-format", "json", "--json-schema", json.dumps(schema),
           "--setting-sources", "project", "--strict-mcp-config",
           "--mcp-config", '{"mcpServers":{}}', "--tools", "",
           "--permission-mode", "bypassPermissions", "--no-session-persistence"]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        p = subprocess.run(cmd, cwd=str(JUDGE_DIR), capture_output=True, text=True,
                           timeout=timeout, env=env)
        j = json.loads(p.stdout)
        txt = j.get("result", "")
    except Exception as e:
        return {"error": str(e)[:200]}
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt or "", re.S)
        if not m:
            return {"error": "unparseable judge reply"}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {"error": "unparseable judge reply"}


def fmt_points(points):
    return "\n".join(f"{p['id']}. [{'critical' if p.get('critical') else 'normal'}] {p['claim']}"
                     for p in points)


def build_rubric(tid, answers):
    blob = "\n\n".join(f"--- answer {i + 1} ---\n{a}" for i, a in enumerate(answers))
    r = ask(RUBRIC_PROMPT.format(question=TASKS[tid]["prompt"], n=len(answers), answers=blob),
            RUBRIC_SCHEMA, timeout=300)
    return r.get("points") or []


def score_answer(tid, points, answer):
    return ask(SCORE_PROMPT.format(question=TASKS[tid]["prompt"],
                                   points=fmt_points(points), answer=answer), SCORE_SCHEMA)


# --- selftest ----------------------------------------------------------------

GOOD = """Missing key `OIDC_CLIENT_SECRET` in secret `auth-service-prod` (namespace auth).
App loads 14 keys, validates, dies: `config validation failed: required key OIDC_CLIENT_SECRET missing`.
Image `prod-20260802-49a152c` expects a key the secret does not carry -> CrashLoopBackOff.

Fix: add OIDC_CLIENT_SECRET to the AWS Secrets Manager secret backing it, let the external-secrets
sync land, then restart the deployment. Value comes from the OIDC provider's client credentials --
rotate it there if nobody has the current one."""

BAD = """Pod cannot reach Postgres at auth-prod.cluster-abc.us-east-2.rds.amazonaws.com, so it
crashes on boot. The RDS security group is blocking port 5432 from the node subnet.

Fix: open 5432 in the DB security group and the pod will start."""


def selftest():
    tid = "diagnose"
    points = build_rubric(tid, [GOOD, BAD])
    if not points:
        print("XX rubric build failed")
        return 1
    print(f"  rubric: {len(points)} points ({sum(1 for p in points if p.get('critical'))} critical)")
    g, b = score_answer(tid, points, GOOD), score_answer(tid, points, BAD)
    if "error" in g or "error" in b:
        print(f"XX scoring failed: {g.get('error') or b.get('error')}")
        return 1
    gc, bc = len(g["covered"]), len(b["covered"])
    ok_cov = gc > bc
    ok_dist = len(b["distortions"]) > len(g["distortions"])
    print(f"{'ok ' if ok_cov else 'XX '} coverage    good={gc}/{len(points)}  bad={bc}/{len(points)}")
    print(f"{'ok ' if ok_dist else 'XX '} distortions good={len(g['distortions'])}  bad={len(b['distortions'])}"
          f"  e.g. {(b['distortions'] or ['-'])[0][:90]}")
    ok = ok_cov and ok_dist
    print(f"\njudge selftest: {'valid' if ok else 'NOT TRUSTWORTHY'}")
    return 0 if ok else 1


# --- run ---------------------------------------------------------------------

def run(run_dir):
    run_dir = Path(run_dir)
    if not run_dir.exists():
        run_dir = RUNS_DIR / run_dir.name
    cells = []
    for d in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        a = d / "answer.md"
        m = d / "metrics.json"
        if a.exists() and m.exists():
            met = json.loads(m.read_text(encoding="utf-8"))
            cells.append({**met, "dir": d, "answer": a.read_text(encoding="utf-8")})
    by_task = defaultdict(list)
    for c in cells:
        by_task[c["task"]].append(c)

    # Judge calls are independent, so they run concurrently: serially this pass took
    # minutes per rubric and would have outlasted the matrix that produced it.
    rubrics_path = run_dir / "rubrics.json"
    rubrics = json.loads(rubrics_path.read_text(encoding="utf-8")) if rubrics_path.exists() else {}
    todo = [(tid, [c["answer"] for c in cs if c["answer"].strip()])
            for tid, cs in sorted(by_task.items()) if tid not in rubrics]
    if todo:
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(build_rubric, tid, ans): tid for tid, ans in todo}
            for fut in concurrent.futures.as_completed(futs):
                tid = futs[fut]
                rubrics[tid] = fut.result()
                rubrics_path.write_text(json.dumps(rubrics, indent=2), encoding="utf-8")
                print(f"rubric {tid:15} {len(rubrics[tid])} points", flush=True)

    scores_path = run_dir / "scores.json"
    scores = json.loads(scores_path.read_text(encoding="utf-8")) if scores_path.exists() else {}
    order = [c for c in cells if c["dir"].name not in scores]
    random.Random(42).shuffle(order)          # judge sees no arm grouping

    def one(c):
        pts = rubrics.get(c["task"]) or []
        s = score_answer(c["task"], pts, c["answer"])
        crit = {p["id"] for p in pts if p.get("critical")}
        cov = set(s.get("covered") or [])
        return c["dir"].name, {"task": c["task"], "arm": c["arm"], "rep": c["rep"],
                               "n_points": len(pts), "n_critical": len(crit),
                               "covered": sorted(cov), "critical_covered": len(cov & crit),
                               "distortions": s.get("distortions") or [],
                               "dropped_caveats": s.get("dropped_caveats") or [],
                               "ambiguities": s.get("ambiguities") or [],
                               "out_tokens": c.get("out_tokens"), "chars": c.get("chars"),
                               "text_tokens": c.get("text_tokens"),
                               "error": s.get("error")}

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for fut in concurrent.futures.as_completed([ex.submit(one, c) for c in order]):
            key, rec = fut.result()
            scores[key] = rec
            done += 1
            scores_path.write_text(json.dumps(scores, indent=2), encoding="utf-8")
            if done % 10 == 0 or done == len(order):
                print(f"  scored [{done}/{len(order)}]", flush=True)
    report(scores)
    print(f"\nwrote {scores_path}")


def report(scores):
    by_arm = defaultdict(list)
    for s in scores.values():
        by_arm[s["arm"]].append(s)
    print(f"\n{'arm':16} {'n':>3} {'retention':>10} {'crit ret':>9} {'read_tok':>9} "
          f"{'pts/1k tok':>11} {'distort':>8} {'dropped':>8} {'ambig':>6}")
    for arm, ss in sorted(by_arm.items()):
        n = len(ss)
        ret = sum(len(s["covered"]) / max(s["n_points"], 1) for s in ss) / n
        cret = sum((s["critical_covered"] / s["n_critical"]) if s["n_critical"] else 1.0 for s in ss) / n
        tok = [s.get("text_tokens") for s in ss if s.get("text_tokens")]
        mt = sum(tok) / len(tok) if tok else 0
        dens = sum(len(s["covered"]) / (s["text_tokens"] / 1000) for s in ss if s.get("text_tokens")) / max(len(tok), 1)
        print(f"{arm:16} {n:>3} {ret:>9.1%} {cret:>9.1%} {mt:>7.0f} {dens:>11.1f} "
              f"{sum(len(s['distortions']) for s in ss):>8} {sum(len(s['dropped_caveats']) for s in ss):>8} "
              f"{sum(len(s['ambiguities']) for s in ss):>6}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", help="run dir to judge")
    ap.add_argument("--report", help="re-print the table from a judged run dir")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if args.report:
        d = Path(args.report)
        if not d.exists():
            d = RUNS_DIR / d.name
        return report(json.loads((d / "scores.json").read_text(encoding="utf-8")))
    if args.run:
        if selftest():
            sys.exit("judge not trustworthy; refusing to score the matrix")
        return run(args.run)
    sys.exit("give --selftest, --run <dir> or --report <dir>")


if __name__ == "__main__":
    main()
