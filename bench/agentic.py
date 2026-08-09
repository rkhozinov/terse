"""Agentic bench: which model and effort can actually do the mechanical work.

run.py measures prose -- tools off, answers judged against a rubric by an LLM.
That says nothing about editing files, which is where the sonnet-for-mechanical
convention lives. Here the model gets a scratch repo and real tools, and the
grade is a check script's exit code. No judge, so no judge noise: the two runs
in this repo's history show LLM scoring carries roughly +/-9 points at n=3,
which is wider than most of the differences we would be looking for.

Usage:
  uv run python agentic.py --arms s-med,o-high --runs 3
  uv run python agentic.py --fixtures py-bug --arms o-high --runs 1
  uv run python agentic.py --selftest        # prove the anti-cheat guard works
"""
import argparse, concurrent.futures, json, os, shutil, statistics, subprocess, sys, tempfile
from collections import defaultdict
from pathlib import Path

from run import ARM_CFG, ARMS, MODEL, claude_bin       # one source of truth for the arms

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
RUNS_DIR = HERE / "runs-agentic"
CELL_TIMEOUT = 600          # tool loops are slower than one-shot prose


def fixture_names():
    return sorted(d.name for d in FIXTURES.iterdir() if (d / "check.sh").exists())


def run_agent(prompt, workdir, out_path, model, effort, timeout=CELL_TIMEOUT):
    """One agentic cell. Tools ON -- that is the whole point -- in a throwaway copy."""
    cmd = [claude_bin(), "-p", prompt,
           "--model", model or MODEL,
           "--output-format", "json",
           "--setting-sources", "project",       # scratch dir has no .claude, so: no hooks, no CLAUDE.md
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--permission-mode", "bypassPermissions",
           "--no-session-persistence"]
    if effort:
        cmd += ["--effort", effort]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    err_path = out_path.with_suffix(".stderr.txt")
    try:
        with open(out_path, "wb") as so, open(err_path, "wb") as se:
            proc = subprocess.Popen(cmd, cwd=str(workdir), stdout=so, stderr=se,
                                    start_new_session=True, env=env)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), 9)
                try:
                    proc.wait(timeout=10)
                except Exception:
                    pass
                se.write(f"\n[KILLED after {timeout}s]".encode())
    except Exception as e:
        out_path.write_text(json.dumps({"error": str(e)[:300]}), encoding="utf-8")
    try:
        j = json.loads(out_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"unparseable: {str(e)[:120]}", "cost": None, "out_tokens": None,
                "turns": None, "duration_ms": None}
    u = j.get("usage") or {}
    return {"cost": j.get("total_cost_usd"), "out_tokens": u.get("output_tokens"),
            "turns": j.get("num_turns"), "duration_ms": j.get("duration_ms"),
            "error": j.get("error") or (j.get("subtype") if j.get("is_error") else None)}


def grade(fixture: Path, workdir: Path):
    """Restore protected files, then run the check.

    Restoring is the anti-cheat: making a test pass by editing the test is the
    single easiest way for an agent to score, and it looks identical to success
    in the result JSON. Anything in keep.txt is overwritten from the pristine
    fixture first, so those edits are undone rather than rewarded.
    """
    keep = (fixture / "keep.txt").read_text(encoding="utf-8").split()
    restored = []
    for rel in keep:
        src = fixture / "repo" / rel
        if src.exists():
            dst = workdir / rel
            tampered = (not dst.exists()) or dst.read_bytes() != src.read_bytes()
            shutil.copy(src, dst)
            if tampered:
                restored.append(rel)
    env = {**os.environ, "FIXTURE": str(fixture)}
    r = subprocess.run(["bash", str(fixture / "check.sh")], cwd=workdir,
                       capture_output=True, text=True, env=env, timeout=180)
    out = (r.stdout + r.stderr).strip().splitlines()
    return {"passed": r.returncode == 0,
            "detail": out[-1] if out else "",
            "tampered": restored}


