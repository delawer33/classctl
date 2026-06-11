from classctl.core.error_detector import detect


def test_returns_matching_line():
    """Проверяет, что detect возвращает строку, содержащую паттерн."""
    lines = "all good\nERROR: disk full\nok"
    assert detect(lines, ["error"]) == ["ERROR: disk full"]


def test_matching_is_case_insensitive():
    """Проверяет, что сравнение с паттерном выполняется без учёта регистра."""
    assert detect("Traceback (most recent call last)", ["traceback"]) == [
        "Traceback (most recent call last)"
    ]


def test_returns_empty_when_no_match():
    """Проверяет, что detect возвращает пустой список если ни одна строка не совпала."""
    assert detect("everything fine\ndone", ["error", "failed"]) == []


def test_empty_output_returns_empty():
    """Проверяет, что пустой вывод возвращает пустой список."""
    assert detect("", ["error"]) == []


def test_empty_patterns_returns_empty():
    """Проверяет, что пустой список паттернов возвращает пустой список."""
    assert detect("ERROR: something", []) == []


def test_multiple_patterns_match_same_line():
    """Проверяет, что строка, подходящая под несколько паттернов, включается в результат только один раз."""
    assert detect("error: failed to mount", ["error", "failed"]) == [
        "error: failed to mount"
    ]


def test_multiple_lines_can_match():
    """Проверяет, что несколько совпавших строк все включаются в результат."""
    output = "step 1 ok\nERROR: bad\nstep 2 ok\nfailed to connect"
    result = detect(output, ["error", "failed"])
    assert result == ["ERROR: bad", "failed to connect"]
