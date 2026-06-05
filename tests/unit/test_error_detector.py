from classctl.core.error_detector import detect


def test_returns_matching_line():
    lines = "all good\nERROR: disk full\nok"
    assert detect(lines, ["error"]) == ["ERROR: disk full"]


def test_matching_is_case_insensitive():
    assert detect("Traceback (most recent call last)", ["traceback"]) == [
        "Traceback (most recent call last)"
    ]


def test_returns_empty_when_no_match():
    assert detect("everything fine\ndone", ["error", "failed"]) == []


def test_empty_output_returns_empty():
    assert detect("", ["error"]) == []


def test_empty_patterns_returns_empty():
    assert detect("ERROR: something", []) == []


def test_multiple_patterns_match_same_line():
    # A line matching multiple patterns should appear only once
    assert detect("error: failed to mount", ["error", "failed"]) == [
        "error: failed to mount"
    ]


def test_multiple_lines_can_match():
    output = "step 1 ok\nERROR: bad\nstep 2 ok\nfailed to connect"
    result = detect(output, ["error", "failed"])
    assert result == ["ERROR: bad", "failed to connect"]
