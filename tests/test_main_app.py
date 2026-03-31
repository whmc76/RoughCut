from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_readyz_returns_200_when_dependencies_are_ready(monkeypatch):
    import roughcut.main as main_mod

    async def fake_readiness():
        return {
            "status": "ready",
            "checks": {
                "database": {"status": "ok", "detail": "ok"},
                "redis": {"status": "ok", "detail": "ok"},
                "storage": {"status": "ok", "detail": "ok"},
            },
        }

    monkeypatch.setattr(main_mod, "build_readiness_payload", fake_readiness)
    app = main_mod.create_app()
    client = TestClient(app)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readyz_returns_503_when_dependencies_are_degraded(monkeypatch):
    import roughcut.main as main_mod

    async def fake_readiness():
        return {
            "status": "degraded",
            "checks": {
                "database": {"status": "ok", "detail": "ok"},
                "redis": {"status": "failed", "detail": "connection refused"},
                "storage": {"status": "ok", "detail": "ok"},
            },
        }

    monkeypatch.setattr(main_mod, "build_readiness_payload", fake_readiness)
    app = main_mod.create_app()
    client = TestClient(app)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["redis"]["status"] == "failed"


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


def test_resolve_frontend_dist_finds_built_assets_from_installed_package_layout(
    tmp_path: Path, monkeypatch
):
    import roughcut.main as main_mod

    app_root = tmp_path / "app"
    dist = app_root / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>installed-layout</body></html>", encoding="utf-8")

    fake_module = app_root / ".venv" / "lib" / "python3.11" / "site-packages" / "roughcut" / "main.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("# synthetic module path for test\n", encoding="utf-8")

    monkeypatch.setattr(main_mod, "__file__", str(fake_module))

    assert main_mod._resolve_frontend_dist() == dist.resolve()
