# classctl

Инструмент централизованного управления учебными аудиториями. Запускает скрипты подготовки рабочих станций параллельно по SSH, отображает вывод в реальном времени и позволяет оператору реагировать на ошибки без прерывания работы.

---

## Быстрый старт

```bash
# Установка (Linux)
pipx install git+https://github.com/delawer33/classctl

# Права на ARP-сканирование (один раз)
sudo setcap cap_net_raw+ep "$(find ~/.local/share/pipx/venvs/classctl -name python3 -type f | head -1)"

# Запуск
classctl
```

Откройте браузер: **http://127.0.0.1:8000**

Подробные инструкции для Linux и Windows — в [INSTALL.md](INSTALL.md).  
Руководство пользователя — в [GUIDE.md](GUIDE.md).

---

## Что делает classctl

Оператор сидит в аудитории с ноутбуком, подключённым к подсети класса. classctl:

1. **Обнаруживает машины** — ARP-сканирует подсеть и сохраняет список IP/MAC.
2. **Будит машины** — рассылает Wake-on-LAN и ждёт, пока SSH станет доступен.
3. **Запускает прогон** — выполняет скрипты параллельно на всех выбранных машинах, шаг за шагом.
4. **Показывает вывод** — каждая строка stdout/stderr появляется в интерфейсе в реальном времени через WebSocket.
5. **Обнаруживает ошибки** — строки, совпавшие с настраиваемыми паттернами, выделяются; прогон приостанавливается.
6. **Ждёт решения** — оператор выбирает: повторить неудачные машины, пропустить и продолжить, или прервать.

---

## Конфигурация аудитории

Конфигурация хранится в `~/.config/classctl/classrooms.json` и управляется через веб-интерфейс или REST API.

### Поля аудитории

| Поле | Тип | Описание |
|---|---|---|
| `name` | string | Уникальное имя аудитории |
| `subnet` | string | Подсеть в формате CIDR, например `192.168.10.0/24` |
| `ssh_key_path` | string | Путь к закрытому SSH-ключу |
| `script_directory` | string | Путь к каталогу скриптов на рабочих станциях |
| `step_mapping` | object | Отображение номера шага на имя файла скрипта |
| `username` | string | SSH-пользователь (по умолчанию `student`) |
| `wol_timeout` | number | Таймаут ожидания SSH после WoL в секундах (по умолчанию 300) |

### Пример step_mapping

```json
{
  "step_mapping": {
    "1": "01_stop.sh",
    "2": "02_delete.sh",
    "3": "03_reset.sh",
    "4": "04_create.sh",
    "5": "05_shutdown.sh"
  }
}
```

### Паттерны ошибок

Глобальный список подстрок, по которым детектируются ошибки в выводе скриптов. По умолчанию: `error`, `failed`, `traceback`, `exception`. Редактируются в интерфейсе через **Настройки → Паттерны ошибок**.

---

## REST API

Сервер запускается на `http://127.0.0.1:8000`. Интерактивная документация: `http://127.0.0.1:8000/docs`.

### Аудитории

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/classrooms` | Список всех аудиторий |
| `POST` | `/classrooms` | Создать аудиторию |
| `GET` | `/classrooms/{name}` | Получить аудиторию |
| `PUT` | `/classrooms/{name}` | Обновить аудиторию |
| `DELETE` | `/classrooms/{name}` | Удалить аудиторию |

### Машины

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/classrooms/{name}/machines` | Список машин аудитории |
| `POST` | `/classrooms/{name}/machines` | Добавить машину вручную |
| `DELETE` | `/classrooms/{name}/machines/{mac}` | Удалить машину |
| `POST` | `/classrooms/{name}/discover` | ARP-сканирование и слияние результатов |

### Прогоны

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/classrooms/{name}/run` | Запустить прогон |
| `GET` | `/runs/{run_id}/state` | Текущее состояние прогона |
| `POST` | `/runs/{run_id}/decide` | Решение оператора: `retry` / `skip` / `abort` |
| `WS` | `/runs/{run_id}/ws` | WebSocket-стрим событий |

#### Тело запроса POST /run

```json
{
  "start_step": 1,
  "end_step": 4,
  "machine_ips": ["192.168.1.10", "192.168.1.11"],
  "wake_on_lan": true
}
```

`machine_ips: null` — запустить на всех машинах аудитории.

#### События WebSocket

| Тип | Описание |
|---|---|
| `snapshot` | Начальное состояние при подключении |
| `step_started` | Начало шага |
| `machine_output` | Строка вывода с машины |
| `machine_update` | Смена статуса машины |
| `step_evaluated` | Итог шага (переход / пауза) |
| `run_paused` | Прогон ждёт решения оператора |
| `run_finished` | Прогон завершён |
| `wol_sent` | WoL-пакеты отправлены |
| `wol_polling` | Промежуточный статус ожидания SSH |
| `wol_result` | Итог опроса SSH после WoL |
| `run_error` | Ошибка конфигурации |
| `ping` | Keepalive при отсутствии событий |

### Выключение

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/classrooms/{name}/shutdown` | Выключить машины через SSH |

```json
{ "machine_ips": ["192.168.1.10"] }
```

`machine_ips: null` — выключить все. Машины, участвующие в активном прогоне, автоматически исключаются.

### Настройки

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/settings/error-patterns` | Текущие паттерны ошибок |
| `PUT` | `/settings/error-patterns` | Заменить паттерны |

---

## Архитектура

```
classctl/
├── __main__.py          # точка входа, запускает uvicorn
├── core/
│   ├── config.py        # ConfigManager — загрузка и сохранение конфига
│   ├── config_validator.py  # проверка конфига перед прогоном
│   ├── discovery.py     # DiscoveryEngine — обёртка над ARP-сканером
│   ├── error_detector.py    # поиск паттернов ошибок в выводе
│   ├── lan_ip.py        # ARP-сканирование (scapy / ping+arp для Windows)
│   ├── pipeline_runner.py   # PipelineRunner — управляет прогоном
│   ├── run_state_machine.py # RunStateMachine — чистая машина состояний
│   ├── script_executor.py   # SSH-подключение и запуск скрипта
│   ├── shutdown.py      # SSH-выключение одной машины
│   ├── ssh_poller.py    # SSHPoller — ожидание доступности SSH-порта
│   └── wol.py           # отправка Wake-on-LAN пакета
└── web/
    ├── app.py           # FastAPI-приложение, все маршруты
    └── static/          # HTML/CSS/JS фронтенд
```

**Поток выполнения прогона:**

```
start_run (HTTP) → PipelineRunner.run() (asyncio.Task)
    → _wol_phase(): WoL → SSHPoller.wait() → задержка
    → loop: RSM.start_step() → asyncio.gather(_run_one × N)
        → ScriptExecutor.run() → ErrorDetector.detect()
        → RSM.machine_completed/timed_out/disconnected()
    → RSM.evaluate_step() → RUNNING / PAUSED / COMPLETED
    → (если PAUSED) ждёт deliver_decision() из POST /decide
```

Все события (вывод, смена статусов, пауза, завершение) помещаются в `asyncio.Queue` и доставляются клиенту через WebSocket.

---

## Разработка

```bash
git clone https://github.com/delawer33/classctl
cd classctl
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Юнит-тесты
pytest tests/unit/

# Интеграционные тесты (требуют Docker)
pytest tests/integration/ -m integration
```
