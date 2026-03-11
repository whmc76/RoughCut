from __future__ import annotations

import roughcut.db.session as db_session
from roughcut.pipeline.tasks import _reset_db_session_state


class _DummyEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def test_reset_db_session_state_disposes_engine_and_clears_singletons():
    engine = _DummyEngine()
    session_factory = object()
    old_worker_mode = db_session._worker_mode

    db_session._engine = engine
    db_session._session_factory = session_factory
    try:
        _reset_db_session_state()
        assert engine.disposed is True
        assert db_session._engine is None
        assert db_session._session_factory is None
    finally:
        db_session._worker_mode = old_worker_mode
