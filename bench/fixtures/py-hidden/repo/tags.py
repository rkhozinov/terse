"""Tag parsing for the alert pipeline."""


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
