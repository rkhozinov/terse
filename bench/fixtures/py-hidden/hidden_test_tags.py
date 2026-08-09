from tags import parse_tags


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
