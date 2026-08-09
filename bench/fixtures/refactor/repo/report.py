"""Cost report rendering."""


def render_daily(rows):
    total = 0.0
    for r in rows:
        total += r["cost"]
    lines = []
    for r in rows:
        pct = (r["cost"] / total * 100) if total else 0.0
        lines.append(f"{r['name']}: ${r['cost']:.2f} ({pct:.1f}%)")
    return "\n".join(lines)


def render_monthly(rows):
    total = 0.0
    for r in rows:
        total += r["cost"]
    lines = []
    for r in rows:
        pct = (r["cost"] / total * 100) if total else 0.0
        lines.append(f"{r['name']}: ${r['cost']:.2f} ({pct:.1f}%)")
    return "MONTHLY\n" + "\n".join(lines)
