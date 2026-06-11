import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal

_STALE_THRESHOLD = timedelta(hours=12)

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from classctl.core.config import ConfigManager
from classctl.core.config_validator import validate as validate_classroom
from classctl.core.discovery import DiscoveryEngine
from classctl.core.pipeline_runner import PipelineRunner
from classctl.core.run_state_machine import RunStateMachine
from classctl.core.shutdown import ssh_shutdown
from classctl.core.wol import send_wol


class RunRequest(BaseModel):
    start_step: int = 1
    end_step: int = 4
    machine_ips: list[str] | None = None  # None = все машины
    wake_on_lan: bool = True               # отправить WoL-пакеты и опросить перед запуском


class DecisionRequest(BaseModel):
    action: Literal["retry", "skip", "abort"]
    ips: list[str] | None = None


class ShutdownRequest(BaseModel):
    machine_ips: list[str] | None = None  # None = все машины


async def _run_pipeline(runner: PipelineRunner, on_finish=None) -> None:
    """Запускает runner.run() и перехватывает исключения как события.

    Args:
        runner: экземпляр PipelineRunner для запуска.
        on_finish: необязательный коллбэк, вызываемый по завершению прогона.
    """
    try:
        await runner.run()
    except Exception as exc:
        runner.events.put_nowait({"type": "run_error", "error": str(exc)})
    finally:
        if on_finish:
            on_finish()


def _serialize_state(state) -> dict:
    """Преобразует объект RunState в словарь для сериализации в JSON.

    Args:
        state: объект RunState.

    Returns:
        Словарь с полями phase, current_step, start_step, end_step,
        machines, flagged_lines и output.
    """
    return {
        "phase": state.phase.name,
        "current_step": state.current_step,
        "start_step": state.start_step,
        "end_step": state.end_step,
        "machines": {ip: s.name for ip, s in state.machines.items()},
        "flagged_lines": state.flagged_lines,
        "output": state.output,  # ip → полный вывод, для восстановления UI после перезагрузки
    }

# Статические файлы находятся рядом с этим модулем; путь вычисляется при импорте,
# чтобы он был корректным независимо от рабочего каталога при запуске сервера.
_STATIC_DIR = Path(__file__).parent / "static"

# Путь к конфигурации по умолчанию при реальном запуске приложения (не в тестах)
_DEFAULT_CONFIG_PATH = Path.home() / ".config" / "classctl" / "classrooms.json"