def cell(fname, arm, rep, out_dir):
    fixture = FIXTURES / fname
    d = out_dir / f"{fname}__{arm}__{rep}"
    d.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"ab-{fname}-"))
    try:
        shutil.copytree(fixture / "repo", work, dirs_exist_ok=True)
        model, effort = ARM_CFG.get(arm, (None, None))
        prompt = (fixture / "prompt.txt").read_text(encoding="utf-8")
        style = ARMS.get(arm)
        if style:
            (work / ".claude" / "output-styles").mkdir(parents=True, exist_ok=True)
            shutil.copy(HERE / "styles" / f"{style}.md",
                        work / ".claude" / "output-styles" / f"{style}.md")
            (work / ".claude" / "settings.json").write_text(
                json.dumps({"outputStyle": style}), encoding="utf-8")
        r = run_agent(prompt, work, d / "_claude.json", model, effort)
        g = grade(fixture, work)
        rec = {"fixture": fname, "arm": arm, "rep": rep,
               "model": model or MODEL, "effort": effort or "(default)", **r, **g}
        (d / "result.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        # keep the worktree only when it failed: that is the only time it is worth reading
        if not g["passed"]:
            shutil.copytree(work, d / "worktree", dirs_exist_ok=True)
        return rec
    finally:
        shutil.rmtree(work, ignore_errors=True)


def selftest():
    """Prove the guard bites: an agent that deletes the test must not score a pass."""
    fixture = FIXTURES / "py-bug"
    work = Path(tempfile.mkdtemp(prefix="ab-selftest-"))
    try:
        shutil.copytree(fixture / "repo", work, dirs_exist_ok=True)
        # the cheat: neuter the test instead of fixing the bug
        (work / "test_retention.py").write_text("def test_nothing():\n    assert True\n")
        g = grade(fixture, work)
        ok = (not g["passed"]) and "test_retention.py" in g["tampered"]
        print(f"{'ok ' if ok else 'XX '} cheat (test gutted) -> passed={g['passed']} "
              f"restored={g['tampered']} detail={g['detail']!r}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="s-med,o-high")
    ap.add_argument("--fixtures", default=",".join(fixture_names()))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    arms = [x for x in a.arms.split(",") if x]
    fixes = [x for x in a.fixtures.split(",") if x]
    unknown = [x for x in arms if x not in ARMS] + [x for x in fixes if x not in fixture_names()]
    if unknown:
        sys.exit(f"unknown: {unknown}")

    stamp = subprocess.run(["date", "+%Y%m%d-%H%M%S"], capture_output=True, text=True).stdout.strip()
    out_dir = RUNS_DIR / stamp
    out_dir.mkdir(parents=True)
    jobs = [(f, arm, rep) for f in fixes for arm in arms for rep in range(a.runs)]
    print(f"{len(jobs)} cells -> {out_dir}")

    results, done = [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(cell, f, arm, rep, out_dir): (f, arm, rep) for f, arm, rep in jobs}
        for fut in concurrent.futures.as_completed(futs):
            done += 1
            try:
                rec = fut.result()
            except Exception as e:
                f, arm, rep = futs[fut]
                rec = {"fixture": f, "arm": arm, "rep": rep, "passed": False,
                       "detail": f"harness error: {str(e)[:120]}", "cost": None,
                       "turns": None, "tampered": []}
            results.append(rec)
            print(f"  [{done}/{len(jobs)}] {rec['fixture']:13} {rec['arm']:9} #{rec['rep']} "
                  f"{'PASS' if rec['passed'] else 'FAIL'} "
                  f"turns={rec.get('turns')} ${rec.get('cost') or 0:.4f} "
                  f"{'TAMPERED=' + ','.join(rec['tampered']) if rec.get('tampered') else ''}"
                  f"{'  ' + rec['detail'] if not rec['passed'] else ''}", flush=True)

    (out_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    report(results)
    print(f"\nwrote {out_dir}")
    return 0


def report(results):
    by_arm = defaultdict(list)
    by_cell = defaultdict(list)
    for r in results:
        by_arm[r["arm"]].append(r)
        by_cell[(r["fixture"], r["arm"])].append(r)

    fixes = sorted({r["fixture"] for r in results})
    arms = sorted({r["arm"] for r in results})
    print(f"\n{'fixture':14}" + "".join(f"{a:>12}" for a in arms))
    for f in fixes:
        row = ""
        for a in arms:
            v = by_cell.get((f, a), [])
            row += f"{sum(x['passed'] for x in v)}/{len(v):<10}" if v else f"{'-':>12}"
        print(f"{f:14}" + row)

    print(f"\n{'arm':10} {'pass rate':>10} {'$/cell':>9} {'$/pass':>9} {'turns':>7} {'tampered':>9}")
    for a in arms:
        v = by_arm[a]
        p = sum(x["passed"] for x in v)
        costs = [x["cost"] for x in v if x.get("cost")]
        turns = [x["turns"] for x in v if x.get("turns")]
        cpc = statistics.mean(costs) if costs else 0
        print(f"{a:10} {p}/{len(v):<8} {cpc:9.4f} "
              f"{(sum(costs) / p if p else float('nan')):9.4f} "
              f"{(statistics.mean(turns) if turns else 0):7.1f} "
              f"{sum(1 for x in v if x.get('tampered')):9}")


if __name__ == "__main__":
    sys.exit(main())
