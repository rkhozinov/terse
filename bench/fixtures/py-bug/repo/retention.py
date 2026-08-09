"""Retention window helpers."""


def windows_overdue(last_run_ts, now_ts, interval_s):
    """How many whole intervals have elapsed since last_run_ts.

    A run exactly on the boundary is not overdue: at now_ts - last_run_ts == interval_s
    the next run is due, not the one after it.
    """
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    return (now_ts - last_run_ts) // interval_s + 1
