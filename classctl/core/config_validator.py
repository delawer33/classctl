import os


def validate(classroom: dict, start_step: int, end_step: int) -> list[str]:
    """Проверяет конфигурацию аудитории classroom перед запуском прогона.

    Принимает словарь аудитории, номер начального шага start_step и конечного end_step.
    Возвращает список строк с описанием ошибок на русском языке. Пустой список означает,
    что конфигурация корректна и прогон может быть запущен. Все проверки выполняются
    локально, без сетевых вызовов.
    """
    errors = []

    key_path = classroom.get("ssh_key_path", "")
    if not os.path.isfile(key_path):
        errors.append(f"SSH-ключ не найден: {key_path}")
        return errors  # дальнейшая проверка без ключа бессмысленна

    if not classroom.get("script_directory", "").strip():
        errors.append("Каталог скриптов не указан")
        return errors

    step_mapping = classroom.get("step_mapping", {})
    for step in range(start_step, end_step + 1):
        if str(step) not in step_mapping:
            errors.append(f"Шаг {step} не задан в маппинге шагов")
            return errors

    return errors
