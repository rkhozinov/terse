from report import render_daily, render_monthly

ROWS = [{"name": "eks", "cost": 30.0}, {"name": "rds", "cost": 10.0}]


def test_daily():
    assert render_daily(ROWS) == "eks: $30.00 (75.0%)\nrds: $10.00 (25.0%)"


def test_monthly():
    assert render_monthly(ROWS) == "MONTHLY\neks: $30.00 (75.0%)\nrds: $10.00 (25.0%)"


def test_empty_does_not_divide_by_zero():
    assert render_daily([]) == ""
