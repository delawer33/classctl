import pytest
from fastapi.testclient import TestClient
from classctl.web.app import create_app
from classctl.core.config import ConfigManager

ROOM_A = {
    "name": "Room A",
    "subnet": "192.168.10.0/24",
    "ssh_key_path": "/home/user/.ssh/id_rsa",
    "script_directory": "/home/student/VBox_install",
    "step_mapping": {
        "1": "01_stop.sh",
        "2": "02_delete.sh",
        "3": "03_reset.sh",
        "4": "04_create.sh",
        "5": "05_shutdown.sh",
    },
}


@pytest.fixture
def client(tmp_path):
    """Создаёт TestClient с изолированным ConfigManager, не затрагивающим ~/.config."""
    cm = ConfigManager(tmp_path / "config.json")
    app = create_app(config=cm)
    return TestClient(app)


def test_list_classrooms_empty(client):
    """Проверяет, что GET /classrooms возвращает пустой список при отсутствии аудиторий."""
    response = client.get("/classrooms")
    assert response.status_code == 200
    assert response.json() == []


def test_create_classroom(client):
    """Проверяет, что POST /classrooms создаёт аудиторию и возвращает 201."""
    response = client.post("/classrooms", json=ROOM_A)
    assert response.status_code == 201
    assert response.json()["name"] == "Room A"


def test_create_duplicate_returns_409(client):
    """Проверяет, что повторное создание аудитории с тем же именем возвращает 409."""
    client.post("/classrooms", json=ROOM_A)
    response = client.post("/classrooms", json=ROOM_A)
    assert response.status_code == 409


def test_get_classroom(client):
    """Проверяет, что GET /classrooms/{name} возвращает данные аудитории по имени."""
    client.post("/classrooms", json=ROOM_A)
    response = client.get("/classrooms/Room A")
    assert response.status_code == 200
    assert response.json()["subnet"] == "192.168.10.0/24"


def test_get_unknown_classroom_returns_404(client):
    """Проверяет, что GET /classrooms/{name} возвращает 404 для несуществующей аудитории."""
    response = client.get("/classrooms/Ghost")
    assert response.status_code == 404


def test_update_classroom(client):
    """Проверяет, что PUT /classrooms/{name} заменяет данные аудитории."""
    client.post("/classrooms", json=ROOM_A)
    updated = {**ROOM_A, "subnet": "10.0.0.0/24"}
    response = client.put("/classrooms/Room A", json=updated)
    assert response.status_code == 200
    assert response.json()["subnet"] == "10.0.0.0/24"


def test_update_unknown_returns_404(client):
    """Проверяет, что PUT /classrooms/{name} возвращает 404 для несуществующей аудитории."""
    response = client.put("/classrooms/Ghost", json=ROOM_A)
    assert response.status_code == 404


def test_delete_classroom(client):
    """Проверяет, что DELETE /classrooms/{name} удаляет аудиторию и она перестаёт быть доступной."""
    client.post("/classrooms", json=ROOM_A)
    response = client.delete("/classrooms/Room A")
    assert response.status_code == 204
    assert client.get("/classrooms/Room A").status_code == 404


def test_delete_unknown_returns_404(client):
    """Проверяет, что DELETE /classrooms/{name} возвращает 404 для несуществующей аудитории."""
    response = client.delete("/classrooms/Ghost")
    assert response.status_code == 404
