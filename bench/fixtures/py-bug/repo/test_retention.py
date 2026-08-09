from retention import windows_overdue


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
