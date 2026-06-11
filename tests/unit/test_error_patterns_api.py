from fastapi.testclient import TestClient
from classctl.web.app import create_app
from classctl.core.config import ConfigManager


def client(tmp_path):
    """Создаёт TestClient с изолированным ConfigManager и возвращает пару (клиент, менеджер)."""
    cm = ConfigManager(tmp_path / "config.json")
    return TestClient(create_app(config=cm)), cm


def test_get_returns_default_patterns(tmp_path):
    """Проверяет, что GET /settings/error-patterns возвращает паттерны по умолчанию."""
    c, _ = client(tmp_path)
    r = c.get("/settings/error-patterns")
    assert r.status_code == 200
    patterns = r.json()
    assert "error" in patterns
    assert "failed" in patterns


def test_update_patterns(tmp_path):
    """Проверяет, что PUT /settings/error-patterns заменяет список паттернов."""
    c, _ = client(tmp_path)
    r = c.put("/settings/error-patterns", json=["oops", "fatal"])
    assert r.status_code == 200
    assert c.get("/settings/error-patterns").json() == ["oops", "fatal"]


def test_update_persists(tmp_path):
    """Проверяет, что обновлённые паттерны сохраняются на диск и доступны после перезагрузки."""
    c, cm = client(tmp_path)
    c.put("/settings/error-patterns", json=["oops"])
    # Перезагружаем с диска
    cm2 = ConfigManager(tmp_path / "config.json")
    assert cm2.error_patterns == ["oops"]
