from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_create_app_returns_placeholder_when_frontend_missing(tmp_path: Path, monkeypatch):
    import roughcut.main as main_mod

    monkeypatch.setattr(main_mod, "_FRONTEND_DIST", tmp_path / "missing-dist")
    app = main_mod.create_app()
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 503
    assert "frontend not built" in response.text.lower()


def test_create_app_serves_frontend_dist_index(tmp_path: Path, monkeypatch):
    import roughcut.main as main_mod

    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>roughcut-react</body></html>", encoding="utf-8")
    monkeypatch.setattr(main_mod, "_FRONTEND_DIST", dist)
    app = main_mod.create_app()
    client = TestClient(app)

    response = client.get("/jobs")

    assert response.status_code == 200
    assert "roughcut-react" in response.text
