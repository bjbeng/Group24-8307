from fastapi.testclient import TestClient

from app.main import app


def test_auth_cookies_apply_to_non_auth_routes() -> None:
    client = TestClient(app)
    username = "cookie-path-user"
    password = "password123"

    response = client.post("/api/auth/register", json={"username": username, "password": password})

    assert response.status_code == 200
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert any("access_token=" in header and "Path=/" in header for header in set_cookie_headers)
    assert any("csrf_token=" in header and "Path=/" in header for header in set_cookie_headers)

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200

    history_response = client.get("/api/history")
    assert history_response.status_code == 200
