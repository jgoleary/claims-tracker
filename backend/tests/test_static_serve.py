from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.static_serve import create_spa_router


def _app(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('hi')")
    app = FastAPI()
    app.include_router(create_spa_router(tmp_path))
    return TestClient(app)


def test_serves_index_for_unknown_route(tmp_path):
    client = _app(tmp_path)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "<title>app</title>" in resp.text


def test_serves_existing_asset(tmp_path):
    client = _app(tmp_path)
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_api_path_404s(tmp_path):
    client = _app(tmp_path)
    assert client.get("/api/unknown").status_code == 404


def test_root_serves_index(tmp_path):
    client = _app(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "<title>app</title>" in resp.text
