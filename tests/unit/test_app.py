from fastapi.testclient import TestClient
from classctl.web.app import create_app


def test_root_serves_html():
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
