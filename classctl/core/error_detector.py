def detect(output: str, patterns: list[str]) -> list[str]:
    """Return lines from output that contain any pattern (case-insensitive).

    Exit codes from scripts are unreliable, so this is the sole mechanism
    for flagging problems. Each matching line appears at most once even if
    multiple patterns hit it.
    """
    if not output or not patterns:
        return []

    lowered = [p.lower() for p in patterns]

    return [
        line
        for line in output.splitlines()
        if any(p in line.lower() for p in lowered)
    ]
