"""Generate the agentic fixtures.

Each fixture is a directory with:
  repo/       starting state, copied per cell into a scratch dir
  prompt.txt  what the agent is told
  check.sh    grader, run from inside the scratch copy, exit 0 == pass
  keep.txt    files restored from the pristine fixture before grading

`keep.txt` is the anti-cheat: an agent can always make a test pass by editing
the test. Anything listed there is overwritten from the original before check.sh
runs, so edits to graders are silently undone rather than rewarded.

Fixtures are offline by construction: no terraform init (no provider downloads),
no cluster, no package installs beyond what uv already caches.

Regenerate with: uv run python make_fixtures.py
"""
import shutil, stat
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / "fixtures"


def fixture(name, files, prompt, check, keep=()):
    d = ROOT / name
    if d.exists():
        shutil.rmtree(d)
    for rel, body in files.items():
        p = d / "repo" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (d / "prompt.txt").write_text(prompt.strip() + "\n", encoding="utf-8")
    c = d / "check.sh"
    c.write_text("#!/usr/bin/env bash\nset -uo pipefail\n" + check.strip() + "\n", encoding="utf-8")
    c.chmod(c.stat().st_mode | stat.S_IEXEC)
    (d / "keep.txt").write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")


# 1. terraform: add a variable and wire it through -------------------------------
fixture(
    "tf-add",
    {
        "variables.tf": 'variable "project" {\n  type        = string\n  description = "Project slug."\n}\n',
        "locals.tf": 'locals {\n  name_prefix = var.project\n}\n',
        "outputs.tf": 'output "name_prefix" {\n  value = local.name_prefix\n}\n',
    },
    """
Add an `environment` input to this Terraform module and thread it through.

- A new variable `environment`, type string, with a description. No default: callers must set it.
- `local.name_prefix` must become the project and the environment joined by a hyphen, in that order.
- Keep the existing `name_prefix` output working.
- The module must stay `terraform fmt` clean.

Do not run `terraform init`, `plan`, or `apply` -- there is no backend or provider here.
""",
    """
terraform fmt -check -recursive . || { echo "FAIL: not fmt clean"; exit 1; }
grep -qE 'variable[[:space:]]+"environment"' variables.tf || { echo "FAIL: no environment variable"; exit 1; }
grep -A4 -E 'variable[[:space:]]+"environment"' variables.tf | grep -q 'type *= *string' || { echo "FAIL: environment not typed string"; exit 1; }
grep -A4 -E 'variable[[:space:]]+"environment"' variables.tf | grep -q 'description' || { echo "FAIL: environment has no description"; exit 1; }
grep -A4 -E 'variable[[:space:]]+"environment"' variables.tf | grep -q 'default' && { echo "FAIL: environment must not have a default"; exit 1; }
grep -q 'var.project}-${var.environment}' locals.tf || { echo "FAIL: name_prefix not project-environment"; exit 1; }
grep -q 'local.name_prefix' outputs.tf || { echo "FAIL: output broken"; exit 1; }
echo PASS
""",
)

# 2. kubernetes yaml: add resource limits ----------------------------------------
fixture(
    "yaml-limits",
    {
        "deployment.yaml": """apiVersion: apps/v1
kind: Deployment
metadata:
  name: tracking-service
  namespace: test
spec:
  replicas: 2
  selector:
    matchLabels:
      app: tracking-service
  template:
    metadata:
      labels:
        app: tracking-service
    spec:
      containers:
        - name: app
          image: tracking-service:1.4.2
          ports:
            - containerPort: 8080
"""
    },
    """
The `app` container in deployment.yaml has no resource constraints, so it can be scheduled
anywhere and evicted under pressure. Give it requests and limits:

- requests: 100m CPU, 128Mi memory
- limits:   500m CPU, 512Mi memory

Change nothing else. The file must stay valid YAML.
""",
    """
command -v yq >/dev/null || { echo "SKIP: yq missing"; exit 1; }
q() { yq -r "$1" deployment.yaml; }
[ "$(q '.spec.template.spec.containers[0].resources.requests.cpu')" = "100m" ] || { echo "FAIL: cpu request"; exit 1; }
[ "$(q '.spec.template.spec.containers[0].resources.requests.memory')" = "128Mi" ] || { echo "FAIL: mem request"; exit 1; }
[ "$(q '.spec.template.spec.containers[0].resources.limits.cpu')" = "500m" ] || { echo "FAIL: cpu limit"; exit 1; }
[ "$(q '.spec.template.spec.containers[0].resources.limits.memory')" = "512Mi" ] || { echo "FAIL: mem limit"; exit 1; }
[ "$(q '.spec.replicas')" = "2" ] || { echo "FAIL: replicas changed"; exit 1; }
[ "$(q '.spec.template.spec.containers[0].image')" = "tracking-service:1.4.2" ] || { echo "FAIL: image changed"; exit 1; }
echo PASS
""",
)

