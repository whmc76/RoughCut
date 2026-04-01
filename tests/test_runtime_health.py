from __future__ import annotations


async def test_check_storage_ready_accepts_local_storage_without_client(monkeypatch):
    import roughcut.runtime_health as health_mod

    class LocalStorage:
        def __init__(self) -> None:
            self.bucket_checked = False

        def ensure_bucket(self) -> None:
            self.bucket_checked = True

    storage = LocalStorage()

    monkeypatch.setattr(
        "roughcut.storage.s3.get_storage",
        lambda: storage,
    )

    ok, detail = await health_mod._check_storage_ready()

    assert ok is True
    assert detail == "ok"
    assert storage.bucket_checked is True
