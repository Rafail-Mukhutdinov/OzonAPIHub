def valid_posting_number(pn: str | None) -> bool:
    """Validate posting_number: exclude test and malformed values."""
    if not pn:
        return False
    if pn.upper().startswith('TEST-POSTING'):
        return False
    if '-' not in pn:
        return False
    suffix = pn.split('-')[-1]
    return suffix.isdigit()
