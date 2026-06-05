import os


def validate(classroom: dict, start_step: int, end_step: int) -> list[str]:
    """Validate classroom config before starting a Run.

    Returns a list of Russian-language error strings.
    Empty list means the config is valid and the Run can proceed.
    All checks are local (no network calls).
    """
    errors = []

    key_path = classroom.get("ssh_key_path", "")
    if not os.path.isfile(key_path):
        errors.append(f"SSH-ключ не найден: {key_path}")
        return errors  # no point checking further without a key

    if not classroom.get("script_directory", "").strip():
        errors.append("Каталог скриптов не указан")
        return errors

    step_mapping = classroom.get("step_mapping", {})
    for step in range(start_step, end_step + 1):
        if str(step) not in step_mapping:
            errors.append(f"Шаг {step} не задан в маппинге шагов")
            return errors

    return errors