def create_app(config: ConfigManager | None = None, shutdown_fn=None) -> FastAPI:
    """Фабрика приложения FastAPI.

    Args:
        config: экземпляр ConfigManager; если None — создаётся с путём по умолчанию.
                Позволяет тестам инъецировать изолированный ConfigManager.
        shutdown_fn: функция выключения машины; если None — используется ssh_shutdown.

    Returns:
        Сконфигурированное приложение FastAPI со всеми маршрутами.
    """
    if config is None:
        config = ConfigManager(_DEFAULT_CONFIG_PATH)
    _shutdown = shutdown_fn or ssh_shutdown

    app = FastAPI(title="classctl")
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # Активные прогоны по run_id; хранятся в app.state чтобы каждый тест получал изоляцию
    app.state.runs: dict[str, dict] = {}
    # Одновременно может быть активен не более одного прогона по всем аудиториям
    app.state.active_run_id: str | None = None

    @app.get("/")
    def index():
        """Отдаёт главную HTML-страницу интерфейса."""
        return FileResponse(_STATIC_DIR / "index.html")

    # --- Маршруты аудиторий ---

    @app.get("/classrooms")
    def list_classrooms():
        """Возвращает список всех аудиторий из конфигурации."""
        return config.classrooms

    @app.post("/classrooms", status_code=201)
    def create_classroom(classroom: dict):
        """Создаёт новую аудиторию. Возвращает 409 если аудитория с таким именем уже существует."""
        try:
            config.add_classroom(classroom)
        except ValueError:
            raise HTTPException(status_code=409, detail="Classroom already exists")
        return classroom

    @app.get("/classrooms/{name}")
    def get_classroom(name: str):
        """Возвращает данные аудитории по имени. Возвращает 404 если не найдена."""
        try:
            return config.get_classroom(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")

    @app.put("/classrooms/{name}")
    def update_classroom(name: str, classroom: dict):
        """Заменяет данные аудитории. Возвращает 404 если аудитория не найдена."""
        try:
            config.update_classroom(name, classroom)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")
        return classroom

    @app.delete("/classrooms/{name}", status_code=204)
    def delete_classroom(name: str):
        """Удаляет аудиторию. Возвращает 404 если не найдена."""
        try:
            config.delete_classroom(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")
        return Response(status_code=204)

    # --- Маршруты машин ---

    @app.get("/classrooms/{name}/machines")
    def list_machines(name: str):
        """Возвращает список машин аудитории. Возвращает 404 если аудитория не найдена."""
        try:
            return config.get_machines(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")

    @app.post("/classrooms/{name}/machines", status_code=201)
    def add_machine(name: str, machine: dict):
        """Добавляет машину в аудиторию. Возвращает 404 если аудитория не найдена."""
        try:
            config.add_machine(name, machine)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")
        return machine

    @app.delete("/classrooms/{name}/machines/{mac}", status_code=204)
    def remove_machine(name: str, mac: str):
        """Удаляет машину из аудитории по MAC-адресу. Возвращает 404 если не найдена."""
        try:
            config.remove_machine(name, mac)
        except KeyError:
            raise HTTPException(status_code=404, detail="Not found")
        return Response(status_code=204)

    @app.post("/classrooms/{name}/discover")
    def discover_machines(name: str):
        """Запускает ARP-сканирование подсети аудитории и объединяет результаты со списком машин.

        Returns:
            Словарь с полями machines, found_count, new_count и no_hosts_found.
        """
        try:
            room = config.get_classroom(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")
        try:
            found = DiscoveryEngine().discover(room["subnet"])
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        new_count = config.merge_discovered(name, found)
        return {
            "machines": config.get_machines(name),
            "found_count": len(found),
            "new_count": new_count,
            "no_hosts_found": len(found) == 0,
        }

    # --- Маршруты прогонов ---

    @app.post("/classrooms/{name}/run", status_code=202)
    async def start_run(name: str, request: RunRequest):
        """Запускает новый прогон для аудитории.

        Args:
            name: имя аудитории.
            request: параметры прогона — start_step, end_step, machine_ips, wake_on_lan.

        Returns:
            Словарь с полями run_id и stale_machines_warning.
        """
        try:
            room = config.get_classroom(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")

        machines = config.get_machines(name)
        if request.machine_ips is not None:
            machines = [m for m in machines if m["ip"] in request.machine_ips]

        if not machines:
            raise HTTPException(status_code=400, detail="No machines selected")

        if app.state.active_run_id is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Запуск уже активен ({app.state.active_run_id[:8]}…). "
                       "Дождитесь завершения или прервите его.",
            )

        errors = validate_classroom(room, request.start_step, request.end_step)
        if errors:
            raise HTTPException(status_code=400, detail=errors[0])

        target_ips = [m["ip"] for m in machines]
        rsm = RunStateMachine(
            start_step=request.start_step,
            end_step=request.end_step,
            target_ips=target_ips,
        )
        runner = PipelineRunner(
            rsm=rsm,
            classroom=room,
            machines=machines,
            error_patterns=config.error_patterns,
            wol_sender=send_wol if request.wake_on_lan else None,
        )

        updated_at_raw = room.get("machines_updated_at")
        if updated_at_raw:
            updated_at = datetime.fromisoformat(updated_at_raw)
            stale = (datetime.now(timezone.utc) - updated_at) > _STALE_THRESHOLD
        else:
            stale = True

        run_id = str(uuid.uuid4())
        app.state.active_run_id = run_id

        def _clear_active():
            """Снимает блокировку активного прогона после его завершения."""
            if app.state.active_run_id == run_id:
                app.state.active_run_id = None

        task = asyncio.create_task(_run_pipeline(runner, on_finish=_clear_active))
        app.state.runs[run_id] = {"runner": runner, "task": task}
        return {"run_id": run_id, "stale_machines_warning": stale}

    @app.get("/runs/{run_id}/state")
    def get_run_state(run_id: str):
        """Возвращает сериализованное состояние прогона. Возвращает 404 если прогон не найден."""
        entry = app.state.runs.get(run_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Run not found")
        return _serialize_state(entry["runner"].state)

    @app.post("/runs/{run_id}/decide")
    def decide(run_id: str, request: DecisionRequest):
        """Доставляет решение оператора (retry/skip/abort) в очередь прогона.

        Args:
            run_id: идентификатор прогона.
            request: решение с полями action и опциональным ips.

        Returns:
            {'ok': True}
        """
        entry = app.state.runs.get(run_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Run not found")
        entry["runner"].deliver_decision(request.action, request.ips)
        return {"ok": True}

    @app.websocket("/runs/{run_id}/ws")
    async def run_ws(run_id: str, ws: WebSocket):
        """WebSocket-обработчик для стриминга событий прогона клиенту.

        При подключении отправляет снимок текущего состояния, затем стримит события
        из очереди runner.events. Посылает пинги при отсутствии событий.
        Закрывает соединение с кодом 1008 если прогон не найден.

        Args:
            run_id: идентификатор прогона.
            ws: объект WebSocket соединения.
        """
        await ws.accept()
        entry = app.state.runs.get(run_id)
        if not entry:
            await ws.close(code=1008)
            return

        runner = entry["runner"]
        await ws.send_json({"type": "snapshot", "state": _serialize_state(runner.state)})

        try:
            while True:
                try:
                    event = await asyncio.wait_for(runner.events.get(), timeout=1.0)
                    await ws.send_json(event)
                    if event.get("type") == "run_finished":
                        break
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "ping"})
        except WebSocketDisconnect:
            pass

    # --- Маршрут выключения ---

    @app.post("/classrooms/{name}/shutdown")
    async def shutdown_machines(name: str, request: ShutdownRequest):
        """Выключает машины аудитории через SSH.

        Машины, участвующие в активном прогоне, исключаются из выключения.

        Args:
            name: имя аудитории.
            request: список machine_ips для выключения; None означает все машины.

        Returns:
            Словарь с полями results (список результатов по машинам) и skipped.
        """
        try:
            room = config.get_classroom(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")

        machines = config.get_machines(name)
        if request.machine_ips is not None:
            machines = [m for m in machines if m["ip"] in request.machine_ips]

        # Исключаем машины, участвующие в активном прогоне
        skipped = []
        if app.state.active_run_id:
            active_entry = app.state.runs.get(app.state.active_run_id)
            if active_entry:
                active_ips = set(active_entry["runner"].state.machines.keys())
                skipped = [
                    {"ip": m["ip"], "reason": "run_active"}
                    for m in machines if m["ip"] in active_ips
                ]
                machines = [m for m in machines if m["ip"] not in active_ips]

        key_path = room["ssh_key_path"]
        username = room.get("username", "student")

        async def _safe(ip):
            """Вызывает функцию выключения для ip и перехватывает исключения в словарь результата."""
            try:
                return await _shutdown(ip, key_path, username)
            except Exception as exc:
                return {"ip": ip, "ok": False, "error": str(exc)}

        results = await asyncio.gather(*[_safe(m["ip"]) for m in machines])
        return {"results": list(results), "skipped": skipped}

    # --- Маршруты настроек ---

    @app.get("/settings/error-patterns")
    def get_error_patterns():
        """Возвращает текущий список паттернов ошибок."""
        return config.error_patterns

    @app.put("/settings/error-patterns")
    def update_error_patterns(patterns: list[str]):
        """Заменяет список паттернов ошибок и сохраняет конфигурацию.

        Args:
            patterns: новый список паттернов.

        Returns:
            Обновлённый список паттернов.
        """
        config.save_error_patterns(patterns)
        return patterns

    return app
