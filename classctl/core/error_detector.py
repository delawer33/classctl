def detect(output: str, patterns: list[str]) -> list[str]:
    """Возвращает строки из вывода, содержащие хотя бы один паттерн.

    Коды завершения скриптов ненадёжны, поэтому данная функция является единственным
    механизмом обнаружения проблем. Каждая совпавшая строка включается в результат
    не более одного раза, даже если под неё подходят несколько паттернов.
    Сравнение выполняется без учёта регистра.

    Args:
        output: полный stdout+stderr скрипта.
        patterns: список подстрок для поиска.

    Returns:
        Список строк из output, в которых найден хотя бы один паттерн.
        Пустой список если output или patterns пусты, либо совпадений нет.
    """
    if not output or not patterns:
        return []

    lowered = [p.lower() for p in patterns]

    return [
        line
        for line in output.splitlines()
        if any(p in line.lower() for p in lowered)
    ]
