def detect(output: str, patterns: list[str]) -> list[str]:
    """Возвращает строки из output, содержащие хотя бы один паттерн из patterns (без учёта регистра).

    Коды завершения скриптов ненадёжны, поэтому данная функция является единственным
    механизмом обнаружения проблем. Каждая совпавшая строка включается в результат
    не более одного раза, даже если под неё подходят несколько паттернов.
    """
    if not output or not patterns:
        return []

    lowered = [p.lower() for p in patterns]

    return [
        line
        for line in output.splitlines()
        if any(p in line.lower() for p in lowered)
    ]