# 3. python: fix the source, not the test ----------------------------------------
fixture(
    "py-bug",
    {
        "retention.py": '''"""Retention window helpers."""


def windows_overdue(last_run_ts, now_ts, interval_s):
    """How many whole intervals have elapsed since last_run_ts.

    A run exactly on the boundary is not overdue: at now_ts - last_run_ts == interval_s
    the next run is due, not the one after it.
    """
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    return (now_ts - last_run_ts) // interval_s + 1
''',
        "test_retention.py": '''from retention import windows_overdue


def test_no_time_passed():
    assert windows_overdue(0, 0, 60) == 0


def test_exactly_one_interval():
    assert windows_overdue(0, 60, 60) == 1


def test_partial_interval_does_not_count():
    assert windows_overdue(0, 90, 60) == 1


def test_two_intervals():
    assert windows_overdue(0, 120, 60) == 2


def test_rejects_zero_interval():
    import pytest
    with pytest.raises(ValueError):
        windows_overdue(0, 60, 0)
''',
    },
    """
`pytest` fails in this directory. Fix `retention.py` so the suite passes.

The tests encode the intended behaviour and are correct -- do not edit test_retention.py.
""",
    """
uv run --with pytest pytest -q >/dev/null 2>&1 || { echo "FAIL: tests red"; exit 1; }
echo PASS
""",
    keep=("test_retention.py",),
)

# 4. python: implement to spec, graded by tests the agent never sees --------------
fixture(
    "py-hidden",
    {
        "tags.py": '''"""Tag parsing for the alert pipeline."""


def parse_tags(raw):
    """Parse a comma-separated tag string into a sorted list of unique tags.

    - Surrounding whitespace on each tag is stripped.
    - Empty tags (from repeated or trailing commas) are dropped.
    - Comparison is case-insensitive, and the lowercased form is what is returned.
    - The result is sorted and contains no duplicates.
    - None or an empty string yields an empty list.

    >>> parse_tags(" Prod, db ,PROD,, ")
    ['db', 'prod']
    """
    raise NotImplementedError
'''
    },
    """
Implement `parse_tags` in tags.py according to its docstring. Do not change the docstring.
""",
    """
cp "$FIXTURE/hidden_test_tags.py" ./test_tags_hidden.py
uv run --with pytest pytest -q test_tags_hidden.py >/dev/null 2>&1 || { echo "FAIL: hidden tests red"; exit 1; }
echo PASS
""",
)

# the grader for py-hidden lives outside repo/ so the agent never sees it
(ROOT / "py-hidden" / "hidden_test_tags.py").write_text(
    '''from tags import parse_tags


def test_empty():
    assert parse_tags("") == []
    assert parse_tags(None) == []


def test_docstring_example():
    assert parse_tags(" Prod, db ,PROD,, ") == ["db", "prod"]


def test_case_folding_and_dedup():
    assert parse_tags("A,a,B") == ["a", "b"]


def test_sorted():
    assert parse_tags("z,m,a") == ["a", "m", "z"]


def test_only_separators():
    assert parse_tags(",,, ,") == []
''',
    encoding="utf-8",
)

# 5. refactor: remove duplication without breaking behaviour ---------------------
fixture(
    "refactor",
    {
        "report.py": '''"""Cost report rendering."""


def render_daily(rows):
    total = 0.0
    for r in rows:
        total += r["cost"]
    lines = []
    for r in rows:
        pct = (r["cost"] / total * 100) if total else 0.0
        lines.append(f"{r['name']}: ${r['cost']:.2f} ({pct:.1f}%)")
    return "\\n".join(lines)


def render_monthly(rows):
    total = 0.0
    for r in rows:
        total += r["cost"]
    lines = []
    for r in rows:
        pct = (r["cost"] / total * 100) if total else 0.0
        lines.append(f"{r['name']}: ${r['cost']:.2f} ({pct:.1f}%)")
    return "MONTHLY\\n" + "\\n".join(lines)
''',
        "test_report.py": '''from report import render_daily, render_monthly

ROWS = [{"name": "eks", "cost": 30.0}, {"name": "rds", "cost": 10.0}]


def test_daily():
    assert render_daily(ROWS) == "eks: $30.00 (75.0%)\\nrds: $10.00 (25.0%)"


def test_monthly():
    assert render_monthly(ROWS) == "MONTHLY\\neks: $30.00 (75.0%)\\nrds: $10.00 (25.0%)"


def test_empty_does_not_divide_by_zero():
    assert render_daily([]) == ""
''',
    },
    """
`render_daily` and `render_monthly` in report.py are the same function apart from one prefix.
Refactor so the shared logic exists once. Both public functions must keep their current names,
signatures and output. Do not edit test_report.py.
""",
    """
uv run --with pytest pytest -q >/dev/null 2>&1 || { echo "FAIL: tests red"; exit 1; }
n=$(grep -c 'pct = (r\\["cost"\\] / total \\* 100)' report.py)
[ "$n" -le 1 ] || { echo "FAIL: still duplicated ($n copies)"; exit 1; }
echo PASS
""",
    keep=("test_report.py",),
)

print(f"wrote {len(list(ROOT.iterdir()))} fixtures to {ROOT}")
for d in sorted(ROOT.iterdir()):
    print("  -", d.name)
